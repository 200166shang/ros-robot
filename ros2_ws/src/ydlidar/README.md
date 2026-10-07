# YDLIDAR scan visualization / YDLIDAR 雷达可视化

[简体中文](#简体中文) | [English](#english)

## 简体中文

驱动将雷达扫描发布为 `sensor_msgs/msg/LaserScan`，使用相对话题名
`scan`。默认配置下，话题为 `/scan`，坐标系为 `laser_link`。RViz2 和
浏览器视图都读取同一话题；它们不会启动第二个雷达驱动，也不会再次连接
雷达串口。

### 在 Orange Pi 上使用 RViz2

如果尚未安装 RViz2：

```bash
sudo apt install ros-foxy-rviz2
```

在一个终端中加载 ROS 和工作空间，并启动驱动：

```bash
source /opt/ros/foxy/setup.bash
source ~/code/ros-robot/ros2_ws/install/setup.bash
ros2 launch ydlidar ydlidar.launch.py
```

在另一个已加载相同环境的终端中打开预设视图：

```bash
rviz2 -d "$(ros2 pkg prefix ydlidar --share)/config/ydlidar.rviz"
```

预设将固定坐标系设为 `laser_link`，并显示 `/scan`。当前扫描数据就在雷达
坐标系下，因此这个独立视图不需要额外的 TF 发布器。扫描角度遵循 ROS 约定：
零弧度朝向 +X，正角度绕 +Z 轴逆时针旋转。

### 在 Mac 浏览器中使用 Foxglove

ROS 2 Foxy 早于当前 Foxglove Bridge 二进制包支持的发行版；旧版 ROS 2 需要
从源码构建该 Bridge。这里使用 Foxy 的 ROS `rosbridge_server`，并通过
Foxglove 现有的浏览器客户端查看数据。Foxglove 支持通过 Rosbridge 接收
ROS 2 消息，包括 `sensor_msgs/msg/LaserScan`。

保持驱动运行，在 Orange Pi 的另一个终端安装并启动 WebSocket 桥接：

```bash
sudo apt install ros-foxy-rosbridge-server
source /opt/ros/foxy/setup.bash
source ~/code/ros-robot/ros2_ws/install/setup.bash
ros2 launch rosbridge_server rosbridge_websocket_launch.xml
```

桥接默认监听 `9090` 端口。请确保 Mac 和 Orange Pi 在同一局域网内可互相访问，
并允许两者之间的 TCP `9090` 端口。运行 `hostname -I` 可查看 Orange Pi 的局域网
地址。

在 Mac 浏览器打开 [Foxglove](https://app.foxglove.dev/)，选择
**Open connection** → **Rosbridge**，并输入：

```text
ws://<ORANGE_PI_IP>:9090
```

Foxglove 的直接实时连接目前需要 Developer seat（开发者席位）。连接后添加 **3D** 面板，选择
`/scan` 作为 LaserScan 话题，并将固定坐标系设为 `laser_link`。面板会显示已启动
的驱动发布的实时扫描。

启动可视化前，可先确认话题和坐标系：

```bash
ros2 topic hz /scan
ros2 topic echo /scan --once --field header.frame_id
```

如果连接失败，请检查桥接是否正在运行，以及 Mac 是否能通过 TCP `9090` 访问
Orange Pi。

## English

The driver publishes radar scans as `sensor_msgs/msg/LaserScan` on the relative
topic `scan`. With the default configuration, the topic is `/scan` and the frame
is `laser_link`. RViz2 and the browser view both read this same topic; neither
starts another radar driver or opens a second serial connection.

### RViz2 on the Orange Pi

Install RViz2 if it is not already present:

```bash
sudo apt install ros-foxy-rviz2
```

In one terminal, source ROS and the workspace and start the driver:

```bash
source /opt/ros/foxy/setup.bash
source ~/code/ros-robot/ros2_ws/install/setup.bash
ros2 launch ydlidar ydlidar.launch.py
```

In another terminal with the same setup sourced, open the saved RViz2 view:

```bash
rviz2 -d "$(ros2 pkg prefix ydlidar --share)/config/ydlidar.rviz"
```

The view uses `laser_link` as its fixed frame and displays `/scan`. The scan is
expressed in the lidar frame, so no additional TF publisher is needed for this
standalone view. Scan angles follow the ROS convention: zero radians points
along +X and positive angles rotate counterclockwise around +Z.

### Foxglove in a Mac browser

ROS 2 Foxy predates the distributions supported by current Foxglove Bridge binary
packages; older ROS 2 distributions require building that Bridge from source.
This setup uses Foxy's ROS `rosbridge_server` package with Foxglove's existing
browser client. Foxglove supports ROS 2 messages over Rosbridge, including
`sensor_msgs/msg/LaserScan`.

Keep the driver running. On the Orange Pi, install and start the WebSocket bridge
in another terminal:

```bash
sudo apt install ros-foxy-rosbridge-server
source /opt/ros/foxy/setup.bash
source ~/code/ros-robot/ros2_ws/install/setup.bash
ros2 launch rosbridge_server rosbridge_websocket_launch.xml
```

The bridge listens on port `9090` by default. Make sure the Mac and Orange Pi can
reach each other on the same LAN, and allow TCP port `9090` between them. Run
`hostname -I` to find the Orange Pi's LAN address.

On the Mac, open [Foxglove](https://app.foxglove.dev/) in a browser, choose
**Open connection** → **Rosbridge**, and enter:

```text
ws://<ORANGE_PI_IP>:9090
```

Foxglove currently requires a Developer seat for direct live connections. After
connecting, add a **3D** panel, choose `/scan` as its LaserScan topic, and set the
fixed frame to `laser_link`. The panel will display live scans from the running
driver.

Before opening either visualizer, confirm the topic and frame:

```bash
ros2 topic hz /scan
ros2 topic echo /scan --once --field header.frame_id
```

If the connection fails, check that the bridge is running and that the Mac can
reach the Orange Pi on TCP port `9090`.
