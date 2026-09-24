# `~/code/robot` 到 Orange Pi 3B 的能力移植评估

> 本文是 2026-09-21 的阶段性评估记录。当前 ROS 2 解码链路以 OpenCV 为主；本文中早期的 MPP/RGA 方案描述不应当作现行实现。最新运行说明见 [perception-demo.md](perception-demo.md)。

> 迁移状态（2026-09-21）：方案 1–4 的安全演示子集已落地到本仓库
> `ros2_ws/src`，并在 Orange Pi 3B 实机完成 USB 摄像头、ROS 2 图像、RK3566
> NPU YOLOv6、人物检测框、dry-run 跟踪和文本 Agent 联调。操作手册见
> [perception-demo.md](./perception-demo.md)。真实底盘、串口、雷达和 Nav2 仍按本文边界不接入。

## 结论

当前最可靠、最有硬件价值的主线是：

```text
Logitech C270
  -> ROS 2 USB Camera（MJPEG）
  -> MPP/RGA 硬件解码
  -> RKNN YOLOv6（RK3566 NPU）
  -> 目标跟踪 dry-run
  -> 发布安全隔离的速度建议话题
```

这条链路不依赖电机、MCU 串口或激光雷达，能在现有设备上形成完整闭环：镜头前出现人物后，系统发布检测框、带标注的视频和建议角速度；人向左、向右移动时，可以从视频和 ROS 2 话题同时验证跟踪逻辑。

不建议现在优先移植真实底盘控制、YDLidar、Nav2 实车导航、头部舵机或 LCD，因为缺少相应硬件时只能做模拟，不能满足“能力移植可靠、真正跑通”的目标。

## 已核实的目标机条件

| 项目 | 实机结果 | 对移植的意义 |
|---|---|---|
| 主机 | Orange Pi 3B，RK3566，aarch64，4 GB | 与仓库 RKNN 模型目标一致 |
| 系统与 ROS | Ubuntu 20.04，ROS 2 Foxy | 原 ROS 1 包需要改为 ament/rclcpp/rclpy |
| 摄像头 | Logitech C270，`/dev/video0` | 可直接采集 |
| 视频格式 | MJPEG 1280×720 @ 30 fps | 与 `usb_camera` 的 MJPEG 输入设计一致 |
| 摄像头麦克风 | USB Audio，16 kHz 单声道采集成功 | 后续可做本地 ASR |
| MPP/RGA | 运行库及开发包已安装 | 可验证 JPEG 硬解码和硬缩放 |
| NPU | RKNPU 0.9.6 驱动已加载，600 MHz | 可运行 RKNN 推理 |
| RKNN Runtime | 1.4.0 | 与模型编译器 1.4.0 匹配 |
| ROS 图像依赖 | `cv_bridge`、`image_transport` 尚未安装 | 构建前需安装或移除未使用依赖 |

## 源码能力地图

| 模块 | 当前状态 | 硬件依赖 | 建议 |
|---|---|---|---|
| `ros2_ws/src/usb_camera` | 已有 ROS 2 版本，但尚未在板上构建 | USB 摄像头 | 第一批修复并验证 |
| `ros2_ws/src/img_decode` | 已有 ROS 2 版本，含 MPP/RGA | RK3566 MPP/RGA | 第一批修复并验证 |
| `src/ai_msgs` | ROS 1 自定义检测消息 | 无 | 改为 ROS 2 `rosidl`，作为视觉接口 |
| `src/rknn_yolov6` | ROS 1，模型和推理代码完整 | RK3566 NPU | 第二批移植，成功概率高 |
| `src/object_track` | ROS 1，图像+检测+可选雷达 | 检测结果；雷达可禁用 | 第三批移植为 dry-run 跟踪 |
| `web_controller.py` | ROS 1 Flask 控制面板 | 无；电机命令可只观察 | 精简后改为 ROS 2 控制台 |
| `src/monitor` | ROS 1 系统/进程监控 | 无 | 可移植，优先级低于视觉 |
| `test11_description` | ROS 1 URDF/Xacro | 无 | 可移植并在 Mac RViz2 显示 |
| `prototype_nav_cpp` | 独立 C++17 教学模拟器 | 无 | 可直接在 ARM64 跑，但不是实车导航 |
| `offline-agent/voice` | sherpa-onnx 源码存在 | 摄像头麦克风 | 可行，但模型是 LFS 指针，需补齐 |
| `offline-agent/tts` | 本地 TTS 源码存在 | 音频输出 | 可行，但模型是 LFS 指针，需补齐 |
| `offline-agent/llamacpp-ros` | ROS 1，预编译库为 x86-64 | 大内存/CPU、GGUF 模型 | 不能直接迁移，建议后置 |
| `src/base_control` | ROS 1 串口底盘控制 | MCU、串口、电机、编码器 | 当前不做真实验收 |
| `src/ydlidar` | ROS 1 雷达驱动 | YDLidar、串口 | 当前不做 |
| `src/robot_navigation` | ROS 1 move_base | 雷达、底盘、里程计 | 不能直接等价迁移为 Nav2 |
| `src/shm_transport` | ROS 1 自定义共享内存 | 无 | ROS 2 下不建议原样移植 |
| 舵机/LCD/MCU | PWM、SPI、STM32 固件 | 对应外设 | 当前不做 |

## 可真正跑通的方案

### 方案 1：ROS 2 连续视频链路

目标链路：

```text
/dev/video0
  -> usb_camera:/image_raw/compressed
  -> img_decode:/camera/image_raw
  -> 统计节点/保存帧/远程显示
```

现有 ROS 2 代码不是直接构建即可用，至少要先处理这些问题：

- `usb_camera` 没有使用 RKNN，却错误链接 `rknn_api` 和 `rknnrt`；应删除虚假依赖。
- `usb_camera` 没有实际使用 `cv_bridge` 和 `image_transport`，可从主目标移除，减少安装面。
- V4L2 缓冲区结构没有完整初始化，失败路径可能释放未映射内存；应改成 RAII。
- 当前驱动在重新入队缓冲区后才复制帧，有被摄像头覆盖的竞态；应先复制再归还缓冲区。
- 测试订阅器写死了错误话题 `/jpeg_image`，应参数化为 `/image_raw/compressed`。
- 两个包缺少 ROS 2 launch 文件和自动化验收脚本。
- `img_decode` 应检查 MPP/RGA 初始化结果，失败时可选回退到 OpenCV，而不是继续运行。

验收标准：

- 连续运行至少 10 分钟，不退出、不持续增长内存。
- `/image_raw/compressed` 和 `/camera/image_raw` 都有稳定频率。
- 原始帧分辨率、编码和时间戳正确。
- 保存出的帧能正常打开，颜色顺序正确。
- 断开并重新插入摄像头后，节点能自动恢复或明确退出并由 launch 重启。

### 方案 2：RK3566 NPU 实时目标检测

目标链路：

```text
/camera/image_raw
  -> rknn_yolov6
  -> /ai_msg_det
  -> /camera/image_det
```

这是最值得从 ROS 1 移植的模块。仓库内 `yolov6n_85.rknn` 明确包含：

- target：`rk3566`
- compiler：RKNN 1.4.0
- 输入布局：NHWC/int8
- 三路 YOLO 输出

目标机上的 RKNN Runtime 同为 1.4.0，NPU 驱动已经加载，因此模型/运行时/芯片三者匹配。

移植内容：

- 把 `ai_msgs/Det.msg`、`Dets.msg` 改为 ROS 2 interface 包。
- 把 `roscpp` publisher/subscriber、参数、日志和时间戳改为 `rclcpp`。
- 保留 RKNN 推理、OpenCV 预处理和 YOLO 后处理算法，不重写已验证的核心算法。
- 修复当前“只有检测图像有订阅者才启动输入订阅”的逻辑；检测消息有订阅者时也必须推理。
- 增加离线图片测试，再接实时摄像头，便于区分模型错误和 ROS 图像链路错误。

验收标准：

- 仓库自带 `test.jpg` 能稳定输出检测结果。
- 摄像头画面中出现人时，`/ai_msg_det` 产生 `person` 框。
- `/camera/image_det` 的框位置与人物一致。
- 记录端到端 FPS、NPU 频率、CPU 和内存；目标不是固定 30 fps，而是无积压、低延迟地处理最新帧。

### 方案 3：无电机“人物跟随”闭环

目标链路：

```text
检测框 + 图像
  -> object_track
  -> /camera/image_det_track
  -> /tracking/cmd_vel_safe
```

这可以验证真正的跟随决策，但不把速度发给真实底盘：

- `control_linear=false`，没有雷达时线速度固定为 0。
- `enable_lidar=false`，不创建雷达订阅，也不等待雷达到相机的 TF。
- 输出改到隔离话题 `/tracking/cmd_vel_safe`，避免未来接入底盘后误动作。
- 增加 `dry_run`、目标丢失超时和停止消息。
- 修复源码中硬编码 `0.01`、`0.5` 而没有使用 `kp_angular`、`kp_linear` 参数的问题。
- 不修改输入的共享图像消息，先 clone 后绘制。

验收动作：人在画面左侧、中央、右侧移动。预期线速度始终为 0；角速度符号随人物左右变化，人物居中时接近 0；人物离开后立即发布 0。

### 方案 4：ROS 2 Agent 的安全软件子集

不建议一开始搬运整个 `src/agent`。应先提取一个纯 ROS 2 的函数执行器，只保留：

- 开启/关闭摄像头。
- 开启/关闭 dry-run 跟踪。
- 查询跟踪状态。
- 发布测试命令并返回结构化结果。

这样可以通过文本话题或命令行模拟 LLM function call，完整验证“意图 -> 函数执行 -> ROS 2 能力切换”，而不依赖 API Key、云服务、舵机、电机、LCD 或导航。

之后可按两条路线扩展：

1. 云端 Agent：现有 DashScope ASR/LLM/TTS 代码可保留业务逻辑，只把 `rospy` 接口改为 `rclpy`。它依赖网络、账号和密钥，不能算纯离线能力。
2. 离线语音：C270 的 USB 麦克风已实测可录制 16 kHz 单声道，sherpa-onnx 支持 aarch64；但仓库里的 ONNX 文件目前只有约 132 字节，是 Git LFS 指针，必须先拉取真实模型。

### 方案 5：系统监控与 URDF

这两项都能真实运行，但展示价值低于视觉：

- `monitor`：核心是读取 `/proc`，与 ROS 版本无关；把消息/服务改为 ROS 2，并把 rosbag1 改为 rosbag2 即可。可用于观察视觉节点 CPU、内存、网络和进程状态。
- `test11_description`：Xacro、URDF、mesh 可复用；改为 ROS 2 launch 和 `robot_state_publisher`。Orange Pi 发布 TF，Mac 上 RViz2 显示模型，可避免板端 GUI 压力。

### 方案 6：导航算法教学模拟

`prototype_nav_cpp` 是独立 C++17 程序，不依赖 ROS，可直接在 Orange Pi 编译运行并生成地图及轨迹 CSV。它可以验证 A*、简化 DWA、障碍重规划和里程计漂移的概念，但不能当作 Nav2 或实车导航验收。

## 当前不应承诺跑通的模块

### 底盘与串口

`base_control` 需要 `/dev/ttyS2`、STM32、电机和编码器反馈。虽然源码有“串口不存在时填零”的模拟分支，但这不能验证 PID、帧协议、方向、急停或里程计。应等硬件接入后再移植，并先实现虚拟串口协议测试。

### YDLidar 与真实导航

`ydlidar` 需要真实串口雷达。`robot_navigation` 使用 ROS 1 `move_base`、AMCL、gmapping 和对应插件，迁移到 ROS 2 应改用 Nav2/SLAM Toolbox，不是简单替换 API。没有雷达、底盘和 odom 时只能跑仿真，不能作为真实能力验收。

### 本地 llama.cpp Agent

当前 `llamacpp-ros/lib` 内的动态库是 x86-64，CMake 还硬编码了 x86-64 的 curl 路径；仓库中也没有可对话的 GGUF 权重。因此必须在 Orange Pi 重新编译 llama.cpp、补模型、改 ROS 2 接口。4 GB 内存只适合很小的量化模型，性能和体验需单独评估，不能列入第一批可靠交付。

### 本地 TTS/ASR 模型

SummerTTS 的 `single_speaker_fast.bin` 和 sherpa-onnx 的模型文件当前都是 Git LFS 指针，不是真实权重。源码具有 ARM64 可行性，但在模型补齐前不能声称可运行。

### `shm_transport`

这是 ROS 1 定制共享内存通道。ROS 2 已有 DDS、进程内通信和可组合节点机制。第一阶段原样移植会增加维护面，并可能破坏标准工具链，应先用标准 ROS 2 消息完成性能测量，确有瓶颈再优化。

## 推荐实施顺序

1. 修复并验收 ROS 2 `usb_camera + img_decode`。
2. 移植 `ai_msgs + rknn_yolov6`，先离线图片、后实时视频。
3. 移植 `object_track` 的无雷达 dry-run 模式。
4. 增加一个总 launch、健康检查和 10 分钟稳定性测试。
5. 精简移植 Agent 函数执行器，用文本命令开关跟踪。
6. 再选择监控、URDF 或离线 ASR；不要同时铺开。

第一阶段完成后，真正可演示的能力应是：浏览连续视频、看到实时人物检测框、观察人物左右移动产生的跟踪角速度建议、通过 Agent 文本命令启停整条视觉跟踪链路。这个范围与现有硬件匹配，也为以后接入电机和雷达保留标准 ROS 2 接口。
