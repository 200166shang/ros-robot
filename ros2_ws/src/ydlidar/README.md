# YDLIDAR scan visualization

The driver publishes the radar scan as `sensor_msgs/msg/LaserScan` on the
relative `scan` topic. The launch file uses the node namespace at runtime; in
the default setup the topic is `/scan` and its frame is `laser_link`.
RViz2 and the browser view below both read this same topic. They do not start
another radar driver or open another serial connection.

## RViz2 on the Orange Pi

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

The view uses `laser_link` as its fixed frame and displays `/scan` as a
LaserScan. This scan is expressed in the lidar frame, so no additional TF
publisher is needed for this standalone view. The driver's scan angles follow
the ROS convention: zero radians points along +X and positive angles rotate
counterclockwise around +Z.

## Foxglove in a Mac browser

Foxy is older than the distributions supported by the current Foxglove Bridge
binary packages. Use Foxy's ROS `rosbridge_server` package and Foxglove's
existing browser client instead. The client supports ROS 2 messages over
Rosbridge, including `sensor_msgs/msg/LaserScan`.

On the Orange Pi, install the Foxy bridge package:

```bash
sudo apt install ros-foxy-rosbridge-server
```

Keep the driver running, then start the WebSocket bridge in another terminal:

```bash
source /opt/ros/foxy/setup.bash
source ~/code/ros-robot/ros2_ws/install/setup.bash
ros2 launch rosbridge_server rosbridge_websocket_launch.xml
```

The bridge listens on port `9090`. Make sure the Mac and Orange Pi can reach
each other on the same LAN, and allow TCP port `9090` between them. Find the
Orange Pi's LAN address with `hostname -I`.

On the Mac, open [Foxglove](https://app.foxglove.dev/) in a browser, choose
**Open connection** → **Rosbridge**, and enter:

```text
ws://<ORANGE_PI_IP>:9090
```

Foxglove currently requires a Developer seat for direct live connections.

After connecting, add a **3D** panel, choose `/scan` as its LaserScan topic,
and set the fixed frame to `laser_link`. The panel will show the live scan
from the already-running driver. If the connection fails, check that the
bridge is running and that the Mac can reach the Orange Pi on TCP port `9090`.

## Quick checks

With the driver running, confirm the topic and frame before opening either
visualizer:

```bash
ros2 topic hz /scan
ros2 topic echo /scan --once --field header.frame_id
```
