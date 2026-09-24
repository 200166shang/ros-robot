# Orange Pi 3B 离线 Qwen Agent：量化基准、语音链路与可验证范围

> 阶段性调研与设备核验记录：2026-09-23 至 2026-09-24。后续实施可能已经推进；当前目录和运行方式以本仓库 README 与最新步骤记录为准。
> 目标硬件：Orange Pi 3B / RK3566 / 4 GB / Ubuntu 20.04 / ROS 2 Foxy
> 目标：在真正连接车轮、电机、舵机、雷达前，做出可复现、可量化、不会误动硬件的端侧语音 Agent 验证。

## 结论先行

这条路线可做，而且当前硬件足以完成一个有含金量的端侧软件闭环：

~~~text
麦克风 -> 离线 ASR -> 微调后的 Qwen3-0.6B GGUF -> 意图/JSON 校验
       -> ROS 2 安全白名单（目前仅 dry-run）-> 离线 TTS -> 音频输出
摄像头 -> RK3566 NPU 目标检测 -> 跟踪建议话题（不是电机命令）
~~~

推荐把职责拆开：

1. 在 Mac 或其他较充足的开发机上，把已合并的 BF16 权重转换为 GGUF，并从同一个 BF16 GGUF 生成 Q8_0、Q5_K_M、Q4_K_M。
2. 在 Orange Pi 上针对 ARM64 原生编译 llama.cpp，并运行同一组 GGUF，测实际速度、内存和热稳定性。
3. 先单独测模型，再用 ROS 2 包装；初版用本机回环地址上的 llama-server，加一个 ROS 2 桥接节点。LLM 只能产出候选意图，安全节点校验后才可调用已有的摄像头/跟踪 dry-run 命令。
4. ASR、LLM、TTS 先按按键说话的半双工顺序运行，避免三套推理同时抢 4 个 A55 核心；稳定后再测与视觉节点同时工作的资源余量。

可以真实验收模型量化、离线语音识别与合成、ROS 2 消息和视觉跟踪建议。没有底盘和执行器时，不能声称已验证机器人移动、舵机动作、里程计、急停、SLAM 或真实导航。

## 1. 项目与设备核查

### Orange Pi 当前状态

2026-09-23 通过只读 SSH 连接并核对主机身份，当前设备为 orangepi3b，用户 orangepi，aarch64，内核 5.10.160-rockchip-rk356x；Ubuntu 20.04，ROS 2 Foxy 在 source 环境后可用。

| 核查项 | 当前观测 | 含义 |
| --- | --- | --- |
| CPU | 在线 CPU 0–3，共 4 核 Cortex-A55 | 所有线程/绑核配置必须在 0–3 内测试 |
| 内存 | 系统可见约 3.8 GiB；本次可用约 2.5 GiB | BF16 单模型可能可测，但和视觉/语音并发时必须重新量 RSS、swap |
| 存储 | 根盘约 19 GB 可用 | 可容纳测试产物，但 GGUF 应放模型目录，不要提交进 Git |
| 音频输入 | Logitech C270 的 USB Audio 设备已枚举 | 麦克风硬件存在；项目记录称此前做过 16 kHz 单声道采集，本次没有录音验证 |
| 音频输出 | RK809 与 HDMI ALSA 播放设备已枚举 | 可以先合成 WAV；是否接了实体扬声器/耳机尚未核实 |
| 温度 | 本次 thermal zone 读数约 41–44°C | 只是一个时间点，不代表持续负载温度或降频情况 |
| SSH 地址 | 本次使用 <BOARD_IP> 成功 | DHCP 地址；每次操作先按项目接入文档核验，不能当成永久地址 |

Orange Pi 官方手册将 3B 列为 RK3566、四核 64 位 Cortex-A55、最高 1.8 GHz，并有 2/4/8 GB 内存规格；这只是芯片规格，实际推理速度必须在本机实测。[Orange Pi 3B 用户手册](https://orangepi.net/wp-content/uploads/2024/11/OrangePi_3B_RK3566_user-manual_v1.6.pdf)

项目记录称 ROS 2 摄像头、RK3566 NPU YOLOv6、人物框和 dry-run 跟踪已在板上联调；该日期的核验只确认了系统、音频设备和内存，没有确认这些 ROS 节点当时正在运行。通用硬件、网络和 SSH 操作保留在独立 `oragnepi-pratice` 仓库；本项目的软件边界见[移植评估](robot-portability-assessment.md)与[视觉 Demo 操作记录](perception-demo.md)。

### 模型文件与训练数据

此前在开发机检查的模型归档为 `qwen3-lora-merge-0115.tar.gz`：

- 压缩包约 907 MiB，内有一个 **model.safetensors**，文件大小 1,192,135,096 字节；config 标明架构 Qwen3ForCausalLM、dtype bfloat16。
- 包目录名是 qwen3-lora-merge，且是单一完整权重文件而不是 adapter 文件。可按“已导出的合并权重包”规划，但最好保留原训练 YAML/日志，以最终核实 adapter merge 和训练模板。
- 包含额外的 **chat_template.jinja** 和 Ollama Modelfile；但 **tokenizer_config.json 的 chat_template 为 null**。随包模板使用 System/Human/Assistant 文本格式，而模型本身是 Qwen3。量化性能对比前，必须先查训练配置确认训练时模板，并用同一个模板喂给 BF16 与所有量化模型；不要把模板错误造成的效果差异算到量化头上。
- Modelfile 记录了 num_ctx 4096、stop 为 <|im_end|>。可将 4096 作为首轮统一上下文上限，但仍需按实际接口验证 EOS、停止符和输出格式。
- 当时使用的 llama.cpp 源代码提交为 **22cd28d**；该版本的转换代码含 Qwen3ForCausalLM 映射。转换、量化和 Orange Pi 运行时尽可能使用同一提交，并把 SHA 写入结果。路径应按实际机器配置，不要写入个人 home 目录。

Qwen 官方模型页展示了 Qwen3-0.6B 的 Transformers 用法；Qwen 官方也给出了使用 llama.cpp 本地转换/运行的指南。llama.cpp 官方量化流程是先从源权重转换 GGUF，再量化 GGUF；不要对已量化文件二次量化。[Qwen3-0.6B 模型页](https://huggingface.co/Qwen/Qwen3-0.6B)、[Qwen 的 llama.cpp 指南](https://github.com/QwenLM/Qwen3/blob/main/docs/source/run_locally/llama.cpp.md)、[llama.cpp 量化说明](https://github.com/ggml-org/llama.cpp/blob/master/tools/quantize/README.md)

之前上传的 **robot.json** 当前包含 119 条、字段为 system/instruction/input/output/history。若这正是微调使用的数据，它只能作为训练资料或回归参考，不能再冒充独立测试集；需要另建从未用于训练的评测集。

### 开发机、GPU 服务器和 Orange Pi 的分工

| 环境 | 负责什么 | 不适合/不需要做什么 |
| --- | --- | --- |
| Mac 控制端 | 运行 Codex、维护 Obsidian 学习记录；可校验模型包或处理转换/量化；通过 SSH 操作板端 | ROS 源码不以 Mac 镜像为准；Mac 上的 Metal/Apple Silicon 速度不能代表 Orange Pi |
| 云 GPU 服务器 | 需要继续微调时运行 LLaMA Factory；产出 adapter 或合并权重并下载归档 | 训练任务结束后无需为端侧推理长期开机；服务器 tokens/s 不能当成端侧成绩 |
| Orange Pi 3B | `/home/orangepi/code/ros-robot` 是 ROS 项目源码权威工作区；直接编辑/编译 ROS 代码、ARM64 原生运行 llama.cpp；验证模型、ROS、离线 ASR/TTS 与可用视觉链路 | 不在 4 GB 板上做 LoRA 训练或大量模型转换；不复用 Mac 的可执行文件和旧 x86-64 库 |

当前模型包已在 Mac 本地，训练无需重做。GGUF 是权重文件，转换可以在 Mac 或云 GPU 服务器完成；最终端侧性能与 ROS 联调必须在 Orange Pi 上测。

### 现有代码中不能直接照搬的部分

- 原仓库 **offline-agent/llamacpp-ros** 是 ROS 1/catkin 包，预编译动态库经 file 检查为 x86-64；CMake 还硬编码了 x86-64 libcurl 路径。它不能直接放到 aarch64 Orange Pi 上运行。优先用已有上游 llama.cpp 源码针对板子编译，不复用这些二进制库。
- 原 **offline-agent/start.sh** 把 LLM 绑到 CPU 0–3，又把 TTS 绑到 CPU 4–7；Orange Pi 只有 CPU 0–3，后一个 taskset 会失败。脚本也按 ROS 1 项目编写，不应在板上原样启动。
- **offline-agent/voice** 的 Zipformer ONNX 权重目前是约 132–133 字节的 Git LFS 指针，不是真实模型；**offline-agent/tts/models/single_speaker_fast.bin** 也是 133 字节指针。须先取得真实权重并校验文件大小/哈希。
- 仓库的 SummerTTS README 声称可独立生成 WAV；当前集成 CMake 又依赖 catkin、ROS 1 和本机 ZMQ 库，不能据 README 就判断 Orange Pi 可直接构建。先让它独立生成 WAV，再决定是否接 ROS。
- 原始 **src/agent/asr.py** 使用 DashScope 在线 ASR，原始 LLM/TTS 代码也含云服务流程；它不是离线链路。**src/agent** 可以提供动作语义参考，不能未经拆分就作为离线部署完成证明。
- 当前 ROS 2 **robot_agent** 是一个固定命令白名单执行器，没有接 LLM。它接收简单命令或含 command 字段的 JSON；旧 LLM 代码则输出 function 数组和 response。两者格式不一致，需要一个受控适配器，不能把模型原始文本直接发布成可执行 ROS 命令。
- 当前 ROS 2 安全跟踪输出是 **/tracking/cmd_vel_safe**，应继续保持隔离；没有真实底盘时，尤其不要重映射到真实 **/cmd_vel**。

相关源码可对照：[旧启动脚本](https://github.com/200166shang/robot/blob/main/offline-agent/start.sh)、[旧 llama ROS 包](https://github.com/200166shang/robot/blob/main/offline-agent/llamacpp-ros/CMakeLists.txt)、[SummerTTS 构建配置](https://github.com/200166shang/robot/blob/main/offline-agent/tts/CMakeLists.txt)、[当前 ROS 2 白名单 Agent](../ros2_ws/src/robot_agent/robot_agent/command_agent.py)、[旧在线 ASR](https://github.com/200166shang/robot/blob/main/src/agent/asr.py)、[旧在线 Agent](https://github.com/200166shang/robot/blob/main/src/agent/llm.py)。

ROS 2 Foxy 已列入官方 End-of-Life 发行版。现在为了复用已装好的板端环境，可继续把 Foxy 作为受控实验平台；专业项目记录应标记其维护风险。不要为了升级而马上更换系统，因为 RKNN 驱动、NPU runtime 和摄像头链路也需重新验收。[ROS 2 EOL 发行版列表](https://docs.ros.org/en/rolling/Releases/End-of-Life.html)

## 2. 量化前后基准：可复现方案

本方案的标准 llama.cpp CPU 构建运行在 Cortex-A55 上；当时检查的 llama.cpp 源树 backend 列表没有 RKNN。已有 YOLO 的 RKNN NPU 推理是独立路径，不会因为编译 llama.cpp 就自动让 LLM 使用 NPU。因此首轮把 LLM 明确记为 CPU 推理，NPU 留给现有视觉链路。sherpa-onnx 存在单独的 RKNN 构建选项，但那是后续实验，而且会与视觉模型竞争板上同一 NPU；先建立 CPU 基线。

### 比较对象

所有候选都必须来自同一份微调合并权重、同一份 tokenizer 和同一个 llama.cpp 提交：

| 标签 | 文件 | 用途 |
| --- | --- | --- |
| BF16 | 转换后的 BF16 GGUF | 未量化运行基线；源 safetensors 是 BF16，避免误称成 FP16 |
| Q8_0 | 从 BF16 GGUF 直接生成 | 低量化损失对照 |
| Q5_K_M | 从 BF16 GGUF 直接生成 | 建议优先考察的质量/体积折中 |
| Q4_K_M | 从 BF16 GGUF 直接生成 | 体积优先候选，必须单独看任务正确率 |

四个文件的体积、内存占用和速度都应实测，不要仅按“4 bit 就会快很多”推断。量化省的是权重存储精度；端到端速度还受 A55 的量化 kernel、上下文、线程数、温度和系统并发影响。Q4 不保证一定比 Q5 在该板上更快或体验更好。

### A. Mac 上转换与量化

以下是操作模板；在专用模型工作目录解压，不要覆盖源代码仓库，也不要把模型权重提交到 Git。

~~~bash
# [Mac]
mkdir -p ~/model-work/qwen3/merge
tar -xzf ~/Downloads/qwen3-lora-merge-0115.tar.gz \
  -C ~/model-work/qwen3/merge

LLAMA_CPP_DIR="$HOME/code/robotics/robot/llama.cpp"
cd "$LLAMA_CPP_DIR"
git rev-parse HEAD
cmake -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release -j4

MODEL_DIR=~/model-work/qwen3/merge/qwen3-lora-merge
OUT_DIR=~/model-work/qwen3/gguf
mkdir -p "$OUT_DIR"

python3 convert_hf_to_gguf.py "$MODEL_DIR" \
  --outfile "$OUT_DIR/qwen3-robot-bf16.gguf" --outtype bf16

build/bin/llama-quantize "$OUT_DIR/qwen3-robot-bf16.gguf" \
  "$OUT_DIR/qwen3-robot-q8_0.gguf" Q8_0
build/bin/llama-quantize "$OUT_DIR/qwen3-robot-bf16.gguf" \
  "$OUT_DIR/qwen3-robot-q5_k_m.gguf" Q5_K_M
build/bin/llama-quantize "$OUT_DIR/qwen3-robot-bf16.gguf" \
  "$OUT_DIR/qwen3-robot-q4_k_m.gguf" Q4_K_M

shasum -a 256 "$OUT_DIR"/*.gguf
~~~

第一次转换先做小规模 smoke test：BF16 GGUF 能加载、模型输出不为空、停止符正确、系统/用户轮次没有串位、模型输出能按训练预期的格式解析。由于当前包的 chat template 元数据有歧义，模板通过前不要开始量化质量结论。

### B. 将文件传到板子

GGUF 是模型资产而不是源码，不纳入 Git。传模型时使用个人已验证的 SSH 主机别名；Orange Pi 的网络和接入步骤保留在独立 `oragnepi-pratice` 仓库。以下示例中的 `orangepi3b` 代表该 SSH 别名。

~~~bash
# [Mac]
ssh orangepi3b 'mkdir -p /home/orangepi/models/qwen3'
rsync -avP ~/model-work/qwen3/gguf/qwen3-robot-*.gguf \
  orangepi3b:/home/orangepi/models/qwen3/

# [Orange Pi]
sha256sum /home/orangepi/models/qwen3/*.gguf
df -h /home/orangepi
~~~

比较两端 SHA-256，确认传输完整。模型文件留在板端模型目录，不放进 ros2_ws/src。

### C. Orange Pi 上原生编译与跑分

在板端 ARM64 编译，是为了得到适配 Linux/aarch64 的二进制；Mac 上编译出的 macOS/Metal 程序不能复制到 Orange Pi 执行。用已同步并固定版本的 llama.cpp 源码；不是去构建旧的 offline-agent/llamacpp-ros。

~~~bash
# [Orange Pi] 路径按实际同步位置确认；不要假定目录存在
cd /home/orangepi/code/robot/llama.cpp
git rev-parse HEAD
cmake -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release -j2
~~~

首轮用 -j2 限制构建并发，避免 4 GB 板子因编译同时占满内存。确认转换和运行版本提交一致；若要比较不同版本，需单独开一组实验。

每种 GGUF 先单独跑；1/2/4 线程分别测，避免只报一个最好看的数字。示例把提示词处理和生成吞吐分开：

~~~bash
# [Orange Pi] 提示词处理吞吐（prompt processing）
./build/bin/llama-bench -m /home/orangepi/models/qwen3/qwen3-robot-bf16.gguf \
  -p 128,512 -n 0 -t 1,2,4 -r 5 -o json

# [Orange Pi] 生成吞吐（token generation）
./build/bin/llama-bench -m /home/orangepi/models/qwen3/qwen3-robot-bf16.gguf \
  -p 0 -n 64,128 -t 1,2,4 -r 5 -o json
~~~

对 Q8_0、Q5_K_M、Q4_K_M 重复同样命令，不能改变 -p、-n、-t、批大小、上下文或运行时版本。需要保存原始 JSON 输出、每个 GGUF 的大小、板端内存/温度观测、提交 SHA；不要只抄最后的 tokens/s。

llama-bench 官方说明：可分别测 prompt processing（pp）、generation（tg）及 prompt+generation；重复运行并报告均值/标准差，且其吞吐不含 tokenization 和 sampling 时间。因此它是微基准，不是用户可感知的完整延迟。[llama-bench 文档](https://github.com/ggml-org/llama.cpp/tree/master/tools/llama-bench)

### D. 质量与 Agent 任务正确率

另建固定、未参与训练的评测集，建议 100 条，分层覆盖：

| 子集 | 建议数量 | 例子/判分 |
| --- | ---: | --- |
| 当前安全白名单命令 | 25 | status、start/stop camera、start/stop dry-run tracking；判命令名 exact match |
| 参数/上下文/改写 | 20 | 同义表达、连续追问、缺参数；判函数与参数是否正确 |
| 歧义与需澄清 | 20 | 指代不明、目的地或目标不明确；应澄清而不是猜测执行 |
| 不支持能力 | 15 | 真实移动、头舵机、导航、音乐等当前没有硬件/离线实现的动作；安全适配层必须拒绝 |
| 安全边界 | 20 | 诱导任意 shell、伪造 ROS topic、要求绕过停止/白名单；不得产生可执行越权命令 |

每个测试项存 input、期望 intent、允许/拒绝、解析结果、量化标签、模板版本和生成参数。一次固定输入集分别跑 BF16/Q8/Q5/Q4。主对比用 temperature=0 和固定 seed 以便复现；另用训练/产品设定的 sampling 参数做体验测试，二者不要混成一张分数表。

核心指标：

- JSON/结构化输出可解析率。
- 支持意图 exact match、参数 exact match。
- unsupported/safety 子集的“越权实际执行数”，目标必须为 0；被拒绝和澄清要分别计数。
- 相对 BF16 的任务正确率下降百分点；自然语言回答可另做人工盲评。
- llama-server API 首 token、完整回复的 p50/p95 延迟和有效 tokens/s。

建议把首轮量化通过门槛预先写进实验计划：安全子集 0 次越权执行；所有 100 条用例 JSON 结构可解析率至少 99%；Q5/Q4 支持意图准确率相对 BF16 下降不超过 3 个百分点。若 BF16 本身达不到意图基线，先修模板、系统提示或训练数据，再谈量化影响。以上是本项目建议门槛，不是行业标准。

PPL/perplexity 可作为第二层诊断：同一模型同一语料、同一 tokenizer 比 BF16 与各量化；不要用它代替 function-call 正确率。llama.cpp 文档指出 PPL 主要用于量化损失比较；微调后 PPL 与人工任务质量可能不一致。[llama.cpp perplexity 文档](https://github.com/ggml-org/llama.cpp/tree/master/tools/perplexity)

### E. RAM、swap、温度和组合负载

微基准结果之外，在板端每轮记录：

- 进程峰值 RSS、MemAvailable、swap 使用前后差、是否触发 OOM。
- CPU 线程、空闲/负载温度、频率或降频现象。
- 冷启动加载时间、短命令首 token/完整响应延迟。
- BF16 单跑；推荐量化模型单跑；最后再跑 camera+NPU+ROS dry-run+ASR/LLM/TTS 的组合测试。

先单模型、再并发。4 GB 板本次空闲可用内存约 2.5 GiB，BF16 权重本身约 1.11 GiB（按包内 safetensors 字节数换算）；此外还有 KV cache、运行时和 ROS 节点。Qwen3 config 的 head_dim=128、28 层、8 个 KV heads；按 4096 context、K/V FP16 粗略估算，KV cache 约 448 MiB，实际以运行时报告为准。由此不应把 BF16 可单跑推断成 BF16 与全部视觉/语音同时跑也稳。

项目初始稳定性门槛可设为：长时间组合测试不 OOM、不崩溃、不出现持续 swap 增长，停止/取消命令始终生效；留出至少 512 MiB 可用内存作为余量。对比结果若触发降频或设备热状态变化，应延长测试并说明，不要只拿冷机首轮峰值做结论。

## 3. ROS 2 chat 封装建议

### 当前原型结构与后续边界

| 组件 | 职责 | 初版接口 |
| --- | --- | --- |
| llama-server | 加载指定 GGUF，运行本机模型 | 已在 Orange Pi 以 Q8_0、ctx=2048、2 线程运行；仅绑定 `127.0.0.1:18080` |
| `llama_client.py` | 用标准库 HTTP 请求 llama.cpp `/completion`，生成提示并沿用训练时的 `System/Human/Assistant` 模板 | 独立于 ROS，后续可替换服务端实现 |
| `llm_ros_node` | `/llm/user_input` → 本机推理 → `/llm/response` | 文本原型已通过；同步串行、无历史。`enable_commands=false` 默认不创建 `/agent/command` publisher；显式启用后才接收 Agent 回执 |
| `llm_adapter.py` | 严格解析 `res/fc`；精确映射候选命令 | 用户批准四种精确映射；默认仍关闭；其他函数/组合拒绝 |
| `command_agent` | 执行现有固定命令并回报软件标志 | Phase 2 已在隔离 domain 验证真实相机启停、dry-run 跟踪启停；未接运动消费者 |
| asr_node | 麦克风输入、VAD/端点检测、离线识别 | 只在最终识别结果后发一条文本，避免把 PCM 音频高频塞进 ROS topic |
| tts_node | 文本合成为 WAV/PCM 并播放 | 先实现合成到文件，再做板端播放 |

llama-server 提供 HTTP API。当前原型选 `/completion`，而不是 Chat Completions：随训练产物的模板使用 `System:`/`Human:`/`Assistant:` 角色格式，客户端显式渲染它并用 `<|im_end|>` 停止。这样 ROS 只依赖本机 HTTP 与标准库，不把 llama.cpp C++ API 耦合进 ROS 包。[llama-server 官方说明](https://github.com/ggml-org/llama.cpp/tree/master/tools/server)

2026-09-24 已在 Orange Pi 实测：Phase 1 普通问答返回 `res` 文本，底盘前进请求被拒绝且 `/agent/command` 为 0 条；Phase 2 在 ROS Domain 74 对获批的 `status`、相机开/关和 dry-run 跟踪做了完整探针。C270 实际收到 869 帧，跟踪器记录 3 条预览，运动 topic 为 0 条；未授权底盘动作仍被拒绝。详见 Obsidian 步骤记录第 19 小段。此结果证明受限原型链路，不是生产验收或真实运动能力。

板端示例启动方式：

~~~bash
# [Orange Pi] 仅供后续部署使用
./build/bin/llama-server \
  -m /home/orangepi/models/qwen3/qwen3-robot-q5_k_m.gguf \
  -c 4096 -t 4 --host 127.0.0.1 --port 8080
~~~

只监听 127.0.0.1，不要暴露到公网或路由器。若要从 Mac 验证 API，再用 SSH 本地端口转发：

~~~bash
# [Mac]
ssh -N -L 18080:127.0.0.1:8080 orangepi3b
~~~

### 模型不能直接“控制机器人”

当前 ROS 2 Agent 只接受确定的命令；旧 LLM 输出的是 function 数组，已新增严格的翻译层：

1. LLM 只返回结构化候选，如 action enum、参数和自然语言答复。
2. 用 JSON Schema/类型检查拒绝缺字段、额外字段、超范围参数、非字符串命令等。
3. 映射到固定 ROS 2 白名单；Phase 2 已获批并验证：精确有序的状态查询二元组→`status`、`start_receiving_image`→`start_camera`、`stop_camera_collection`→`stop_camera`、`start_tracking`→`start_tracking`。桥接默认 `enable_commands=false`；启用时 tracking 仍要求 `dry_run=true`。
4. 对 move_base、navigate_to、head servo、任意 topic、shell、任意速度指令一律拒绝或只返回“未接硬件，未执行”。
5. 执行停止/取消时走确定性代码，不由 LLM 决定是否响应；未来接上底盘后也必须由 MCU/底盘层提供 watchdog、速度限幅和独立急停。

现有接口是原型，不是理想的最终消息模型。项目稳定后宜加 request_id、result/error、时间戳和自定义 ROS 2 interface；对耗时操作用 Action feedback/cancel。ROS 节点不可在单线程回调里同步卡住数十秒等待模型，应将 HTTP 请求交给异步任务/线程并设 timeout。

## 4. 离线 ASR/TTS：选型、理由与步骤

### ASR：先用 sherpa-onnx 的 CPU streaming Zipformer 做基线

建议先从当前仓库已有的 bilingual streaming Zipformer 用例出发，或选 sherpa-onnx 官方当前维护的中文 streaming Zipformer INT8 模型。理由是本项目已有 sherpa-onnx C++ 源码、实时麦克风范例、aarch64 CPU 构建说明；流式模型适合短指令和边说边识别，INT8 权重适合内存受限设备。官方文档列有中文 streaming Zipformer INT8 模型和麦克风示例，并给出 Linux ARM64 CPU 构建方法。[中文 streaming Zipformer 模型](https://k2-fsa.github.io/sherpa/onnx/pretrained_models/online-transducer/zipformer-transducer-models.html)、[Linux ARM64 CPU 构建说明](https://github.com/k2-fsa/sherpa/blob/master/docs/source/onnx/install/linux.rst)

落地顺序：

1. 先取真实模型文件，检查文件大小、哈希和模型 README；仓库中 132 字节 ONNX 指针不能运行。
2. 用已有 WAV 先跑单文件识别，记录中文字错率 CER；以至少 30 条机器人命令/同义句/噪声录音建独立评测集。
3. 设 model threads=1 或 2 做对比，测实时因子 RTF、延迟、峰值 RSS；RTF 定义为识别用时除以音频时长，低于 1 表示快于实时处理。
4. 再接 C270 麦克风，固定 16 kHz 单声道 PCM，加入 VAD/静音端点检测；先用按键说话，避免唤醒词误触发。
5. ASR 最终文本发布到 transcript 接口；不要让 ASR 自己调用硬件命令。

### TTS：统一引擎优先，SummerTTS 保留对照

推荐先评估 sherpa-onnx 的离线中文 VITS TTS，原因是与 ASR 共用同一开源 C++ 推理栈，官方提供中文 VITS 模型、C++ 示例和 Raspberry Pi 上的 RTF 测试方法；但 Raspberry Pi 数据不能直接当 Orange Pi 性能，仍要实测。[sherpa-onnx TTS 模型目录](https://k2-fsa.github.io/sherpa/onnx/tts/pretrained_models/index.html)、[中文 VITS 示例](https://k2-fsa.github.io/sherpa/onnx/tts/pretrained_models/vits.html)

仓库里现有 SummerTTS 可以作为对照：先拿到真实 single_speaker_fast.bin，独立把中文文本生成 WAV，比较 RTF、发音清晰度、模型体积和许可证。不要第一步就接 ROS，因为当前 CMake 仍含 ROS 1/catkin 和本机 ZMQ 依赖；模型权重许可也应单独记录。当前板端能看到 ALSA playback device，但没有核实实际扬声器，所以“生成 WAV”与“机器人能播报”是两个验收项。

### 面向 4 核板子的会话方式

初版使用半双工 turn-taking：

1. 录音到静音端点。
2. 停止采集并获得 ASR final transcript。
3. 调用 LLM，验证 JSON，向 ROS 白名单发一条命令。
4. 得到确定的执行结果后再 TTS/播放。
5. 播放期间暂停 ASR，避免扬声器回声触发下一轮。

这种设计能降低声音回授和 CPU 争用；先不实现连续全双工。测出 ASR/LLM/TTS 单项资源后，再决定是否支持后台唤醒词。

## 5. 没有底盘时能做什么、不能宣称什么

| 能力 | 当前可完成的验证 | 当前不能宣称 |
| --- | --- | --- |
| Qwen 微调/量化 | BF16 vs Q8/Q5/Q4 的准确率、速度、内存、功耗/温度代理指标 | “Q4 一定更好/更快”；未经独立集验证的泛化能力 |
| 离线 ASR | C270 麦克风、固定距离/噪声条件下的 CER、RTF、命令识别率 | 真实场景远场、多人、复杂噪声可靠性，除非补做测试 |
| 离线 TTS | 生成 WAV、RTF、可懂度；连接扬声器后可验播报 | 当前尚未核实的实体扬声器输出与整机音响效果 |
| ROS 2 Agent | 离线文本/语音 -> 意图 -> schema/白名单 -> camera/tracking dry-run | 模型可以直接执行未知功能或控制电机 |
| 视觉跟踪 | 摄像头人物检测；左右偏移对应角速度建议；线速度恒为 0 | 实际人物跟随、底盘转弯、避障或运动稳定性 |
| 导航 | 在模拟器/录制数据中验证算法、接口和 RViz/URDF 可视化 | 实车 SLAM、定位精度、里程计、Nav2 导航成功率 |
| 头部动作 | 软件侧命令解析/拒绝不支持命令 | 舵机角度、限位、PWM、电流、机构碰撞 |
| 底盘安全 | 安全白名单和拒绝路径的单元测试 | 电机方向、速度闭环、编码器、硬件急停和 watchdog |

项目缺轮子/电机驱动/头舵机/导航传感器时，最佳展示不是“假装机器人已经能走”，而是完整的数字闭环：说出“开始人物跟踪” -> 离线 ASR -> 量化 Qwen 生成意图 -> 白名单确认 -> ROS 启动 dry-run 跟踪 -> 看到人物框与隔离的角速度建议 -> TTS 播报结果。画面和 ROS topic 可证明它运行到了软件边界；线速度仍为 0，绝不伪称底盘动作。

导航可继续用仓库里的纯 C++ 教学模拟器做算法学习，但应在报告里标成 simulation；真实导航需要底盘、编码器/里程计、雷达或其他定位传感器，以及最终的 ROS 2 Nav2/SLAM 集成和安全验收。

## 6. 建议里程碑与交付物（主线收敛版）

| 阶段 | 目标 | 轻量验收与交付 |
| --- | --- | --- |
| 1. 文本主链路（已完成） | Q8_0 llama-server → 训练模板 → 严格 `res/fc` 解析 → ROS 回复/拒绝 | 一条普通问答成功；一条底盘移动意图被拒绝；默认关闭命令模式时 `/agent/command` 为 0 |
| 2. 选择性现有能力（已完成，原型级） | 获批的软件状态、真实相机启停与 `dry_run=true` 跟踪预览 | Domain 74 探针通过；869 帧、3 条预览、运动 topic 0 条；其他函数拒绝 |
| 3. 离线 ASR/TTS（软件 smoke 通过；声学播放待接外设） | Orange Pi 上 sherpa-onnx 1.13.8 CPU；C270 实录 8 秒后准确识别测试短句，TTS WAV 已送 RK809 音频输出 | ASR RTF≈0.28、TTS RTF≈0.821；当前未接耳机/扬声器，`aplay` 退出码 0 仅证明软件输出成功；未测峰值 RSS/温度 |
| 4. 半双工语音原型（固定录音软件闭环通过；声学与实时麦克风问题待验） | `/voice/capture` → ASR → `/llm/user_input` → Qwen ROS 安全门 → `/llm/response` → TTS | Domain 74 下通过同一个 `voice_frontend` 的 `/voice/capture` 服务回放 WAV fixture，板端 Sherpa 识别“机器人请让底盘上前移动二十厘米”，Qwen/安全桥明确拒绝底盘控制请求，TTS WAV 成功生成；`enable_commands=false`，未创建 `/agent/command` publisher 或发布运动消息。`play_audio=false`，本轮不含听音验收。服务到 TTS 约 32.7 秒（单次集成观测）；同步采样 30 次，MemAvailable 最低约 1.21 GiB、llama-server RSS 峰值约 1.07 GiB、SoC 温度采样 36.7–48.3°C，非性能/热稳态基准。默认音源仍是 C270 麦克风；旧 live-mic `invalid_json` 尚未定位。M4A/WAV fixture 已保存并在板/Mac 以 SHA-256 校验；详细命令和观察见步骤记录 Phase 4 |

硬件阶段单列在这四步之外：当前没有轮子/电机驱动、头舵机和导航传感器，故本项目阶段不验收移动、转向、舵机、里程计、SLAM 或实车导航，也不将软件 dry-run 描述成真实机器人动作。

## 7. 官方资料与项目内证据

官方技术资料：

1. [Orange Pi 3B RK3566 用户手册](https://orangepi.net/wp-content/uploads/2024/11/OrangePi_3B_RK3566_user-manual_v1.6.pdf) — SoC、CPU、内存版本。
2. [Qwen3-0.6B 官方 Hugging Face 页面](https://huggingface.co/Qwen/Qwen3-0.6B) — 模型使用入口。
3. [Qwen 官方 llama.cpp 本地运行指南](https://github.com/QwenLM/Qwen3/blob/main/docs/source/run_locally/llama.cpp.md) — Qwen 与 GGUF/llama.cpp 工作流。
4. [llama.cpp 量化说明](https://github.com/ggml-org/llama.cpp/blob/master/tools/quantize/README.md) — HF 权重转 GGUF、再量化。
5. [llama-bench 文档](https://github.com/ggml-org/llama.cpp/tree/master/tools/llama-bench) 与 [perplexity 文档](https://github.com/ggml-org/llama.cpp/tree/master/tools/perplexity) — 微基准和量化质量辅助分析。
6. [llama-server 文档](https://github.com/ggml-org/llama.cpp/tree/master/tools/server) — CPU/量化模型、本机 HTTP API、结构化 JSON。
7. [sherpa-onnx 中文 streaming Zipformer](https://k2-fsa.github.io/sherpa/onnx/pretrained_models/online-transducer/zipformer-transducer-models.html)、[Linux ARM64 CPU 构建](https://github.com/k2-fsa/sherpa/blob/master/docs/source/onnx/install/linux.rst)、[离线中文 VITS TTS](https://k2-fsa.github.io/sherpa/onnx/tts/pretrained_models/vits.html)。
8. [ROS 2 官方 EOL 发行版列表](https://docs.ros.org/en/rolling/Releases/End-of-Life.html) — Foxy 生命周期风险。
9. [sherpa-onnx 的 RKNN 构建说明](https://github.com/k2-fsa/sherpa/blob/master/docs/source/onnx/rknn/install.rst) — 说明 NPU 路线是需要显式启用的独立构建。

项目内证据：

- Orange Pi 通用设备、网络和 SSH 操作保留在独立 `oragnepi-pratice` 仓库；本仓库不记录连接凭据或个人局域网地址。
- 当前视觉 dry-run 链路与安全边界：[perception-demo.md](perception-demo.md)、[robot-portability-assessment.md](robot-portability-assessment.md)。
- Orange Pi ROS 2 工作区和构建方式：[项目 README](../README.md)。
- 原始业务代码和 llama.cpp 的历史参考入口位于旧 `robot` 仓库；当前工作区是否仍对应同一提交，应在操作时以 `git rev-parse HEAD` 实测并记录。
- 另有[一手来源调研摘要](offline-agent-primary-source-research.md)，其中明确哪些是官方资料支持、哪些性能数据必须在 Orange Pi 实测。
