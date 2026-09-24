# ROS 演示启动器重构方案调研

日期：2026-09-25

## 结论摘要

建议把板端复杂编排迁移到 Python 3.8 标准库程序中，Shell 入口只负责加载
ROS 环境并交接。Mac 端隧道脚本独立于板端，先保留原状；待板端重构稳定后，
再单独评估是否值得迁移。不要把两台机器的逻辑塞进一个跨机器的大 Python
程序，也暂不引入第三方 Python 依赖。

建议结构：

```text
scripts/
  run-demo.sh       # Orange Pi：加载 ROS 环境后 exec Python
  demo_launcher.py  # Orange Pi：检查、Qwen/ROS 生命周期管理
  open-ui.sh        # Mac：维持现有 SSH 隧道工具
```

这不是“为了生产级而改成 Python”。依据是当前脚本已经承担了复杂控制流：
板端 `run-demo.sh` 约 430 行，Mac 端 `open-ui.sh` 约 202 行。Google Shell
Style Guide 将 Shell 定位为小型工具和简单包装脚本，并建议超过约 100 行或
控制流不简单时考虑结构化语言；这是启发式判断，不是强制行数上限。

因此，板端 430 行脚本是本次迁移重点。Mac 端 202 行脚本也超过该启发线，
但它是独立的本地开发辅助工具；不应为了“两个入口形式统一”而扩大本次变更。
可以在板端方案通过验收后，再对 Mac 脚本作单独决策。

## 项目事实

- Orange Pi 当前运行 ROS 2 Foxy。
- Orange Pi 上的 `python3 --version` 为 Python 3.8.10。
- 板端脚本负责配置验证、文件/端口检查、Qwen 健康和模型身份检查、启动
  llama-server、等待健康、前台启动 ROS launch，并在退出时清理自启动的
  Qwen 进程。
- Mac 脚本负责 SSH 连接检查、端口占用检测、启动/等待 SSH 隧道、健康检查、
  可选打开浏览器，并在 Ctrl-C 时清理隧道。
- 两端职责不同，分别运行在 Orange Pi 和 Mac；不应让单个脚本从一台机器远程
  启停所有服务。

## 为什么采用 Shell 入口 + Python 编排

### ROS 环境仍由 Bash 加载

ROS 的 `setup.bash` 会设置当前 shell 的环境。Bash 的 `source`（即点命令）
是在当前 shell 环境中执行文件；随后执行的子进程继承已导出的环境变量。
因此最稳妥的边界是：Bash 入口先加载 Foxy 和工作区环境，再用 `exec` 替换
自身为 Python 程序。这样 ROS 环境进入 Python，Ctrl-C 和退出状态也交给真正的
编排进程处理。[Bash source/current-shell 语义](https://www.gnu.org/software/bash/manual/html_node/Bourne-Shell-Builtins.html)

### Python 更适合当前的复杂部分

- 配置和命令行：使用 `argparse` 管理 `--check-only`，自动拒绝未知参数并生成
  帮助文本。
- 路径、端口和配置校验：用小函数逐项验证，类型和值域清晰。
- Qwen 模型身份：使用标准库 `json` 解析 `/v1/models`，不再内嵌一段
  `python -c` 在 Shell 里解析 JSON。
- 进程生命周期：用 `subprocess.Popen` 持有自己启动进程的对象，只清理这些
  对象对应的进程；为需要整组信号管理的服务使用 POSIX
  `start_new_session=True`，并按有界超时等待退出。
- 日志：用标准库 `logging` 输出阶段、时间、级别和错误，也可把 Qwen 的原始
  stdout/stderr 保留在本地日志文件。
- 隧道：Python 端仍使用本机的 `ssh` 命令，不重写 SSH 协议；通过列表形式传
  参数，不拼接 shell 命令字符串。

Python 标准库文档说明，`start_new_session` 在 POSIX 上创建独立会话；
同时明确不建议用线程环境下不安全的 `preexec_fn` 来调用 `setsid`。
这个接口在 Python 3.2 已提供，因此与板端 Python 3.8 兼容。
[Python 3.8 subprocess 文档](https://docs.python.org/3.8/library/subprocess.html)

## 建议的文件职责

### `run-demo.sh`：板端薄入口

只做以下事情：

1. 开启必要的 Bash 严格模式。
2. 根据脚本路径定位仓库和 ROS 工作区。
3. source Foxy 和工作区 setup 文件；对 Foxy 需要的 nounset 兼容范围作局部处理。
4. 检查 Python 解释器存在，然后 `exec python3 scripts/demo_runner.py "$@"`。

不要在这里保留端口检查、HTTP/JSON 解析、启动等待循环或进程清理。

### `demo_launcher.py`：板端编排器

用单文件和普通函数起步，不先搭复杂 package/class 框架：

- `parse_args()`
- `load_config()` / `validate_config()`
- `check_dependencies()`
- `check_assets()`
- `check_ports_and_model()`
- `start_qwen()`
- `run_ros_launch()`
- `stop_owned_process()`
- `main()`

主流程应能按顺序读成：

```text
解析参数 → 读取/校验配置 → 预检查 → 可选只检查退出
→ 启动或安全复用 Qwen → 前台运行 ROS → finally 清理自启动的 Qwen
```

### `open-ui.sh`：Mac 隧道工具（本次不改）

保持现有行为和入口。后续若独立迁移，再将 SSH 隧道、健康检查和清理逻辑放到
Mac 专属的 `open_ui.py`，仍由薄 Bash 入口启动；它不连接 ROS 环境，也不启动/
停止板端 Qwen 或 ROS。是否迁移取决于当前 Bash 脚本的实际控制流与维护成本，
而不是为了跨机器共享代码。

## Python 规范（兼容 Python 3.8）

以 Google Python Style Guide 和 PEP 8 为基线，并遵守项目特定约束：

1. 只用 Python 3.8 支持的语法；类型标注使用 `typing.Optional` /
   `typing.List` 等，不用 `str | None`、`list[str]` 等较新语法。
2. 四空格缩进；函数、变量用 `snake_case`，类用 `CapWords`，常量用
   `UPPER_SNAKE_CASE`；行长目标 79 字符。
3. 模块和非显然/复杂函数写简洁 docstring；注释解释原因和安全边界，不逐行
   翻译代码。
4. 标准库优先：`argparse`、`dataclasses`、`json`、`logging`、
   `pathlib`、`signal`、`subprocess`、`typing`、`urllib`。
5. 子进程参数传列表，不用 `shell=True`；HTTP 调用设置超时；失败返回明确
   非零状态。
6. 用 `Popen` 对象跟踪所有权；不通过 `pkill` 或进程名清理。清理放在
   `try/finally`，处理 Ctrl-C/SIGTERM，并先优雅停止、有限等待，再升级信号。
7. 一个函数只负责一个阶段；公共函数标注输入/返回类型；不为了“面向对象”
   而创建只有一两个字段且无行为的类。
8. 只用标准库，不引入 requests、psutil 等安装依赖；命令入口留在 `main()`，
   并用 `if __name__ == "__main__":` 保护导入行为。
9. 测试只覆盖关键边界：参数/配置拒绝、模型 ID 匹配/不匹配、启动失败时清理
  自己启动的进程、复用服务时不误杀。使用 Python 3.8 自带 `unittest` 即可。

参考：[Google Python Style Guide](https://google.github.io/styleguide/pyguide.html)、
[PEP 8](https://peps.python.org/pep-0008/)、
[Python 3.8 argparse](https://docs.python.org/3.8/library/argparse.html)、
[Python 3.8 logging](https://docs.python.org/3.8/library/logging.html)。

## 现在不建议做的事

- 不把 ROS 节点或人物跟踪业务逻辑搬进启动器；启动器只管理服务生命周期。
- 板端先保持一个 `demo_launcher.py`；Mac 隧道职责独立，不为形式统一而共用代码。
- 不引入第三方包管理或虚拟环境；当前功能可由板端已有 Python 3.8 标准库完成。
- 不在这一步切换到 systemd。当前目标是可见的前台原型启动和 Ctrl-C 退出；
  后续若要开机启动、崩溃自动拉起和系统级日志，再单独设计 Qwen 与 ROS 的
  service unit，避免一个包装服务暗中管理多个主进程。

## 实施状态与验证记录

已按方案完成板端启动器重构：

- `scripts/run-demo.sh` 仅加载 Foxy/工作区环境，再执行 Python 编排器。
- `scripts/demo_launcher.py` 使用板端 Python 3.8.10 标准库管理预检查、Qwen
  服务、ROS launch 和本次启动进程的退出清理。
- `scripts/open-ui.sh` 保持不变：它在 Mac 建立 SSH 本地端口转发；板端入口
  只打印连接提示，不会创建 Mac 上的隧道。
- 新增 `tests/test_demo_launcher.py`，覆盖配置边界、模型身份、Qwen 复用、
  ROS 参数传递、启动异常清理、信号转发和进程所有权。

已在 Orange Pi 上完成以下验证：

- `python3 -m unittest discover -s tests -v`：15 项通过。
- `bash -n scripts/run-demo.sh` 与 Python 3.8 的 `py_compile`：通过。
- 用 `sh scripts/run-demo.sh --help`：清楚提示必须用 Bash，并以状态码 2 退出。
- `./scripts/run-demo.sh --check-only`：配置、模型文件、摄像头、ROS 环境与端口
  检查全部通过；检查过程没有启动 Qwen、ROS 节点或摄像头采集。

完整常驻演示未由本次验证自动启动，避免在用户未观察时拉起 Qwen/ROS 与摄像头；
正常启动方式仍为板端 `./scripts/run-demo.sh`。如需浏览器画面，再从 Mac 运行
`./scripts/open-ui.sh`。后续若要自动开机启动或崩溃拉起，再单独设计 systemd
服务；本次不提交、不修改 Mac 隧道实现。

## Sources

- [Google Shell Style Guide](https://google.github.io/styleguide/shellguide.html)
- [Google Python Style Guide](https://google.github.io/styleguide/pyguide.html)
- [PEP 8](https://peps.python.org/pep-0008/)
- [Bash Reference Manual: Bourne Shell Builtins](https://www.gnu.org/software/bash/manual/html_node/Bourne-Shell-Builtins.html)
- [Bash Reference Manual: Environment](https://www.gnu.org/software/bash/manual/html_node/Environment.html)
- [Python 3.8 subprocess](https://docs.python.org/3.8/library/subprocess.html)
- [Python 3.8 argparse](https://docs.python.org/3.8/library/argparse.html)
- [Python 3.8 logging](https://docs.python.org/3.8/library/logging.html)
- [llama.cpp server README](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)
