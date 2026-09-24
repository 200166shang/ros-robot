import json
import re
import threading
import time
import uuid
from collections import deque
from pathlib import Path

import cv2
import numpy as np
import rclpy
from ament_index_python.packages import get_package_share_directory
from flask import Flask, Response, jsonify, render_template, request, send_file, url_for
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import CompressedImage, Image
from std_msgs.msg import String

from robot_interfaces.msg import HeadState
from robot_head.catalog import MOTION_CATALOG, catalog_payload

from .turn_store import (
    AudioResponseUnavailable,
    TurnEventStore,
    TurnInProgressError,
)


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
        self.host = self.declare_parameter('host', '127.0.0.1').value
        self.port = int(self.declare_parameter('port', 8080).value)
        self.jpeg_quality = int(self.declare_parameter('jpeg_quality', 75).value)
        self.max_detection_fps = float(
            self.declare_parameter('max_detection_fps', 10.0).value)
        self.last_detection_encode = 0.0
        run_log_dir = self.declare_parameter(
            'run_log_dir',
            '/home/orangepi/local-data/ros-robot/runs',
        ).value
        try:
            self.turns = TurnEventStore(run_log_dir=run_log_dir)
        except OSError as error:
            self.get_logger().warning(
                'turn event file logging is disabled: {}'.format(error)
            )
            self.turns = TurnEventStore()
        self.audio_dir = self.declare_parameter(
            'web_audio_dir',
            '/home/orangepi/local-data/ros-robot/web-audio',
        ).value
        self.store = FrameStore()
        self.head_state_lock = threading.Lock()
        self.latest_head_state = None
        self.head_state_received_at = 0.0

        qos = QoSProfile(depth=1)
        qos.reliability = ReliabilityPolicy.BEST_EFFORT
        qos.durability = DurabilityPolicy.VOLATILE
        self.raw_subscription = self.create_subscription(
            CompressedImage, '/image_raw/compressed', self.on_raw, qos)
        self.detection_subscription = self.create_subscription(
            Image, '/camera/image_det', self.on_detection, qos)
        self.command_publisher = self.create_publisher(String, '/agent/command', 10)
        self.turn_request_publisher = self.create_publisher(
            String, '/llm/turn/request', 10)
        self.web_tts_publisher = self.create_publisher(
            String, '/voice/web_tts_request', 10)
        self.create_subscription(
            String, '/llm/turn/event', self.on_turn_event, 10)
        self.create_subscription(
            HeadState, '/robot/head/state', self.on_head_state, 10)
        self.app = self.create_app()
        self.server_thread = threading.Thread(target=self.run_server, daemon=True)
        self.server_thread.start()
        self.get_logger().info(
            f'web viewer ready at http://{self.host}:{self.port}')

    def on_raw(self, message):
        if message.data:
            self.store.put('raw', bytes(message.data))

    def on_turn_event(self, message):
        try:
            event = json.loads(message.data)
            if not isinstance(event, dict) or event.get('schema_version') != 1:
                raise ValueError('unsupported turn event version')
            self.turns.ingest_event(event)
        except (TypeError, ValueError) as error:
            self.get_logger().warning(
                'discarded malformed turn event: {}'.format(error)
            )

    def on_head_state(self, message):
        state = {
            'backend': message.backend,
            'motion': message.motion,
            'phase': message.phase,
            'expression': message.expression,
            'pitch_deg': round(float(message.pitch_deg), 1),
            'yaw_deg': round(float(message.yaw_deg), 1),
            'simulated': bool(message.simulated),
            'motion_id': message.motion_id,
            'message': message.message,
        }
        with self.head_state_lock:
            self.latest_head_state = state
            self.head_state_received_at = time.monotonic()

    def head_status(self):
        with self.head_state_lock:
            state = None if self.latest_head_state is None else dict(self.latest_head_state)
            received_at = self.head_state_received_at
        age = None if not received_at else max(0.0, time.monotonic() - received_at)
        if state is None:
            state = {
                'backend': 'unknown',
                'motion': '',
                'phase': 'offline',
                'expression': '正常',
                'pitch_deg': 90.0,
                'yaw_deg': 90.0,
                'simulated': True,
                'motion_id': '',
                'message': '尚未收到虚拟头部状态。',
            }
        state['connected'] = age is not None and age < 2.0
        state['age_seconds'] = None if age is None else round(age, 1)
        return state

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
        package_share = Path(get_package_share_directory('web_video_server'))
        template_folder = str(package_share / 'templates')
        static_folder = package_share / 'static'
        app = Flask(
            __name__, template_folder=template_folder,
            static_folder=str(static_folder), static_url_path='/static')

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

        @app.route('/api/head/state', methods=['GET'])
        def head_state():
            return jsonify(self.head_status())

        @app.route('/api/head/catalog', methods=['GET'])
        def head_catalog():
            return jsonify({
                'backend': 'sim',
                'simulated': True,
                'motions': catalog_payload(),
            })

        @app.route('/api/head/assets', methods=['GET'])
        def head_assets():
            emotion_root = static_folder / 'emotions'
            expressions = {}
            for expression in ('正常', '微笑', '睡觉', '苏醒', '兴奋'):
                directory = emotion_root / expression
                if not directory.is_dir():
                    expressions[expression] = []
                    continue
                if expression == '兴奋':
                    paths = [
                        path for path in directory.rglob('*.jpg')
                        if any('2可循环动作' in part for part in path.parts)
                    ]
                else:
                    paths = list(directory.rglob('*.jpg'))

                def frame_order(path):
                    try:
                        return (0, int(path.stem))
                    except ValueError:
                        return (1, path.name.lower())

                paths.sort(key=frame_order)
                expressions[expression] = [
                    url_for(
                        'static',
                        filename=path.relative_to(static_folder).as_posix(),
                    )
                    for path in paths
                ]
            return jsonify({'expressions': expressions})

        @app.route('/api/run', methods=['GET'])
        def run_status():
            return jsonify({
                'run_id': self.turns.run_id,
                'content_logging': False,
                'event_logging': self.turns.event_logging_enabled,
            })

        @app.route('/api/turn', methods=['POST'])
        def submit_turn():
            payload = request.get_json(silent=True)
            text = payload.get('text') if isinstance(payload, dict) else None
            if not isinstance(text, str) or not text.strip():
                return jsonify({'ok': False, 'error': '请输入文本内容。'}), 400
            text = text.strip()
            if len(text) > 4000 or len(text.encode('utf-8')) > 12000:
                return jsonify({
                    'ok': False,
                    'error': '输入过长，请控制在 4000 个字符以内。',
                }), 413

            if self.turn_request_publisher.get_subscription_count() == 0:
                return jsonify({
                    'ok': False,
                    'error': '本地 Qwen ROS 桥接节点未连接，请确认演示已启动。',
                }), 503

            turn_id = uuid.uuid4().hex
            try:
                turn = self.turns.create_turn(turn_id, text)
            except TurnInProgressError:
                return jsonify({
                    'ok': False,
                    'error': '上一轮仍在处理中，请等它结束后再发送。',
                }), 409
            message = String()
            message.data = json.dumps({
                'schema_version': 1,
                'turn_id': turn_id,
                'run_id': self.turns.run_id,
                'text': text,
            }, ensure_ascii=False)
            try:
                self.turn_request_publisher.publish(message)
            except Exception as error:
                self.turns.ingest_event({
                    'turn_id': turn_id,
                    'run_id': self.turns.run_id,
                    'stage': 'failed',
                    'status': 'failed',
                    'error_code': 'request_publish_failed',
                    'response_text': '请求没有送入 ROS，请确认服务仍在运行。',
                })
                self.get_logger().error(
                    'failed to publish web turn ({})'.format(
                        type(error).__name__
                    )
                )
                return jsonify({'ok': False, 'error': '请求提交失败。'}), 503
            return jsonify({
                'ok': True,
                'turn_id': turn_id,
                'run_id': self.turns.run_id,
                'turn': turn,
            }), 202

        @app.route('/api/turn/<turn_id>', methods=['GET'])
        def get_turn(turn_id):
            turn = self.turns.get_turn(turn_id)
            if turn is None:
                return jsonify({'error': 'unknown turn'}), 404
            return jsonify(turn)

        @app.route('/api/turn/<turn_id>/audio', methods=['POST'])
        def request_turn_audio(turn_id):
            turn = self.turns.get_turn(turn_id)
            if turn is None:
                return jsonify({'ok': False, 'error': 'unknown turn'}), 404
            try:
                turn, should_publish = self.turns.request_audio(turn_id)
            except AudioResponseUnavailable:
                return jsonify({
                    'ok': False,
                    'error': '请先等待文字回复完成。',
                }), 409

            if turn['audio_status'] == 'ready':
                return jsonify({
                    'ok': True,
                    'turn_id': turn_id,
                    'audio_status': 'ready',
                }), 200
            if should_publish:
                if self.web_tts_publisher.get_subscription_count() == 0:
                    self.turns.ingest_event({
                        'turn_id': turn_id,
                        'run_id': turn['run_id'],
                        'stage': 'audio',
                        'status': 'failed',
                        'audio_status': 'failed',
                        'error_code': 'voice_node_unavailable',
                    })
                    return jsonify({
                        'ok': False,
                        'error': '语音合成节点未连接，请检查 robot_voice。',
                    }), 503
                message = String()
                message.data = json.dumps({
                    'schema_version': 1,
                    'turn_id': turn_id,
                    'run_id': turn['run_id'],
                    'text': turn['response_text'],
                }, ensure_ascii=False)
                try:
                    self.web_tts_publisher.publish(message)
                except Exception as error:
                    self.turns.ingest_event({
                        'turn_id': turn_id,
                        'run_id': turn['run_id'],
                        'stage': 'audio',
                        'status': 'failed',
                        'audio_status': 'failed',
                        'error_code': 'audio_request_publish_failed',
                    })
                    self.get_logger().error(
                        'failed to publish browser TTS request ({})'.format(
                            type(error).__name__
                        )
                    )
                    return jsonify({
                        'ok': False,
                        'error': '语音请求提交失败。',
                    }), 503
            return jsonify({
                'ok': True,
                'turn_id': turn_id,
                'audio_status': turn['audio_status'],
            }), 202

        @app.route('/api/turn/<turn_id>/audio', methods=['GET'])
        def get_turn_audio(turn_id):
            turn = self.turns.get_turn(turn_id)
            if turn is None:
                return jsonify({'error': 'unknown turn'}), 404
            if not re.fullmatch(r'[0-9a-f]{32}', turn_id):
                return jsonify({'error': 'invalid turn id'}), 400
            run_id = turn['run_id']
            if not re.fullmatch(r'[0-9a-f]{32}', run_id):
                return jsonify({'error': 'invalid run id'}), 400
            audio_path = Path(self.audio_dir) / run_id / (turn_id + '.wav')
            if turn['audio_status'] != 'ready' or not audio_path.is_file():
                return jsonify({'error': 'audio is not ready'}), 404
            return send_file(str(audio_path), mimetype='audio/wav')

        @app.route('/api/turn/active', methods=['GET'])
        def get_active_turn():
            return jsonify({'turn': self.turns.active_turn()})

        @app.route('/api/command', methods=['POST'])
        def command():
            payload = request.get_json(silent=True)
            value = payload.get('command') if isinstance(payload, dict) else None
            if not isinstance(value, str):
                return jsonify({'ok': False, 'error': 'command must be text'}), 400
            value = value.strip()
            allowed = {'start_camera', 'stop_camera', 'start_tracking',
                       'stop_tracking', 'status', 'head_cancel'} | set(MOTION_CATALOG)
            if value not in allowed:
                return jsonify({'ok': False, 'error': 'unsupported command'}), 400
            if value in MOTION_CATALOG or value == 'head_cancel':
                if self.command_publisher.get_subscription_count() == 0:
                    return jsonify({
                        'ok': False,
                        'error': 'Agent 未连接，无法提交虚拟头部动作。',
                    }), 503
                state = self.head_status()
                if not state['connected'] or state['backend'] != 'sim':
                    return jsonify({
                        'ok': False,
                        'error': '虚拟头部仿真节点未在线，请先启动演示。',
                    }), 503
            message = String()
            message.data = value
            self.command_publisher.publish(message)
            return jsonify({
                'ok': True,
                'command': value,
                'simulated': value in MOTION_CATALOG or value == 'head_cancel',
            }), 202

        @app.route('/healthz', methods=['GET'])
        def health():
            return jsonify({
                'ok': True,
                'run_id': self.turns.run_id,
                'streams': self.store.status(),
            })

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
