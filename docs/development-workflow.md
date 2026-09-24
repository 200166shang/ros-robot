# Development workflow

## Source of truth and responsibilities

- Edit, build, test and commit the project in `/home/orangepi/code/ros-robot` on the Orange Pi.
- Use the Mac Codex session to inspect and operate the board over the configured SSH alias; keep learning notes in Obsidian.
- Keep generic board provisioning/network/SSH notes in `oragnepi-pratice`, not duplicated as project implementation.
- Use Git to move source changes to GitHub. Model weights and private/local test data use their documented external paths and are never included in source commits.

## Build and unit-test without starting hardware nodes

```bash
bash --noprofile --norc <<'BASH'
cd /home/orangepi/code/ros-robot/ros2_ws
source /opt/ros/foxy/setup.bash
colcon --log-base log build --base-paths src \
  --build-base build --install-base install --executor sequential \
  --cmake-args -DRKNN_API_INCLUDE_DIR=/home/orangepi/sdk/rknn/include
colcon --log-base log test --base-paths src --build-base build --install-base install
colcon test-result --test-result-base build --verbose
BASH
```

## Hardware demo boundary

`person_tracking_demo.launch.py` starts the camera, image decoder, detector, tracker, Agent, voice front end and acceptance probe. It reads the RKNN model and test WAV from local-only asset paths. Before starting it, check whether the old workspace is using `/dev/video0`; do not start the old and new camera stacks at the same time. The tracking configuration keeps `dry_run: true`; this is not a motor-control or navigation acceptance test.

## Git hygiene

Review `git status --short` and the staged diff before each commit. Do not use `git add -A` blindly. In particular, verify that no `.rknn`, `.gguf`, `.onnx`, `.wav`, `.m4a`, `rknn_api.h`, ROS build output, credentials or machine-private recordings are staged.
