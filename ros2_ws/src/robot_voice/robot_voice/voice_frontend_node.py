"""One-shot half-duplex voice route into the existing safe text bridge."""

import tempfile
import threading
from pathlib import Path

import rclpy
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from std_msgs.msg import String
from std_srvs.srv import Trigger

from .audio_io import play_wav
from .audio_sources import create_audio_source
from .sherpa_asr import SherpaOnnxAsr
from .sherpa_tts import SherpaOnnxTts


ASR_MODEL_DIR = (
    "/home/orangepi/models/voice/"
    "sherpa-onnx-streaming-zipformer-small-bilingual-zh-en-2023-02-16"
)
TTS_MODEL_DIR = "/home/orangepi/models/voice/vits-piper-zh_CN-xiao_ya-medium"
SHERPA_BIN_DIR = "/home/orangepi/venvs/sherpa-onnx/bin"


class VoiceFrontendNode(Node):
    """Capture one utterance, forward text, then synthesize the matching reply."""

    def __init__(self):
        super().__init__("voice_frontend")
        self._record_executable = self.declare_parameter(
            "record_executable", "arecord"
        ).value
        self._play_executable = self.declare_parameter("play_executable", "aplay").value
        self._record_device = self.declare_parameter(
            "record_device", "plughw:2,0"
        ).value
        self._playback_device = self.declare_parameter(
            "playback_device", "plughw:0,0"
        ).value
        self._record_seconds = int(
            self.declare_parameter("record_seconds", 8).value
        )
        self._audio_source_mode = self.declare_parameter(
            "audio_source", "microphone"
        ).value
        input_wav_path = self.declare_parameter("input_wav_path", "").value
        self._asr_timeout = float(
            self.declare_parameter("asr_timeout_seconds", 90.0).value
        )
        self._llm_timeout = float(
            self.declare_parameter("llm_response_timeout_seconds", 150.0).value
        )
        self._tts_timeout = float(
            self.declare_parameter("tts_timeout_seconds", 90.0).value
        )
        self._num_threads = int(self.declare_parameter("num_threads", 2).value)
        self._play_audio = bool(self.declare_parameter("play_audio", True).value)

        asr_executable = self.declare_parameter(
            "asr_executable", SHERPA_BIN_DIR + "/sherpa-onnx"
        ).value
        asr_dir = self.declare_parameter("asr_model_dir", ASR_MODEL_DIR).value
        self._audio_source = create_audio_source(
            self._audio_source_mode,
            input_wav_path=input_wav_path,
            record_executable=self._record_executable,
            record_device=self._record_device,
            record_seconds=self._record_seconds,
        )
        tts_executable = self.declare_parameter(
            "tts_executable", SHERPA_BIN_DIR + "/sherpa-onnx-offline-tts"
        ).value
        tts_dir = self.declare_parameter("tts_model_dir", TTS_MODEL_DIR).value

        input_topic = self.declare_parameter(
            "input_topic", "/llm/user_input"
        ).value
        response_topic = self.declare_parameter(
            "response_topic", "/llm/response"
        ).value
        capture_service = self.declare_parameter(
            "capture_service", "/voice/capture"
        ).value

        self._asr = SherpaOnnxAsr(
            executable=asr_executable,
            tokens=str(Path(asr_dir) / "tokens.txt"),
            encoder=str(Path(asr_dir) / "encoder-epoch-99-avg-1.int8.onnx"),
            decoder=str(Path(asr_dir) / "decoder-epoch-99-avg-1.onnx"),
            joiner=str(Path(asr_dir) / "joiner-epoch-99-avg-1.int8.onnx"),
            num_threads=self._num_threads,
            timeout_seconds=self._asr_timeout,
        )
        self._tts = SherpaOnnxTts(
            executable=tts_executable,
            model=str(Path(tts_dir) / "zh_CN-xiao_ya-medium.onnx"),
            lexicon=str(Path(tts_dir) / "lexicon.txt"),
            tokens=str(Path(tts_dir) / "tokens.txt"),
            rule_fsts=",".join(
                str(Path(tts_dir) / name)
                for name in ("phone.fst", "date.fst", "number.fst")
            ),
            num_threads=self._num_threads,
            timeout_seconds=self._tts_timeout,
        )

        self._state_lock = threading.Lock()
        self._busy = False
        self._waiting_for_response = False
        self._response_text = None
        self._response_event = threading.Event()

        self._input_publisher = self.create_publisher(String, input_topic, 10)
        self.create_subscription(String, response_topic, self._on_llm_response, 10)
        self.create_service(Trigger, capture_service, self._on_capture_request)

        self.get_logger().info(
            "voice frontend ready: Trigger {} -> {}/ASR -> {} -> {} -> TTS; "
            "single-flight, no Agent or motion publisher".format(
                capture_service,
                self._audio_source_mode,
                input_topic,
                response_topic,
            )
        )

    def _on_capture_request(self, _request, response):
        with self._state_lock:
            if self._busy:
                response.success = False
                response.message = "语音回合正在处理中，请等待当前回合结束。"
                return response
            self._busy = True

        worker = threading.Thread(target=self._run_voice_turn, daemon=True)
        worker.start()
        response.success = True
        if self._audio_source_mode == "microphone":
            response.message = "已开始录音；请立即说话，并在句尾留出静音。"
        else:
            response.message = "已开始处理 WAV 测试样本。"
        return response

    def _on_llm_response(self, message):
        with self._state_lock:
            if not self._waiting_for_response:
                return
            self._response_text = message.data.strip()
            self._waiting_for_response = False
            self._response_event.set()

    def _run_voice_turn(self):
        try:
            with tempfile.TemporaryDirectory(prefix="robot-voice-") as temp_dir:
                recording_path = str(Path(temp_dir) / "input.wav")
                audio_info = self._audio_source.capture(recording_path)
                self.get_logger().info(
                    "recorded {} frames at {} Hz; running local ASR".format(
                        audio_info["frames"], audio_info["sample_rate"]
                    )
                )
                transcript = self._asr.transcribe(recording_path)
                self.get_logger().info(
                    "ASR transcript ready ({} characters)".format(len(transcript))
                )

                with self._state_lock:
                    self._response_text = None
                    self._response_event.clear()
                    self._waiting_for_response = True
                user_input = String()
                user_input.data = transcript
                self._input_publisher.publish(user_input)

                if not self._response_event.wait(self._llm_timeout):
                    with self._state_lock:
                        self._waiting_for_response = False
                    raise RuntimeError("timed out waiting for /llm/response")

                with self._state_lock:
                    response_text = self._response_text or ""
                if not response_text:
                    raise RuntimeError("/llm/response was empty")

                tts_path = str(Path(temp_dir) / "response.wav")
                self._tts.synthesize(response_text, tts_path)
                self.get_logger().info(
                    "TTS WAV generated; response length={} characters".format(
                        len(response_text)
                    )
                )
                if self._play_audio:
                    duration = play_wav(
                        self._play_executable,
                        self._playback_device,
                        tts_path,
                    )
                    self.get_logger().info(
                        "ALSA output completed ({:.2f}s); audible sound requires "
                        "connected headphones or an amplified speaker".format(duration)
                    )
                else:
                    self.get_logger().info("play_audio=false; leaving playback disabled")
        except Exception as error:
            self.get_logger().error(
                "voice turn failed ({}): {}".format(type(error).__name__, error)
            )
        finally:
            with self._state_lock:
                self._waiting_for_response = False
                self._busy = False


def main(args=None):
    rclpy.init(args=args)
    node = VoiceFrontendNode()
    executor = MultiThreadedExecutor(num_threads=2)
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        executor.shutdown()
        executor.remove_node(node)
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
