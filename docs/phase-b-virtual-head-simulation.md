# Phase B: Virtual Head and Mac-rendered UI

Implementation record: 2026-09-25. Canonical checkout and builds are on
Orange Pi 3B at `/home/orangepi/code/ros-robot`; the Mac is the browser,
Codex, and Obsidian workstation.

Related plan: [robot capability and simulation roadmap](robot-capability-simulation-roadmap.md).

## Goal and boundary

Run the head action/control path without a physical servo, PWM, GPIO, camera,
NPU, Qwen process, microphone, or speaker. The Orange Pi publishes a fixed
simulated pose and serves the page/assets over its loopback-only web server.
The Mac browser performs the visible sprite animation and pose display through
the existing SSH port-forwarding workflow. The Mac does not need ROS installed
or DDS access.

This is a software simulation, not servo acceptance, robot dynamics, or a
physical robot model.

## What changed

- `robot_interfaces/action/HeadMotion.action` provides a fixed-name goal,
  simulated result and feedback. `robot_interfaces/msg/HeadState.msg` reports
  backend, motion, phase, expression, pose, simulation flag, and motion ID.
- New `robot_head` package serves `/robot/head_motion` and publishes
  `/robot/head/state` at 2 Hz. Actions interpolate fixed pitch/yaw waypoints,
  publish feedback at 10 Hz, reject names outside the catalog, and support
  cancellation. It only permits `backend=sim`; it has no hardware API imports.
- `robot_head/catalog.py` is the single source of truth for 29 fixed action
  names. The action profiles stay within the original controller's conservative
  software bounds (pitch 65–120°, yaw 50–130°); those values are simulated and
  do not command a servo.
- `command_agent` forwards only catalogued head actions through a ROS Action
  client, returns a simulation-labelled result, and exposes `head_cancel`.
  Model functions must exactly match an allowlisted name and must not include
  model-supplied parameters. The Qwen bridge's existing default remains
  `enable_commands=false`; the full demo explicitly enables the reviewed
  allowlist.
- The browser page now has a clearly labelled SIM panel, fixed action selector,
  quick actions, pose telemetry, state text, and original emotion sprites.
  Browser requests use `/api/head/state`, `/api/head/catalog`, and
  `/api/head/assets`. The browser polls state every 500 ms and renders the
  image/translation locally.
- The original sprite tree contains 235 JPG files. The API serves the five
  selected expressions (100 animation frames total); for “兴奋” it selects
  only the loop folder `兴奋_2可循环动作`, not the entrance/return sequences.
- `head_sim_demo.launch.py` is a no-peripheral launch containing only the
  virtual head, command Agent, and web server. The web port can be overridden.
  It binds to `127.0.0.1`, not a public interface.
- The existing full tracking launch also starts the virtual head and Agent;
  its Qwen bridge enables only the reviewed action allowlist.

Important source locations:

- `ros2_ws/src/robot_head/robot_head/catalog.py`
- `ros2_ws/src/robot_head/robot_head/head_motion_node.py`
- `ros2_ws/src/robot_interfaces/action/HeadMotion.action`
- `ros2_ws/src/robot_interfaces/msg/HeadState.msg`
- `ros2_ws/src/robot_agent/robot_agent/command_agent.py`
- `ros2_ws/src/web_video_server/web_video_server/web_video_node.py`
- `ros2_ws/src/web_video_server/templates/index.html`
- `ros2_ws/src/robot_bringup/launch/head_sim_demo.launch.py`

## Run only the virtual-head demo

On the Orange Pi, in a board terminal:

```bash
cd /home/orangepi/code/ros-robot
source /opt/ros/foxy/setup.bash
source ros2_ws/install/setup.bash
export ROS_DOMAIN_ID=157
export ROS_LOCALHOST_ONLY=1
ros2 launch robot_bringup head_sim_demo.launch.py web_port:=8080
```

The dedicated ROS domain and localhost-only discovery keep this simulation
separate from any default-domain robot nodes. This launch intentionally does
not start the camera, detector, Qwen, or voice nodes. Therefore the video area
will wait for frames and the chat area will report that Qwen is unavailable;
use the virtual-head panel for this demo.

On the Mac, from a local checkout of `ros-robot`, in a second terminal:

```bash
./scripts/open-ui.sh
```

Keep both terminals open. The Mac tunnel opens
`http://127.0.0.1:18081/` and forwards to the board's loopback port 8080.
Click “执行仿真” or one of the quick actions (for example, “点头”). Use
“停止” to test cancellation. Press Ctrl-C in the Mac terminal to stop only the
SSH tunnel, and Ctrl-C in the board terminal to stop the ROS launch.

The default port is 8080. To avoid a board-side port conflict, choose an
available port, e.g. `web_port:=18088`, and set
`DEMO_WEB_PORT=18088` when starting `open-ui.sh` on the Mac.

For direct ROS inspection, use a second Orange Pi terminal with the same
`ROS_DOMAIN_ID` and `ROS_LOCALHOST_ONLY` values:

```bash
ros2 action list
ros2 action send_goal -f /robot/head_motion \
  robot_interfaces/action/HeadMotion "{motion: head_nod}"
ros2 topic echo /robot/head/state
```

Expected evidence is a `sim` backend, `simulated: true`, a motion ID, moving
feedback, and a completed/cancelled state. These reports describe the virtual
head only.

## Verification performed

All commands below ran on Orange Pi unless explicitly stated. No real
peripheral, model inference, recording, or audio playback was started.

| Check | Result |
|---|---|
| Python unit tests | 13 catalog and Agent-adapter tests passed |
| Python syntax / XML manifests / `git diff --check` | Passed |
| ROS build | `robot_interfaces`, `robot_head`, `robot_agent`, `web_video_server`, and `robot_bringup` built successfully |
| Isolated action probe | Unknown action rejected; `head_nod` completed; `head_dance` accepted cancellation; simulated state topic observed |
| Head-only launch probe | Only `/robot_head_motion`, `/command_agent`, and `/web_video_server` appeared; camera, detector, Qwen, and voice nodes were absent |
| HTTP end-to-end | Page and health endpoints returned; 29 actions and 100 frames listed; a static JPEG was served; HTTP `head_nod` traversed Agent → Action → completed state; unknown HTTP command returned 400 |
| Browser script syntax | Inline JavaScript passed Mac Node `--check` |

The isolated ROS probes used `ROS_DOMAIN_ID=157` and
`ROS_LOCALHOST_ONLY=1`; temporary nodes were stopped afterward. A headless
Chromium `--dump-dom` attempt was not counted as a pass: the page's MJPEG
stream intentionally stays open when no camera frames arrive, so Chromium
waited for page load. A real Mac-browser visual check remains to be done when
the user opens the tunnel.

## What is not verified

- No real Qwen output was generated. Unit tests verify exact function mapping,
  but real model adherence to the head-action format still needs a live-model
  check.
- No camera/NPU/audio node was started. In the head-only launch, the other
  dashboard sections are intentionally unavailable.
- No physical servo was present or driven. The new waypoint motions are a
  simulation behavior; the original `head_nod`, `head_shake`, and
  `head_dance` functions only changed the expression and did not themselves
  implement servo motion. This work must not be described as migrated,
  hardware-tested servo control.
- The browser paints the emotion sprite and simulated pose on the Mac, but
  this is not a 3D articulated model or physical dynamics.

## Next step

Continue the roadmap with Phase C: a hardware-free differential-drive base
backend with bounded `cmd_vel`, stop timeout, integrated pose/odometry, and
browser-rendered map/trajectory. Keep it separate from real motor topics and
add no navigation stack until that software-in-the-loop loop is observable.
