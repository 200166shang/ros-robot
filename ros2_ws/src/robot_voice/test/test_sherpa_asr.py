import unittest

from robot_voice.sherpa_asr import extract_transcript


class TestSherpaTranscriptParsing(unittest.TestCase):
    def test_uses_last_non_empty_json_transcript(self):
        output = (
            'Recognizer created\n'
            '{"text":"","tokens":[]}\n'
            '你好机器人请报告当前状态\n'
            '{"text":"你好机器人请报告当前状态","tokens":["你","好"]}\n'
        )
        self.assertEqual(extract_transcript(output), "你好机器人请报告当前状态")

    def test_ignores_json_without_text_and_malformed_json(self):
        output = 'not json {bad}\n{"tokens":[]}\n'
        self.assertEqual(extract_transcript(output), "")

    def test_strips_transcript_whitespace(self):
        output = '{"text":"  你好  ","tokens":[]}\n'
        self.assertEqual(extract_transcript(output), "你好")


if __name__ == "__main__":
    unittest.main()
