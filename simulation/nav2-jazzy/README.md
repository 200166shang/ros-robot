# Nav2 Jazzy loopback (Mac Linux VM)

This experiment runs real ROS 2 Jazzy/Nav2 navigation actions in the official Nav2 ideal loopback simulator. It does not install Jazzy or Nav2 onto the Orange Pi Foxy system. The simulator has no inertia, collisions, wheels, or physical sensor model; use it to validate navigation action/state/API wiring, not real-world safety.

The Mac browser renders the map and trajectory. The ARM64 Linux VM runs Nav2, the loopback simulator, and a small HTTP gateway. The gateway accepts only validated location IDs; it does not accept arbitrary coordinates.

## Start on the Mac

Start only the dedicated Colima profile. This leaves the default Docker profile unchanged:

```bash
colima start ros-nav2 --cpus 2 --memory 4 --disk 30 --arch aarch64 --vm-type vz --activate=false
```

The container build needs an HTTP proxy reachable from inside Colima when the package mirrors are not directly reachable. Set the proxy used by the current Colima network, then start the service from a Mac checkout of this repository:

```bash
cd simulation/nav2-jazzy
export APT_HTTP_PROXY=http://192.168.5.2:7890
./scripts/nav2-up.sh
```

The entry point accepts three explicit profiles:

```bash
./scripts/nav2-up.sh ideal  # known map and ideal truth pose; lowest complexity
./scripts/nav2-up.sh amcl   # known map + AMCL estimated localization
./scripts/nav2-up.sh slam   # online map built by SLAM Toolbox from virtual scans
```

In the `slam` profile, the static sandbox map is private to the loopback sensor
generator so it can synthesize LaserScan readings. Nav2 does not subscribe to
that ground-truth map: SLAM Toolbox publishes the estimated `/map`. This is
software SLAM in a deterministic virtual world, not an unknown physical room.
The loopback simulator publishes the ROS clock from system time; Nav2, SLAM,
and the gateway use that clock. Letting the clock producer use simulated time
would deadlock startup before the first `/clock` message.
The first SLAM map covers only the area observed from the starting scan. A
named goal outside the currently mapped free space is intentionally withheld;
drive the virtual robot in the simulator before testing navigation. In this
profile the loopback simulator receives no Nav2 bond heartbeat, so its
lifecycle manager still configures/activates SLAM Toolbox but does not enable
the bond watchdog. Health is instead checked through the generated map, initial
pose transform, and NavigateToPose action readiness. This is a simulator
specific exception, not a setting for a physical Nav2 robot.

For the included sandbox, one short virtual drive along its clear corridor is
enough to reveal both named destinations. From the Mac, with `slam` running and
no active navigation task, execute this once:

```bash
docker --context colima-ros-nav2 exec ros-robot-nav2-loopback bash -lc '
  source /opt/ros/jazzy/setup.bash
  timeout 8s ros2 topic pub --rate 10 /cmd_vel geometry_msgs/msg/Twist \\
    "{linear: {x: 0.15}}" >/dev/null 2>&1
  ros2 topic pub --once /cmd_vel geometry_msgs/msg/Twist "{}" >/dev/null 2>&1
'
curl --noproxy '*' -fsS http://127.0.0.1:18091/api/v1/navigation/locations
```

This publishes velocity only inside the isolated Colima container; it does not
reach ROS on the Orange Pi. The loopback drive is idealized, with no collision
or inertia model. The board-side `--navigation-sim` preflight requires both
`goal_a` and `goal_b` to be present before it will start.

The script builds with the isolated Docker context `colima-ros-nav2`, publishes the UI only to Mac loopback `127.0.0.1:18091`, and waits for Nav2/map/initial-pose health. Open:

```text
http://127.0.0.1:18091/
```

No RViz or Gazebo window runs. The HTML canvas is rendered by the Mac browser. Nav2 computations are in the Linux VM.

## API

- `GET /healthz`: map, initial pose, and NavigateToPose readiness.
- `GET /api/v1/navigation/map`: occupancy grid for the browser.
- `GET /api/v1/navigation/locations`: named locations validated against free map cells.
- `GET /api/v1/navigation/state`: pose, path, active task, backend/simulation label.
- `POST /api/v1/navigation/tasks` with `{"location_id":"goal_a"}`: submit a real Nav2 NavigateToPose action.
- `GET /api/v1/navigation/tasks/{task_id}`: task status.
- `POST /api/v1/navigation/tasks/{task_id}/cancel`: cancel the action.

Only one task can be active. The HTTP server has no login layer, so the container port is deliberately published on Mac loopback only. Do not change it to `0.0.0.0` for network access.

The first validated location is the initial pose. Other named positions come from `ros2_ws/src/robot_nav2_gateway/config/locations.json`; the gateway checks occupancy and clearance in the loaded map before exposing them. The API never accepts raw goal coordinates.

## Optional Orange Pi Agent access

Foxy and Jazzy do not share DDS in this architecture. An SSH reverse tunnel can expose the Mac loopback API to the Orange Pi on its own loopback port, without opening either service to the LAN:

```bash
# Run on Mac; keep the terminal open while the Agent is using Nav2.
ssh -N -o ExitOnForwardFailure=yes -o HostKeyAlias=192.168.3.100 -R 127.0.0.1:18092:127.0.0.1:18091 orangepi-ts
```

The Orange Pi-side client, when enabled, calls `http://127.0.0.1:18092`. The reverse tunnel is separate from starting board services. It does not publish ROS topics between distros.

For the full text prototype, use `scripts/open-nav-sim.sh` on the Mac. It
forwards the board chat page and creates the reverse API tunnel in one SSH
session. Start the tunnel first; then, on the Orange Pi, run:

```bash
cd /home/orangepi/code/ros-robot
./scripts/run-demo.sh --navigation-sim
```

This profile starts the local Qwen service and a ROS Agent with only four
fixed Nav2 functions: `navigate_to_goal_a`, `navigate_to_goal_b`,
`cancel_navigation`, and `navigation_status`. It does not start the camera,
RKNN detector, microphone, or any hardware driver. The Nav2 API client accepts
only loopback HTTP and the two fixed location IDs. A submitted task is not
reported as arrived; task progress and terminal status remain visible in the
Nav2 browser page. To test the command path without Qwen, publish one approved
command on `/agent/command` after launching the profile.

## Stop

Stop the service first, then stop only the dedicated VM to release Mac memory. Images remain cached:

```bash
./scripts/nav2-down.sh
colima stop ros-nav2
```

Do not run `colima delete` unless intentionally removing the experiment profile and its cached data.
