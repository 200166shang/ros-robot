# 阶段 C/D：虚拟底盘与人物跟踪闭环

记录日期：2026-09-25

## 目标

在没有轮子、电机和舵机的情况下，验证跟踪器的控制输出是否会改变底盘位姿，以及目标投影是否随位姿变化。虚拟运动严格使用 `/robot/sim/*` 话题，不把仿真命令映射到真实 `/cmd_vel`、PWM 或 MCU。

## 本阶段新增

- 新增 `robot_sim` ROS 包。纯数学模块实现差速底盘弧线积分、限幅与非有限数值拒绝；ROS 节点以明确的控制源仲裁手动/跟踪/导航速度，输入超时归零，并发布仿真状态、里程计、真值及 `sim_odom → sim_base_link` TF。
- 新增固定世界坐标的虚拟人物。由底盘位姿和针孔投影模型产生合成图像检测框，发布在 `/robot/sim/detections`，用于驱动原 `object_track` 节点；人物可以运行时启停。
- 新增 `base_sim_demo.launch.py` 与 `tracking_sim_demo.launch.py`。后者连接实际跟踪控制器、虚拟人物、仿真版 CommandAgent 和网页。
- 网页新增合成目标框、距离/方位/中心误差、底盘轨迹及启停控制；标题与状态明确标注 SYNTHETIC / 仿真，不依赖 C270 画面。
- 在 `simulation_mode` 下，相机启停被拒绝；跟踪输出固定只允许送入仿真速度话题。

## 在哪里运行

仿真节点与 ROS Foxy 环境仍在 Orange Pi 上：

```bash
cd /home/orangepi/code/ros-robot
source /opt/ros/foxy/setup.bash
source ros2_ws/install/setup.bash
export ROS_DOMAIN_ID=157
export ROS_LOCALHOST_ONLY=1
ros2 launch robot_bringup tracking_sim_demo.launch.py web_port:=18088 person_enabled:=true
```

网页需要从 Mac 经 SSH 隧道访问。网页服务和隧道职责分开：板端启动 ROS/网页；Mac 建立 `-L 本地端口:127.0.0.1:板端网页端口` 转发并用浏览器显示。Mac 的浏览器负责渲染，浏览器帧率不参与机器人运动控制。

## 实际验证结果

- `robot_bringup` 及其依赖的 11 个 ROS 包成功构建。
- 纯数学/投影单元测试共 11 项通过。
- 使用 `ROS_DOMAIN_ID=157` 和 `ROS_LOCALHOST_ONLY=1` 隔离运行；虚拟人物初始水平中心误差约 146 px。启动实际 `object_track` 后，误差约 2.7 秒收敛到 2 px 左右。
- 运行时关闭虚拟人物后，跟踪器检测到目标丢失并在超时内将角速度归零；停止跟踪后速度与控制源归零。
- `start_camera` 请求得到 HTTP 409 拒绝；节点列表未启动 USB 相机、RKNN 检测或语音节点。
- 实际/仿真话题核对：存在 `/robot/sim/tracking_cmd_vel`，没有由该链路发布到真实 `/cmd_vel` 的路径。
- 测试后 launch 进程组正常退出，未遗留对应进程或网页监听端口。

## 怎么理解结果

这是“闭环运动学仿真 + 合成检测输入”，比固定假框多验证了“机器人转动 → 目标图像位置变化 → 跟踪误差调整 → 底盘姿态变化”的链路。它证明了控制和任务逻辑，不证明 YOLO 的真实视觉精度、摄像头性能、电机响应、轮胎打滑、碰撞或真实环境导航。

网页 JavaScript 静态语法检查、API/ROS 隔离检查已通过；本轮 Mac 图形界面处于锁定状态，未做真实浏览器截图验收。画面是否适合演示需之后在浏览器打开后再作目视检查。

## 后续

阶段 E 采用独立 ROS 2 Jazzy/Nav2 loopback 环境，由 Mac Linux 虚拟机承载导航算法，不要求板端 Foxy 与 Jazzy 直接互通；两端通过版本化 HTTP 网关衔接。阶段 F 再使用 Nav2 loopback 的合成扫描与里程计，验证 AMCL/SLAM，并严格区分真值与估计值。
