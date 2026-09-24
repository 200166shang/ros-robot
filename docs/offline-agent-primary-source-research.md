# Orange Pi 3B 离线大模型 Agent：一手来源技术调研

> 调研日期：2026-09-23。本文件对应的资料调研子任务只读项目与官方资料，没有独立 SSH 到板子，也没有运行安装、构建或部署命令。主方案另记录了同日的只读 SSH 核验结果，见 [端侧验证路线](offline-qwen-edge-validation-roadmap.md)。

## 结论

Mac 侧由 Codex 协助、管理学习记录，并可处理模型转换/量化；ROS 项目源码在 Orange Pi 的 Git 工作区开发、原生构建并做性能/资源测试。llama.cpp 官方提供 CPU build，Qwen 官方文档提供 Qwen3 的 llama.cpp 使用和 GGUF 模板说明。[llama.cpp build](https://github.com/ggml-org/llama.cpp/blob/master/docs/build.md) · [Qwen3 llama.cpp](https://github.com/QwenLM/Qwen3/blob/main/docs/source/run_locally/llama.cpp.md)

量化前后以同一源模型转换出的 BF16 GGUF 为基线，并由此生成 Q8_0、Q5_K_M、Q4_K_M。llama-bench 与机器人任务质量测试分开：前者测固定输入/输出 token 下的 pp/tg/pg，后者测工具调用、JSON、安全拒答、端到端延迟和内存。llama-bench 不包括 tokenizer 与 sampling 时间。[llama-bench](https://github.com/ggml-org/llama.cpp/blob/master/tools/llama-bench/README.md) · [quantize](https://github.com/ggml-org/llama.cpp/blob/master/tools/quantize/README.md)

ASR 先试 sherpa-onnx CPU arm64 路径和项目已经引用的双语 streaming Zipformer；不能据此宣称它在 RK3566 上达到实时、准确或内存目标。[Linux arm64 CPU](https://k2-fsa.github.io/sherpa/onnx/install/linux.html) · [Zipformer model](https://k2-fsa.github.io/sherpa/onnx/pretrained_models/online-transducer/zipformer-transducer-models.html)

ROS 侧先使用本地 llama-server 加 ROS 2 client，并将 LLM 输出经过 schema 和 allowlist 后送给当前 dry-run Agent。缺少轮子、电机驱动、头舵机、雷达时，可以验收软件链路、模型、语音、视觉 dry-run；不能声称实体运动、舵机控制、建图定位、避障或导航已完成。[llama-server](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md) · [ROS 2 command_agent](../ros2_ws/src/robot_agent/robot_agent/command_agent.py) · [perception demo](perception-demo.md)

## 1. 项目现状和边界

项目硬件档案记录 Orange Pi 3B / RK3566、四核 Cortex-A55、aarch64、4GB RAM、Ubuntu 20.04 与 ROS 2 Foxy；档案也记录 C270 和 USB 麦克风 16 kHz 单声道采集。此处引用的是既有项目记录，不是本文件编写当日的即时观察。通用硬件/网络操作留在独立 `oragnepi-pratice` 仓库；本项目的能力边界见[移植评估](robot-portability-assessment.md)。

当前 ROS 2 command_agent 只识别 status、start/stop_camera、start/stop_tracking，发布 JSON 状态，不接 LLM 或真实电机。[command_agent.py](../ros2_ws/src/robot_agent/robot_agent/command_agent.py) acceptance_probe 会注入测试人物框后检查 dry-run 输出，证明的是软件契约，不是实体运动。[acceptance_probe.py](../ros2_ws/src/robot_bringup/scripts/acceptance_probe.py)

旧项目 offline-agent 引用 sherpa-onnx Zipformer 与 SummerTTS；检查到其模型权重为 Git-LFS 指针，需确认下载真实权重。旧 llamacpp-ros 是 ROS 1/catkin，CMake 硬编码 x86_64 libcurl，已检查的 libllama/libggml-cpu 为 x86-64 ELF，不能直接在 aarch64 板上使用。[旧启动脚本](https://github.com/200166shang/robot/blob/main/offline-agent/start.sh) · [SummerTTS README](https://github.com/200166shang/robot/blob/main/offline-agent/tts/README.md) · [旧包 CMake](https://github.com/200166shang/robot/blob/main/offline-agent/llamacpp-ros/CMakeLists.txt)

旧 start.sh 将 TTS 绑到 CPU 4–7，而项目板卡记录为四核；使用前要查目标机实际 online CPU 并重做 affinity，不可照搬。[start.sh](https://github.com/200166shang/robot/blob/main/offline-agent/start.sh)

本次未确认的事项：当前 SSH 是否可用、可用内存/swap、板端热状态、LFS 权重是否取回、llama.cpp commit/构建选项、模型聊天模板、ASR/TTS 在板上的 RSS/速度、音频输出设备。不要把这些写成已验证事实。

## 2. LLM 量化与端侧基准方案

### 比较设计

在 Mac 上对同一份原始模型做转换，保留 BF16 GGUF 基线，再从同一基线生成 Q8_0、Q5_K_M、Q4_K_M；记录模型来源与 revision、文件 SHA-256、量化命令、llama.cpp commit、模板和合并 LoRA 状态。llama.cpp 文档说明量化可缩小模型并可能加快推理，但也可能损失精度；哪种格式最适合本板必须实测，不能仅凭位宽预判任务质量。[转换与量化](https://github.com/ggml-org/llama.cpp/blob/master/tools/quantize/README.md)

在 Orange Pi 上先跑 llama-bench 微基准，固定线程、上下文和 batch 参数，分别测试 prompt processing（pp，提示词处理）、token generation（tg，逐 token 生成）及 prompt+generation（pg，组合场景）。例如对各模型使用相同的 128/512 输入 token、64/128 输出 token、1/2/4 线程和至少 10 次重复；保存 JSON 结果。llama-bench 测 pp/tg 等固定工作负载，不计 tokenizer 或 sampling，因此不能替代真实 Agent 测试。[llama-bench 参数与限制](https://github.com/ggml-org/llama.cpp/blob/master/tools/llama-bench/README.md)

任务级测试使用冻结的 20 条提示词，每条重复 5 次：5 条对应当前支持的 status、start_camera、stop_camera、start_tracking、stop_tracking；5 条同义表达；5 条请求移动、舵机、导航等当前不支持动作；5 条含糊或普通问答。所有模型使用相同系统提示、Qwen chat template、采样参数、seed、上下文、输出上限和工具 schema。Qwen3 在 llama.cpp 的模板支持需按官方说明配置（包括适用时的 Jinja 模式），并记录实际版本与模板。[Qwen3 + llama.cpp](https://github.com/QwenLM/Qwen3/blob/main/docs/source/run_locally/llama.cpp.md) [Qwen3 function calling](https://github.com/QwenLM/Qwen3/blob/main/docs/source/framework/function_call.md)

每次记录：pp 与 tg tokens/s、首 token 与完整响应延迟、p50/p95、有效 JSON 比例、schema 合规率、allowlist 命令准确率、对不支持动作的拒绝/澄清率、模型文件大小、冷启动时间、进程 peak RSS/PSS、swap 增量、OOM/崩溃，以及可读取时的 CPU 频率、温度和降频迹象。先冷机、后连续运行至少 10 分钟；保存原始逐条结果，不只报平均值。20×5 的 p95 仅是个人工程对比值，不是 MLPerf 合规结果；MLPerf 对交互式负载规定了特定延迟统计和样本量，Agentic Function Calling 场景也有独立规则。[MLPerf inference rules](https://github.com/mlcommons/inference_policies/blob/master/inference_rules.adoc)

### 运行顺序与角色

- Mac 开发机：准备原模型/已合并 LoRA，转换并量化，归档模型、命令、revision 与校验和；Mac 的延迟和内存结果不代表 RK3566。
- Orange Pi：在目标系统上为 aarch64 原生构建 llama.cpp；先独立运行 CLI/llama-bench，再启动只监听本机或可信网络的 llama-server，最后由 ROS 2 client 调用。官方项目提供 CPU 构建和 HTTP server 接口。[CPU build](https://github.com/ggml-org/llama.cpp/blob/master/docs/build.md) [llama-server](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)
- ROS 集成：将模型输出当作不可信输入，先解析 JSON、验证 schema 与当前命令 allowlist，再交给 dry-run Agent；不要把模型文本直接当 shell 命令，也不要让它直接控制运动话题。当前项目节点只有固定命令与状态输出，尚无 LLM 或真实电机控制。[command_agent.py](../ros2_ws/src/robot_agent/robot_agent/command_agent.py)

## 3. 离线 ASR/TTS：先选候选，再测目标板

**ASR 候选。** sherpa-onnx 官方支持 Linux CPU aarch64；这是运行时平台支持，不等于已验证 RK3566 的速度或精度。[Linux ARM64 安装说明](https://k2-fsa.github.io/sherpa/onnx/install/linux.html) 项目现有代码引用的 streaming Zipformer 中英模型可作为第一候选，官方模型页列出小型模型、量化变体及实时麦克风示例；所列模型目录大小是磁盘占用，不是运行 RSS。[Zipformer 模型目录](https://k2-fsa.github.io/sherpa/onnx/pretrained_models/online-transducer/zipformer-transducer-models.html) 可用官方离线 Paraformer 的小型/int8 中英模型作第二候选，比较流式低延迟与离线整句识别的取舍。[Paraformer 模型目录](https://k2-fsa.github.io/sherpa/onnx/pretrained_models/offline-paraformer/index.html)

用固定的 30–50 条授权录音，覆盖中英文、安静/风扇噪声、远近距离和命令口语；报中文 CER、英文 WER、命令意图准确率、实时因子（处理时长/音频时长）、端点延迟、CPU 与 peak RSS。WER 的替换、插入、删除定义可参考 NIST SCTK。[NIST SCTK sclite](https://github.com/usnistgov/SCTK/blob/master/doc/sclite.htm) 需实际确认采样率、VAD/端点策略、麦克风设备和连续运行资源；不可从模型目录大小推断 4GB 板端一定装得下。

**TTS 候选。** 先检查项目 SummerTTS 的 Git-LFS 权重是否为真实文件并测其已有链路；否则 sherpa-onnx 官方 VITS Melo 中英单说话人模型可作备选，模型页列出的文件约 163MB，且英文发音依赖词典等配置，因此仍需核实声音、部署限制和内存。[VITS/Melo 模型页](https://k2-fsa.github.io/sherpa/onnx/tts/pretrained_models/vits.html) sherpa-onnx 提供离线 TTS API；逐条测试固定 20–30 句，测生成时长、实时因子、峰值内存、音频格式及主观可懂度。[TTS C API](https://github.com/k2-fsa/sherpa-onnx/blob/master/sherpa-onnx/c-api/docs/tts.dox) 小规模内部听测只能作为工程反馈，不能称为标准 MOS；ITU-T P.800 的主观语音质量方法有正式受控程序。[ITU-T P.800](https://www.itu.int/rec/T-REC-P.800-199608-I/en)

**适合 RK3566 的判断仍是待验证假设。** sherpa-onnx 有 CPU ARM64 支持，模型也有小型/量化候选；但 RK3566 的实际吞吐、热稳态、声音质量、并发与 4GB 内存余量没有由这些官方页面保证。先半双工串行跑“麦克风→VAD/ASR→ROS 2 请求队列→LLM→JSON/allowlist→dry-run→TTS”，分别测每段和端到端延迟；避免在 ROS executor 回调中同步等待长推理。

## 4. 没有底盘硬件时的验收边界

**可以如实展示：** 在实际板子上模型能否加载、固定 prompt 下速度和资源、录音 ASR/TTS 文件生成、ROS 2 消息/JSON 契约、命令拒绝与 dry-run 状态机；项目已有视觉演示记录的是相机、检测和 dry-run tracking 软件链路。[perception demo](perception-demo.md) 若 acceptance probe 注入合成检测框，它只验证软件响应与契约，不验证真实目标跟踪或移动。[acceptance_probe.py](../ros2_ws/src/robot_bringup/scripts/acceptance_probe.py)

**不能声称已验证：** 轮子或底盘运动、闭环电机控制、头部舵机动作、真实跟随、里程计、激光建图/定位、避障、导航、实体急停，以及未连接扬声器时的现场语音播报。缺失对应硬件/传感器时，软件 mock 不构成这些能力的验证。通用板卡记录留在独立 `oragnepi-pratice` 仓库；项目移植范围见[移植评估](robot-portability-assessment.md)。

旧 offline-agent 参考代码还需移植与核验：项目记录的 llamacpp-ros 是 ROS 1/catkin，旧构建文件含 x86_64 假设，旧二进制不能直接当作 Orange Pi aarch64 ROS 2 产物；项目启动脚本的 TTS CPU affinity 也不能照搬到四核板上。[旧 CMakeLists](https://github.com/200166shang/robot/blob/main/offline-agent/llamacpp-ros/CMakeLists.txt) [旧 start.sh](https://github.com/200166shang/robot/blob/main/offline-agent/start.sh) 这是基于仓库代码与板卡档案的项目判断，不是对板端现状的运行验证。

**建议验收门槛按阶段推进：** ① Mac 固定模型和 prompt 集、生成校验和；② Orange Pi 单独完成加载、bench 与长时资源记录；③ Orange Pi 上 ASR/TTS 分项测试；④ ROS 2 dry-run 串起语音、模型、校验与状态反馈；⑤ 日后补齐电机、舵机、轮子和雷达后，再另做实体安全、闭环及导航验收。每阶段保存硬件/软件版本、原始数据和失败项；本次不预设未经测量的数值门槛。

## 来源与证据边界

外部技术事实均链接至项目官方文档/源码、MLCommons、NIST 或 ITU-T；项目现状引用本仓库文档和代码。板端性能、温度、真实模型文件、LFS 状态和整机集成表现尚未实测，均作为待验证项，而非来源结论。
