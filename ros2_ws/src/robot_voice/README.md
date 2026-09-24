# robot_voice

This package is a one-shot, half-duplex audio front end for the existing ROS text bridge. It does not import the ASR/TTS runtime into the ROS Python process: replaceable adapters call the installed sherpa-onnx CLI, while `audio_io.py` owns ALSA capture and playback.

```text
Trigger /voice/capture
  -> arecord (C270, 16 kHz mono PCM16)
  -> sherpa-onnx ASR
  -> std_msgs/String /llm/user_input
  <- std_msgs/String /llm/response
  -> sherpa-onnx TTS WAV
  -> aplay on RK809
```

The voice package only publishes `/llm/user_input`; it has no `/agent/command` or motion-topic publisher. The existing Qwen bridge remains responsible for its current response parsing and safety policy. Keep only one `/llm/user_input` request in flight during a voice turn because the agreed `std_msgs/String` response has no request ID.

`audio_source` is an injectable ROS parameter. It defaults to `microphone` and preserves the C270/ALSA behavior above. For a deterministic local regression test, set `audio_source:=wav_file` and point `input_wav_path` to a local mono 16 kHz PCM16 WAV file. The adapter validates and copies the fixture into the per-turn temporary directory without changing the source. Test recordings and generated fixtures belong under `/home/orangepi/local-data/ros-robot/voice-fixtures/`; that directory is outside the Git repository and must not be uploaded.

```bash
VOICE_FIXTURE=/home/orangepi/local-data/ros-robot/voice-fixtures/your-test.wav
ros2 run robot_voice voice_frontend --ros-args \
  -p audio_source:=wav_file \
  -p input_wav_path:="$VOICE_FIXTURE" \
  -p play_audio:=false
```

Then call `/voice/capture` as usual. `play_audio:=false` still synthesizes the TTS WAV but skips `aplay`, which is useful for software-only end-to-end tests when no speaker/headphones are connected. Choose a fixture whose expected behavior is understood; movement requests must remain rejected and must never be treated as permission to actuate hardware.

The `person_tracking_demo.launch.py` launch file defaults to a locally supplied synthetic fixture at `/home/orangepi/local-data/ros-robot/voice-fixtures/start_person_tracking_zh_2026-09-24.wav`. It is intentionally not packaged or tracked. If that file is absent, supply another approved local WAV with `input_wav_path:=...`; microphone mode remains separately selectable with `audio_source:=microphone`.

On the Orange Pi, source ROS Foxy and the workspace, then run `ros2 run robot_voice voice_frontend`. Call `ros2 service call /voice/capture std_srvs/srv/Trigger {}` and speak immediately; the default recording window is 8 seconds. During the current prototype, connect wired headphones to the board's headphone jack or use an amplified speaker to hear TTS. Without an external transducer `aplay` can succeed while the room remains silent.
