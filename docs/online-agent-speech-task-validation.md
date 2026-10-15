# #80 持续 ASR 任务传输迁移验收

2026-10-15，基于最新 `origin/main` 的 `5ee4ad4`，独立 worktree
`/home/orangepi/code/ros-robot-issue-80`，分支 `codex/issue-80-live-asr`。

## 改动与行为

`LiveSpeechInput` 直接调用 `SpeechTask.receive()`，音频发送、事件接收、
连接关闭及 WebSocket 异常转换均沿用任务传输 implementation。删除
`SpeechConnection.receive()` 过渡转发方法及持续输入的 WebSocket 导入、
异常类型依赖。生产语音目录中只有 `_speech_task.py` 知道原始连接。

持续输入仍拥有暂停、恢复清理、音频时间戳、单个最终句交接与连续失败
预算。有效最终句重置预算，断线仅发送新采集帧；WAV 整轮重试与暂停保留
录音、TTS 不重试的语义保持。动作未知状态、显式核对、记忆、感知与硬件
安全模式均未改动。

## 执行结果

复用源码外 Python 3.8 环境 `/tmp/ros-robot-79-env` 和 Foxy。
系统 Python 缺少 websocket；Foxy 的旧版 launch_testing 插件与 pytest
8 不兼容，因此显式关闭插件自动加载。ROS 测试仍导入真实 rclpy 并执行。

从 worktree 根目录运行完整 Python 回归：

```bash
source /opt/ros/foxy/setup.bash
export PYTHONPATH="$PWD/ros2_ws/src/robot_agent:$PWD/ros2_ws/src/robot_audio:$PWD/ros2_ws/src/robot_voice:$PYTHONPATH"
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
/tmp/ros-robot-79-env/bin/python -m pytest -q \
  tests ros2_ws/src/robot_agent/test ros2_ws/src/robot_audio/tests \
  ros2_ws/src/robot_voice/test ros2_ws/src/robot_bringup/test
```

结果：**144 passed，15.98 秒**；4 项警告来自 Foxy 的弃用接口。
未运行与本次 Python 迁移无关的 C++ 构建和测试。

- 持续输入共 16 项：最终句/心跳过滤、暂停真实采集与静音、恢复清理、
  迟到句、重连预算恢复、PCM 故障、空闲退出、迟到连接、清理异常；
  新增发送/接收的网络与编程异常、在途发送/接收/PCM 取消、无数据超时、
  通过可区分 PCM 帧证明重连不重放。
- `test_online_microphone_ros.py` 通过正常 `OnlineVoiceRosNode` 入口，
  使用录音/播放子进程与固定 HTTP/WSS adapter，验证唤醒、请求、模拟
  点头、可信回复、TTS/播放静音保活、恢复、休眠、结果话题及退出。
  三轮只有一个 ASR 任务，正常入口仍没有文本/WAV 订阅。
- 语音协议、交互、组装、WAV 暂停/重试、未知动作、显式核对、记忆与
  感知回归包含在上述完整测试中。没有驱动实体运动或调用真实云服务。
- 两个改动生产文件经 mypy 检查：`Success: no issues found in 2 source files`。
  参数为 `--follow-imports=silent --ignore-missing-imports`，不声称第三方
  依赖或全仓库均已通过类型检查。
- 三个改动 Python 文件经 Ruff format、format --check、check 全部通过；
  `git diff --check` 通过。
- 额外执行全仓库 `ruff check .`，发现基线已存在的
  `test_online_perception_ros.py:10` 导入顺序 I001；本票未改动该文件。

## 双轴审查

固定比较点 `5ee4ad4c28e0fc6140d1036eee842790dfbcc4a2`；两名独立审查
agent 分别检查 Standards 与 Spec。Standards 0 项，Spec 0 项；最终回归
与检查结果已记录于本报告。
