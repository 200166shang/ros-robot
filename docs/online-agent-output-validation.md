# 语音回合输出集中验证（#78）

## 实现

`voice/output.py` 的 `VoiceOutput` 集中拥有 TTS 重试、连续失败计数、
降级与显式恢复、可选播放、音频路径、原文本恢复及原子记录保存。
普通回合和显式核对均一次提交结果，由输出 implementation 决定输出资格
并关联产物。识别失败与空输入仅记录；核对保留原有独立资格规则。

`OnlineVoice` 保留公开 interface、参数校验、唤醒/休眠、音乐过滤、
静音期限、回合归属和 ASR input pause。关闭先取消输出重试与播放，
再关闭输入，并通过 finally 保证合成 Adapter 的关闭仍被调用。
`SpeechOutput` 仍可从原 session 导入，底层 SpeechConnection 未改动。

## 行为与检查

环境：Orange Pi，系统 Python 3.8 / ROS 2 Foxy；使用源码外现有
`issue-68-test-deps` 和 `issue-67-venv` 依赖，ROS_DOMAIN_ID=194。
所有音频和记录均在临时目录，采集、播放及云端传输使用固定 Adapter。

- 重构后原语音行为测试：14 passed。
- 补充原子替换失败、核对余项不执行、旧快照不变及记录关联断言后，
  语音行为、语音组装和模拟麦克风 ROS 组装：17 passed（3.41 秒）。
- 完整 Python 回归：120 passed（13.92 秒）。命令：

  ```bash
  python3 -m pytest -q tests ros2_ws/src/robot_audio/tests \
    ros2_ws/src/robot_agent/test ros2_ws/src/robot_voice/test \
    ros2_ws/src/robot_bringup/test
  ```

- Pyright 检查 `voice/session.py`、`voice/output.py`，Python 3.8，
  使用源码外完整 typeshed：0 errors、0 warnings。
- 根配置 `ruff format --check .`：58 files already formatted；
  `ruff check .`：All checks passed；`git diff --check` 通过。
- code-review 对起点 ffcbc45 的两轴独立审查：Standards 0 项，Spec 0 项。

## 环境限制

首次组装测试收集因未加载外部 websocket-client 而失败；加入现有
源码外 venv 依赖路径后通过。扩展核对测试最初仍以整轮 completed
为等待条件，但有未执行余项时既有契约返回 failed；修正为等待具体动作
确认，再断言余项仍未执行。产品状态语义未调整。

本轮未执行真实云端、真实麦克风/扬声器、硬件动作或 C++ 构建验收；
本次更改限于 Python 语音输出 implementation，dry-run 设置保持。
