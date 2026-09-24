import json
import unittest

from robot_agent.llm_adapter import DecisionKind, decide_model_output


class TestModelOutputDecision(unittest.TestCase):
    def test_empty_function_list_is_chat_only(self):
        decision = decide_model_output('{"res":"你好","fc":[]}')

        self.assertIs(decision.kind, DecisionKind.CHAT_ONLY)
        self.assertEqual(decision.model_response, "你好")
        self.assertIsNone(decision.command)

    def test_exact_allowlisted_function_maps_to_one_canonical_command(self):
        decision = decide_model_output(
            '{"res":"准备开启相机","fc":["start_receiving_image"]}',
            {"start_receiving_image": "start_camera"},
        )

        self.assertIs(decision.kind, DecisionKind.COMMAND)
        self.assertEqual(decision.command, "start_camera")
        self.assertEqual(decision.model_response, "准备开启相机")

    def test_function_is_denied_when_no_allowlist_is_configured(self):
        decision = decide_model_output(
            '{"res":"开始跟踪","fc":["start_tracking"]}'
        )

        self.assertIs(decision.kind, DecisionKind.REJECTED)
        self.assertEqual(decision.reason, "function_not_allowlisted")
        self.assertIsNone(decision.command)

    def test_allowlist_does_not_normalize_case_whitespace_or_parameters(self):
        allowlist = {"start_receiving_image": "start_camera"}
        variants = [
            "Start_receiving_image",
            "start_receiving_image ",
            'start_receiving_image("camera-1")',
        ]

        for function in variants:
            with self.subTest(function=function):
                decision = decide_model_output(
                    '{"res":"动作","fc":['
                    + json.dumps(function, ensure_ascii=False)
                    + "]}",
                    allowlist,
                )
                self.assertIs(decision.kind, DecisionKind.REJECTED)
                self.assertEqual(decision.reason, "function_not_allowlisted")
                self.assertIsNone(decision.command)

    def test_multiple_functions_are_rejected_as_a_whole(self):
        decision = decide_model_output(
            '{"res":"开启相机并执行未知动作",'
            '"fc":["start_receiving_image","navigate_to(餐桌)"]}',
            {"start_receiving_image": "start_camera"},
        )

        self.assertIs(decision.kind, DecisionKind.REJECTED)
        self.assertEqual(decision.reason, "multiple_functions_not_allowed")
        self.assertIsNone(decision.command)

    def test_nonconforming_json_objects_are_rejected(self):
        invalid_payloads = [
            "not json",
            '```json\n{"res":"ok","fc":[]}\n```',
            '{"res":"ok","fc":[]} trailing text',
            '[{"res":"ok","fc":[]}]',
            '{"fc":[]}',
            '{"res":"ok"}',
            '{"res":"ok","fc":[],"extra":true}',
            '{"res":"first","res":"second","fc":[]}',
            '{"res":"ok","fc":[],"fc":[]}',
            '{"res":null,"fc":[]}',
            '{"res":"ok","fc":"start_camera"}',
            '{"res":"ok","fc":[1]}',
        ]

        for raw in invalid_payloads:
            with self.subTest(raw=raw):
                decision = decide_model_output(raw)
                self.assertIs(decision.kind, DecisionKind.REJECTED)
                self.assertIsNone(decision.command)

    def test_payload_larger_than_byte_limit_is_rejected(self):
        decision = decide_model_output(
            '{"res":"你好","fc":[]}', max_bytes=10
        )

        self.assertIs(decision.kind, DecisionKind.REJECTED)
        self.assertEqual(decision.reason, "input_too_large")

    def test_allowlist_cannot_target_arbitrary_ros_commands(self):
        decision = decide_model_output(
            '{"res":"执行","fc":["start_receiving_image"]}',
            {"start_receiving_image": "/cmd_vel"},
        )

        self.assertIs(decision.kind, DecisionKind.REJECTED)
        self.assertEqual(decision.reason, "invalid_allowlist")
        self.assertIsNone(decision.command)

    def test_fixed_virtual_head_function_maps_to_same_named_simulation_command(self):
        decision = decide_model_output(
            '{"res":"我点点头","fc":["head_nod"]}',
            {"head_nod": "head_nod"},
        )

        self.assertIs(decision.kind, DecisionKind.COMMAND)
        self.assertEqual(decision.command, "head_nod")

    def test_virtual_head_function_does_not_accept_model_supplied_parameters(self):
        decision = decide_model_output(
            '{"res":"点头","fc":["head_nod(20)"]}',
            {"head_nod": "head_nod"},
        )

        self.assertIs(decision.kind, DecisionKind.REJECTED)
        self.assertEqual(decision.reason, "function_not_allowlisted")
        self.assertIsNone(decision.command)


if __name__ == "__main__":
    unittest.main()
