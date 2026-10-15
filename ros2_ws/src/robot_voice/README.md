# robot_voice

This package is a one-shot, half-duplex audio front end for the Online Agent text Interface. It does not import the ASR/TTS runtime into the ROS Python process: replaceable adapters call the installed sherpa-onnx CLI, while the shared `robot_audio` package owns ALSA capture and playback.

```text
Trigger /voice/capture
  -> arecord (C270, 16 kHz mono PCM16)
  -> sherpa-onnx ASR
  -> std_msgs/String /online_agent/text
  <- std_msgs/String /online_agent/result
  -> sherpa-onnx TTS WAV
  -> aplay on RK809
```

The voice package publishes text to `/online_agent/text` and reads the JSON
`reply` field from `/online_agent/result` for local TTS. Local ASR/TTS remain
available; the retired local LLM bridge is no longer required. Use a dedicated
Online Agent instance for voice turns: the text input does not carry a client
request ID, so sharing its reply stream with unrelated clients is unsupported.
Start Online Agent with external credentials/configuration before capture.
This adapter is local speech input/output, not the full online voice workflow
planned in #67. It never publishes device commands or motion topics.

`audio_source` is an injectable ROS parameter. It defaults to `microphone` and preserves the C270/ALSA behavior above. For a deterministic local regression test, set `audio_source:=wav_file` and point `input_wav_path` to a local mono 16 kHz PCM16 WAV file. The adapter validates and copies the fixture into the per-turn temporary directory without changing the source. Test recordings and generated fixtures belong under `/home/orangepi/local-data/ros-robot/voice-fixtures/`; that directory is outside the Git repository and must not be uploaded.

```bash
VOICE_FIXTURE=/home/orangepi/local-data/ros-robot/voice-fixtures/your-test.wav
./scripts/dev.sh ros run robot_voice voice_frontend --ros-args \
  -p audio_source:=wav_file \
  -p input_wav_path:="$VOICE_FIXTURE" \
  -p play_audio:=false
```

Then call `/voice/capture` as usual. `play_audio:=false` still synthesizes the TTS WAV but skips `aplay`, which is useful for software-only end-to-end tests when no speaker/headphones are connected. Choose a fixture whose expected behavior is understood; movement requests must remain rejected and must never be treated as permission to actuate hardware.

The tracking/web demo no longer auto-starts local speech fixtures or the
retired voice-to-local-model acceptance probe. Run this frontend explicitly
when local speech input/output is needed.

On the Orange Pi, synchronize and build the [project environment](../../../docs/development-environment.md), then run `./scripts/dev.sh ros run robot_voice voice_frontend`. The default sherpa executables come from the same interpreter's `bin` directory; external model paths remain configurable. Call `ros2 service call /voice/capture std_srvs/srv/Trigger {}` and speak immediately; the default recording window is 8 seconds. During the current prototype, connect wired headphones to the board's headphone jack or use an amplified speaker to hear TTS. Without an external transducer `aplay` can succeed while the room remains silent.
