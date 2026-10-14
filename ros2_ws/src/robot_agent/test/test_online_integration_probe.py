"""通过公开CLI验证证据保存失败仍保留验收失败并释放ROS。"""

import json
import sys

import online_integration_probe
import pytest
import rclpy


def test_reporting_failure_preserves_acceptance_error_and_closes_ros(
    tmp_path, monkeypatch
) -> None:
    """输出目录不可写时，原验收失败仍显露且默认ROS上下文关闭。"""
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "output_dir": str(tmp_path / "results"),
                "memory_file": str(tmp_path / "memory.json"),
            }
        ),
        encoding="utf-8",
    )
    target = tmp_path / "occupied"
    target.write_text("这是文件，不能作为证据目录", encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "online_integration_probe",
            "--config",
            str(config),
            "--wav",
            str(tmp_path / "input.wav"),
            "--evidence-dir",
            str(target),
        ],
    )
    now = 0.0

    def expired_clock() -> float:
        """外部时钟直接越过期限，使真实ROS无服务场景立即失败。"""
        nonlocal now
        now += 20
        return now

    monkeypatch.setattr(
        online_integration_probe.time, "monotonic", expired_clock
    )
    try:
        with pytest.raises(AssertionError, match="安全参数服务未发现"):
            online_integration_probe.main()
        assert not rclpy.ok()
    finally:
        if rclpy.ok():
            rclpy.shutdown()
