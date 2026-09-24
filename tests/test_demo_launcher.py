"""Focused safety and configuration tests for the board-side demo launcher."""

from dataclasses import replace
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import demo_launcher


def make_config(**updates):
    """Build a valid config without depending on Orange Pi-only assets."""
    config = demo_launcher.load_config(
        project_root=Path("/tmp/ros-robot-test"),
        environment={},
    )
    return replace(config, **updates)


class EntryPointTests(unittest.TestCase):
    def test_posix_sh_invocation_explains_that_bash_is_required(self):
        script = Path(__file__).resolve().parents[1] / "scripts" / "run-demo.sh"
        shell_probe = subprocess.run(
            ["sh", "-c", "set -o pipefail"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if shell_probe.returncode == 0:
            self.skipTest("the system sh already supports Bash pipefail")

        result = subprocess.run(
            ["sh", str(script), "--help"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            check=False,
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("此入口需要 Bash", result.stderr)
        self.assertIn("不要用 sh", result.stderr)


class ConfigTests(unittest.TestCase):
    def test_default_config_matches_documented_demo_settings(self):
        config = make_config()

        self.assertEqual(config.llama_port, 18080)
        self.assertEqual(config.web_port, 8080)
        self.assertEqual(config.ros_domain_id, 74)
        self.assertEqual(config.audio_source, "wav_file")
        self.assertFalse(config.run_acceptance_probe)
        self.assertEqual(config.llama_model_alias, "qwen3-robot")

    def test_acceptance_flag_selects_deterministic_wav_replay_profile(self):
        config = make_config(audio_source="microphone")
        with mock.patch.object(
            demo_launcher, "load_config", return_value=config
        ), mock.patch.object(
            demo_launcher, "_run", return_value=0
        ) as run_demo:
            result = demo_launcher.main(["--acceptance"])

        self.assertEqual(result, 0)
        effective_config = run_demo.call_args.args[0]
        self.assertTrue(effective_config.run_acceptance_probe)
        self.assertEqual(effective_config.audio_source, "wav_file")

    def test_invalid_ports_and_duplicate_ports_are_rejected(self):
        cases = (
            ({"DEMO_LLAMA_PORT": "abc"}, "必须是数字"),
            ({"DEMO_WEB_PORT": "65536"}, "1–65535"),
            (
                {"DEMO_LLAMA_PORT": "8080", "DEMO_WEB_PORT": "8080"},
                "不能相同",
            ),
        )
        for environment, message in cases:
            with self.subTest(environment=environment):
                with self.assertRaisesRegex(demo_launcher.DemoError, message):
                    demo_launcher.load_config(
                        project_root=Path("/tmp/ros-robot-test"),
                        environment=environment,
                    )

    def test_invalid_audio_probe_and_domain_values_are_rejected(self):
        cases = (
            ({"DEMO_AUDIO_SOURCE": "unknown"}, "音频来源"),
            ({"DEMO_RUN_ACCEPTANCE_PROBE": "yes"}, "验收探针"),
            (
                {
                    "DEMO_RUN_ACCEPTANCE_PROBE": "true",
                    "DEMO_AUDIO_SOURCE": "microphone",
                },
                "固定样本验收探针必须使用 wav_file",
            ),
            ({"ROS_DOMAIN_ID": "7x"}, "ROS_DOMAIN_ID"),
        )
        for environment, message in cases:
            with self.subTest(environment=environment):
                with self.assertRaisesRegex(demo_launcher.DemoError, message):
                    demo_launcher.load_config(
                        project_root=Path("/tmp/ros-robot-test"),
                        environment=environment,
                    )


class ModelAndPreflightTests(unittest.TestCase):
    def _model_response(self, model_id):
        payload = {"data": [{"id": model_id}]}
        return io.BytesIO(json.dumps(payload).encode("utf-8"))

    def test_model_identity_accepts_alias_or_exact_model_path(self):
        config = make_config()
        for model_id in (
            config.llama_model_alias,
            str(config.llama_model),
        ):
            with self.subTest(model_id=model_id):
                with mock.patch.object(
                    demo_launcher,
                    "_urlopen_without_proxy",
                    return_value=self._model_response(model_id),
                ):
                    self.assertTrue(demo_launcher.llama_model_matches(config))

    def test_model_identity_rejects_wrong_or_malformed_response(self):
        config = make_config()
        responses = (
            self._model_response("unrelated-model"),
            io.BytesIO(b"{not-json"),
            io.BytesIO(b'{"wrong":"shape"}'),
        )
        for response in responses:
            with self.subTest(response=response.getvalue()):
                with mock.patch.object(
                    demo_launcher,
                    "_urlopen_without_proxy",
                    return_value=response,
                ):
                    self.assertFalse(
                        demo_launcher.llama_model_matches(config)
                    )

    def test_healthy_expected_qwen_is_reused(self):
        config = make_config()
        with mock.patch.object(
            demo_launcher, "port_is_in_use", side_effect=[False, True]
        ), mock.patch.object(
            demo_launcher, "http_is_healthy", return_value=True
        ), mock.patch.object(
            demo_launcher, "llama_model_matches", return_value=True
        ):
            self.assertTrue(
                demo_launcher.check_ports_and_model(config)
            )

    def test_wrong_qwen_model_is_never_reused_or_stopped(self):
        config = make_config()
        with mock.patch.object(
            demo_launcher, "port_is_in_use", side_effect=[False, True]
        ), mock.patch.object(
            demo_launcher, "http_is_healthy", return_value=True
        ), mock.patch.object(
            demo_launcher, "llama_model_matches", return_value=False
        ):
            with self.assertRaisesRegex(
                demo_launcher.DemoError, "无法确认为"
            ):
                demo_launcher.check_ports_and_model(config)

    def test_web_port_conflict_stops_preflight_before_qwen_checks(self):
        config = make_config()
        with mock.patch.object(
            demo_launcher, "port_is_in_use", return_value=True
        ) as port_check, mock.patch.object(
            demo_launcher, "http_is_healthy"
        ) as health_check:
            with self.assertRaisesRegex(
                demo_launcher.DemoError, "网页端口"
            ):
                demo_launcher.check_ports_and_model(config)
        port_check.assert_called_once_with(config.web_port)
        health_check.assert_not_called()


class ProcessOwnershipTests(unittest.TestCase):
    def test_qwen_starts_on_loopback_and_is_registered_as_owned(self):
        controller = demo_launcher.ShutdownController()
        process = mock.Mock()
        process.pid = 12345
        process.poll.return_value = None

        with tempfile.TemporaryDirectory() as temp_dir:
            config = make_config(log_dir=Path(temp_dir))
            with mock.patch.object(
                demo_launcher.subprocess, "Popen", return_value=process
            ) as popen, mock.patch.object(
                demo_launcher, "http_is_healthy", return_value=True
            ), mock.patch.object(
                demo_launcher, "llama_model_matches", return_value=True
            ):
                started = demo_launcher.start_qwen(config, controller)

        command = popen.call_args.args[0]
        self.assertIs(started, process)
        self.assertIs(controller.qwen_process, process)
        self.assertEqual(command[command.index("--host") + 1], "127.0.0.1")
        self.assertEqual(command[command.index("--alias") + 1], "qwen3-robot")
        self.assertTrue(popen.call_args.kwargs["start_new_session"])

    def test_ros_launch_receives_demo_settings_and_runs_in_own_session(self):
        config = make_config(
            audio_source="microphone",
            run_acceptance_probe=False,
            ros_domain_id=21,
        )
        controller = demo_launcher.ShutdownController()
        process = mock.Mock()
        process.wait.return_value = 0

        with mock.patch.dict(os.environ, {"ROS_DOMAIN_ID": "74"}):
            with mock.patch.object(
                demo_launcher.subprocess, "Popen", return_value=process
            ) as popen, mock.patch.object(
                demo_launcher, "print_access_instructions"
            ), mock.patch.object(
                demo_launcher, "stop_owned_process"
            ):
                result = demo_launcher.launch_ros(config, controller)
                self.assertEqual(os.environ["ROS_DOMAIN_ID"], "21")

        command = popen.call_args.args[0]
        self.assertEqual(result, 0)
        self.assertEqual(command[:4], [
            "ros2",
            "launch",
            "robot_bringup",
            "person_tracking_demo.launch.py",
        ])
        self.assertIn("audio_source:=microphone", command)
        self.assertIn("run_acceptance_probe:=false", command)
        self.assertTrue(popen.call_args.kwargs["start_new_session"])

    def test_signal_is_forwarded_only_to_active_ros_launcher(self):
        controller = demo_launcher.ShutdownController()
        ros_process = mock.Mock()
        ros_process.poll.return_value = None
        controller.ros_process = ros_process

        controller.handle_signal(signal.SIGTERM, None)

        self.assertEqual(controller.requested_signal, signal.SIGTERM)
        ros_process.send_signal.assert_called_once_with(signal.SIGINT)

    def test_failed_start_still_cleans_the_qwen_process_it_owns(self):
        config = make_config()
        child = mock.Mock()

        def fail_after_start(_config, controller):
            controller.qwen_process = child
            raise demo_launcher.DemoError("injected startup failure")

        with self.assertLogs(demo_launcher.LOGGER, level="ERROR"):
            with mock.patch.object(
                demo_launcher, "preflight", return_value=False
            ), mock.patch.object(
                demo_launcher, "start_qwen", side_effect=fail_after_start
            ), mock.patch.object(
                demo_launcher, "stop_owned_process"
            ) as stop:
                result = demo_launcher._run(config, check_only=False)

        self.assertEqual(result, 1)
        stop.assert_called_once_with(child, "Qwen llama-server")

    def test_check_only_never_starts_services(self):
        config = make_config()
        with mock.patch.object(
            demo_launcher, "preflight", return_value=False
        ), mock.patch.object(
            demo_launcher, "start_qwen"
        ) as start_qwen, mock.patch.object(
            demo_launcher, "launch_ros"
        ) as launch_ros, mock.patch.object(
            demo_launcher, "stop_owned_process"
        ):
            result = demo_launcher._run(config, check_only=True)

        self.assertEqual(result, 0)
        start_qwen.assert_not_called()
        launch_ros.assert_not_called()

    @unittest.skipUnless(hasattr(os, "killpg"), "POSIX only")
    def test_cleanup_stops_only_the_process_group_it_owns(self):
        owned = subprocess.Popen(
            [
                sys.executable,
                "-c",
                (
                    "import signal, sys, time; "
                    "signal.signal(signal.SIGINT, lambda *_: sys.exit(0)); "
                    "time.sleep(30)"
                ),
            ],
            start_new_session=True,
        )
        unrelated = subprocess.Popen(
            [
                sys.executable,
                "-c",
                (
                    "import signal, time; "
                    "signal.signal(signal.SIGINT, signal.SIG_IGN); "
                    "time.sleep(30)"
                ),
            ],
            start_new_session=True,
        )
        try:
            time.sleep(0.15)
            demo_launcher.stop_owned_process(
                owned,
                "测试子进程",
                graceful_timeout=2,
                terminate_timeout=1,
            )
            self.assertIsNotNone(owned.poll())
            self.assertIsNone(unrelated.poll())
        finally:
            if unrelated.poll() is None:
                unrelated.terminate()
                unrelated.wait(timeout=3)


if __name__ == "__main__":
    unittest.main()
