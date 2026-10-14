# Device audio tools

`robot_audio` owns microphone capture, WAV-file input, and WAV playback. It
contains no ROS node, topics, model runtime, ASR, or TTS. Importing it does not
start another process; recording and playback invoke configurable ALSA tools.

Both the online `robot_agent` and the existing offline `robot_voice` depend on
this package. Neither depends on the other for device audio.

```python
from robot_audio.audio_sources import create_audio_source
from robot_audio.audio_io import play_wav

source = create_audio_source(
    "microphone", record_device="plughw:2,0", record_seconds=8
)
source.capture("/absolute/external/input.wav")
play_wav("aplay", "default", "/absolute/external/reply.wav")
```

`create_audio_source("wav_file", input_wav_path=...)` validates and copies an
existing WAV instead of recording. Inputs must be non-empty, mono, PCM16 WAV
at 16kHz. Capture returns format metadata; playback returns the duration.

Capture and playback accept a `cancelled` callback. They terminate and reap
their owned subprocess on cancellation or timeout and report I/O failures.
Playback process success does not prove audible output. Install `alsa-utils`
for the default `arecord` and `aplay` commands. Tests supply external commands
and temporary WAV files; no hardware or model is needed.
