# ROS Robot — Orange Pi 3B

This repository contains the ROS 2 modules migrated from the XiaoMo robot project and validated on Orange Pi 3B. The Orange Pi checkout is the development source of truth; the general Orange Pi setup and SSH playbook remains in the separate `oragnepi-pratice` repository.

The ROS workspace is `ros2_ws/`. It contains the application packages listed below; the tutorial-only `cpp_pubsub` talker/listener demo is intentionally excluded.

- `robot_bringup`, `robot_interfaces`, `robot_agent`, `robot_voice`
- `usb_camera`, `img_decode`, `rknn_yolov6`, `object_track`, `web_video_server`

## Build on Orange Pi

The board uses Ubuntu 20.04, ROS 2 Foxy and ARM64. The Rockchip runtime library is installed on the board. Its SDK header is proprietary, so it is supplied locally and is not part of this repository.

```bash
bash --noprofile --norc <<'BASH'
cd /home/orangepi/code/ros-robot/ros2_ws
source /opt/ros/foxy/setup.bash
colcon --log-base log build --base-paths src \
  --build-base build --install-base install --executor sequential \
  --cmake-args -DRKNN_API_INCLUDE_DIR=/home/orangepi/sdk/rknn/include
source install/setup.bash
BASH
```

Run the unit tests after building:

```bash
bash --noprofile --norc <<'BASH'
cd /home/orangepi/code/ros-robot/ros2_ws
source /opt/ros/foxy/setup.bash
colcon --log-base log test --base-paths src --build-base build --install-base install
colcon test-result --test-result-base build --verbose
BASH
```

The build only compiles packages; it does not open the camera or start robot nodes.

## Start the end-to-end demo

From a Mac terminal, connect to the Orange Pi over Tailscale using the current board
Tailscale IP (replace the example with the current address):

```bash
ssh -o HostKeyAlias=192.168.3.100 orangepi@<BOARD_TAILSCALE_IP>
cd /home/orangepi/code/ros-robot
./scripts/run-demo.sh
```

The board-side script checks local models and ports, starts Qwen's `llama-server` if
needed, then runs the ROS launch in the foreground. It reuses a healthy Qwen server
and never kills a server it did not start. The default acceptance probe uses a fixed
WAV and synthetic detector input; tracking remains `dry_run=true`. To check setup
without starting Qwen, ROS nodes, or the camera, run
`./scripts/run-demo.sh --check-only`.

For the browser video UI, configure the `orangepi-ts` SSH alias on the Mac and run
`scripts/open-ui.sh` from a Mac checkout in a second terminal.
It only creates the tunnel; it does not launch another ROS stack. See
[the demo guide](docs/perception-demo.md). The UI is not the LLaMA Factory WebUI.

## Local-only assets

Model weights, Rockchip SDK headers, Sherpa-ONNX assets and voice fixtures are not stored in Git. Their expected paths, provenance and checksums are in [docs/local-assets.md](docs/local-assets.md). The detector launch accepts `model_path:=...`; the voice demo accepts `input_wav_path:=...`.

The person-tracking demo opens the camera and launches several ROS nodes. Only run one camera stack at a time. It is a software prototype: `object_track` defaults to `dry_run: true`, and this repository does not provide the missing wheels, motor driver, head servo or navigation sensors.

## Repository boundaries

- This repository: XiaoMo-derived ROS 2 application code, project-specific docs and build/test instructions.
- `oragnepi-pratice`: general Orange Pi networking, hardware, SSH and Codex-on-board operating notes.
- `/home/orangepi/models/` and `/home/orangepi/local-data/`: local model and test assets; keep outside Git.
- `ros2_ws/build`, `install`, `log`: generated build outputs; keep outside Git tracking.
