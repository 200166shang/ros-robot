"""Publish a virtual person projection and detections for software-in-the-loop."""

import time

import rclpy
from rcl_interfaces.msg import SetParametersResult
from rclpy.node import Node

from robot_interfaces.msg import BaseState, Det, Dets, SimPersonState

from .person_projection import project_person


class VirtualPersonNode(Node):
    def __init__(self):
        super().__init__('virtual_person_sim')
        self.enabled = bool(self.declare_parameter('person_enabled', True).value)
        self.person_x = float(self.declare_parameter('person_x_m', 2.5).value)
        self.person_y = float(self.declare_parameter('person_y_m', 0.8).value)
        self.image_width = int(self.declare_parameter('image_width', 640).value)
        self.image_height = int(self.declare_parameter('image_height', 360).value)
        self.horizontal_fov = float(
            self.declare_parameter('horizontal_fov_deg', 70.0).value)
        self.person_height = float(
            self.declare_parameter('person_height_m', 1.65).value)
        self.max_range = float(self.declare_parameter('max_range_m', 8.0).value)
        self.base_state = None
        self.base_state_received_at = 0.0
        self.frame_count = 0

        self.detection_publisher = self.create_publisher(
            Dets, '/robot/sim/detections', 10)
        self.state_publisher = self.create_publisher(
            SimPersonState, '/robot/sim/person_state', 10)
        self.create_subscription(
            BaseState, '/robot/sim/base_state', self.on_base_state, 10)
        self.timer = self.create_timer(0.1, self.publish_frame)
        self.add_on_set_parameters_callback(self.on_parameters_changed)

    def on_parameters_changed(self, parameters):
        requested = [
            parameter for parameter in parameters
            if parameter.name == 'person_enabled'
        ]
        if len(requested) != len(parameters) or len(requested) != 1:
            return SetParametersResult(
                successful=False,
                reason='only person_enabled can be changed while simulation is running',
            )
        self.enabled = bool(requested[0].value)
        self.get_logger().info(
            'virtual person visibility {}'.format(
                'enabled' if self.enabled else 'disabled'))
        return SetParametersResult(successful=True)


    def on_base_state(self, message):
        self.base_state = message
        self.base_state_received_at = time.monotonic()

    def publish_frame(self):
        self.frame_count += 1
        stamp = self.get_clock().now().to_msg()
        frame_id = 'sim_camera_{:08d}'.format(self.frame_count)
        detection_array = Dets()
        detection_array.header.stamp = stamp
        detection_array.header.frame_id = frame_id
        detection_array.image_width = self.image_width
        detection_array.image_height = self.image_height

        projection = None
        state = self.base_state
        fresh = (
            state is not None
            and time.monotonic() - self.base_state_received_at < 0.5
        )
        if self.enabled and fresh:
            projection = project_person(
                state.ground_truth_x,
                state.ground_truth_y,
                state.ground_truth_yaw,
                self.person_x,
                self.person_y,
                self.image_width,
                self.image_height,
                self.horizontal_fov,
                self.person_height,
                self.max_range,
            )

        person_state = SimPersonState()
        person_state.header.stamp = stamp
        person_state.header.frame_id = frame_id
        person_state.visible = projection is not None
        person_state.source = 'synthetic_world_projection'
        person_state.target_id = 'virtual_person_1'
        person_state.world_x = self.person_x
        person_state.world_y = self.person_y
        person_state.image_width = self.image_width
        person_state.image_height = self.image_height
        if projection is not None:
            detection = Det()
            detection.x1 = projection['x1']
            detection.y1 = projection['y1']
            detection.x2 = projection['x2']
            detection.y2 = projection['y2']
            detection.confidence = 0.99
            detection.class_name = 'person'
            detection.class_id = 0
            detection.object_id = 1
            detection_array.detections.append(detection)
            person_state.range_m = projection['range_m']
            person_state.bearing_rad = projection['bearing_rad']
            person_state.x1 = projection['x1']
            person_state.y1 = projection['y1']
            person_state.x2 = projection['x2']
            person_state.y2 = projection['y2']

        self.detection_publisher.publish(detection_array)
        self.state_publisher.publish(person_state)


def main(args=None):
    rclpy.init(args=args)
    node = VirtualPersonNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
