import threading
import time
from collections import deque

import cv2
import numpy as np
import rclpy
from ament_index_python.packages import get_package_share_directory
from flask import Flask, Response, jsonify, render_template, request
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import CompressedImage, Image
from std_msgs.msg import String


class FrameStore:
    def __init__(self):
        self.condition = threading.Condition()
        self.frames = {'raw': None, 'detection': None}
        self.sequence = {'raw': 0, 'detection': 0}
        self.received_at = {'raw': 0.0, 'detection': 0.0}
        self.frame_times = {'raw': deque(maxlen=60), 'detection': deque(maxlen=60)}

    def put(self, source, jpeg):
        now = time.monotonic()
        with self.condition:
            self.frames[source] = jpeg
            self.sequence[source] += 1
            self.received_at[source] = now
            self.frame_times[source].append(now)
            self.condition.notify_all()

    def wait_for_frame(self, source, previous, timeout=2.0):
        with self.condition:
            self.condition.wait_for(
                lambda: self.sequence[source] != previous, timeout=timeout)
            return self.sequence[source], self.frames[source]

    def status(self):
        now = time.monotonic()
        result = {}
        with self.condition:
            for source in self.frames:
                times = self.frame_times[source]
                fps = 0.0
                if len(times) > 1 and times[-1] > times[0]:
                    fps = (len(times) - 1) / (times[-1] - times[0])
                age = None if not self.received_at[source] else now - self.received_at[source]
                result[source] = {
                    'connected': age is not None and age < 2.5,
                    'fps': round(fps, 1),
                    'age_seconds': None if age is None else round(age, 1),
                }
        return result


class WebVideoNode(Node):
    def __init__(self):
        super().__init__('web_video_server')
        self.host = self.declare_parameter('host', '0.0.0.0').value
        self.port = int(self.declare_parameter('port', 8080).value)
        self.jpeg_quality = int(self.declare_parameter('jpeg_quality', 75).value)
        self.max_detection_fps = float(
            self.declare_parameter('max_detection_fps', 10.0).value)
        self.last_detection_encode = 0.0
        self.store = FrameStore()

        qos = QoSProfile(depth=1)
        qos.reliability = ReliabilityPolicy.BEST_EFFORT
        qos.durability = DurabilityPolicy.VOLATILE
        self.raw_subscription = self.create_subscription(
            CompressedImage, '/image_raw/compressed', self.on_raw, qos)
        self.detection_subscription = self.create_subscription(
            Image, '/camera/image_det', self.on_detection, qos)
        self.command_publisher = self.create_publisher(String, '/agent/command', 10)
        self.app = self.create_app()
        self.server_thread = threading.Thread(target=self.run_server, daemon=True)
        self.server_thread.start()
        self.get_logger().info(
            f'web viewer ready at http://{self.host}:{self.port}')

    def on_raw(self, message):
        if message.data:
            self.store.put('raw', bytes(message.data))

    def on_detection(self, message):
        now = time.monotonic()
        if now - self.last_detection_encode < 1.0 / max(self.max_detection_fps, 0.1):
            return
        if message.encoding not in ('rgb8', 'bgr8') or message.step < message.width * 3:
            self.get_logger().warning(
                f'unsupported annotated image encoding: {message.encoding}')
            return
        pixels = np.frombuffer(message.data, dtype=np.uint8)
        required = int(message.step * message.height)
        if pixels.size < required:
            return
        image = pixels[:required].reshape((message.height, message.step))
        image = image[:, :message.width * 3].reshape((message.height, message.width, 3))
        if message.encoding == 'rgb8':
            image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
        success, encoded = cv2.imencode(
            '.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality])
        if success:
            self.last_detection_encode = now
            self.store.put('detection', encoded.tobytes())

    def stream(self, source):
        sequence = -1
        while rclpy.ok():
            sequence, frame = self.store.wait_for_frame(source, sequence)
            if frame is None:
                continue
            yield (b'--frame\r\nContent-Type: image/jpeg\r\n'
                   b'Cache-Control: no-cache\r\n\r\n' + frame + b'\r\n')

    def create_app(self):
        template_folder = get_package_share_directory('web_video_server') + '/templates'
        app = Flask(__name__, template_folder=template_folder)

        @app.route('/', methods=['GET'])
        def index():
            return render_template('index.html')

        @app.route('/stream/<source>', methods=['GET'])
        def video_stream(source):
            if source not in ('raw', 'detection'):
                return jsonify({'error': 'unknown source'}), 404
            return Response(
                self.stream(source),
                mimetype='multipart/x-mixed-replace; boundary=frame',
                headers={'Cache-Control': 'no-store, no-cache, must-revalidate'})

        @app.route('/api/status', methods=['GET'])
        def status():
            return jsonify(self.store.status())

        @app.route('/api/command', methods=['POST'])
        def command():
            value = str((request.get_json(silent=True) or {}).get('command', ''))
            allowed = {'start_camera', 'stop_camera', 'start_tracking',
                       'stop_tracking', 'status'}
            if value not in allowed:
                return jsonify({'ok': False, 'error': 'unsupported command'}), 400
            message = String()
            message.data = value
            self.command_publisher.publish(message)
            return jsonify({'ok': True, 'command': value})

        @app.route('/healthz', methods=['GET'])
        def health():
            return jsonify({'ok': True, 'streams': self.store.status()})

        return app

    def run_server(self):
        self.app.run(host=self.host, port=self.port, threaded=True, use_reloader=False)


def main(args=None):
    rclpy.init(args=args)
    node = WebVideoNode()
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
