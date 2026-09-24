import tempfile
import unittest
import wave
from pathlib import Path

from robot_voice.audio_sources import create_audio_source


class TestWavFileAudioSource(unittest.TestCase):
    def test_file_mode_replays_fixture_without_modifying_it(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = root / "fixture.wav"
            destination = root / "working-copy.wav"
            frames = b"\x01\x00\x02\x00" * 6
            with wave.open(str(fixture), "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(16000)
                audio.writeframes(frames)
            original_bytes = fixture.read_bytes()

            source = create_audio_source(
                "wav_file", input_wav_path=str(fixture)
            )
            metadata = source.capture(str(destination))

            self.assertEqual(destination.read_bytes(), original_bytes)
            self.assertEqual(fixture.read_bytes(), original_bytes)
            self.assertEqual(
                metadata,
                {
                    "frames": 12,
                    "channels": 1,
                    "sample_rate": 16000,
                    "sample_width": 2,
                },
            )

    def test_file_mode_rejects_audio_outside_asr_format(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = root / "wrong-rate.wav"
            destination = root / "working-copy.wav"
            with wave.open(str(fixture), "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(8000)
                audio.writeframes(b"\x00\x00" * 8)

            source = create_audio_source(
                "wav_file", input_wav_path=str(fixture)
            )
            with self.assertRaises(ValueError):
                source.capture(str(destination))
            self.assertFalse(destination.exists())

    def test_unknown_audio_source_is_rejected(self):
        with self.assertRaises(ValueError):
            create_audio_source("network_stream")


if __name__ == "__main__":
    unittest.main()
