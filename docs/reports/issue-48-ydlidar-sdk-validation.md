# Issue #48 YDLIDAR SDK validation record

Date: 2026-10-13 (Asia/Shanghai)

## Automated checks

- `python3 tests/test_install_ydlidar_sdk.py`: 6 tests passed. This includes
  mocked install/reuse/failure cases, Zsh environment exports, and a CMake
  configure/link probe for `ydlidar_sdk 1.2.7`.
- `bash -n scripts/install-ydlidar-sdk.sh`, `zsh -n
  scripts/ydlidar-sdk-env.zsh`, `bash -n scripts/ydlidar-sdk-env.zsh`, and
  `git diff --check`: passed.
- `colcon build --packages-select ydlidar --cmake-args
  -DYDLIDAR_BUILD_HARDWARE_NODE=OFF`: passed on aarch64 with ROS Foxy.
- Existing `test_ydlidar_ros_interface`: passed with `ROS_DOMAIN_ID=88`.
  CTest on the default ROS domain crashed on its first run and timed out during
  executor shutdown on its second run; three direct invocations passed. CTest
  with the isolated domain completed with 0 test failures. The README test
  commands now set an unused ROS domain to isolate the test from live nodes.

The installer tests replace `git` and `cmake` through `PATH`. They cover
successful installation, reuse of a completed install, download failure, build
failure, and rejection of an install prefix inside the repository. They do not
download or compile the vendor SDK.

## Orange Pi hardware acceptance

Checked on 2026-10-13 (aarch64, ROS Foxy):

- The persistent prefix contains the V1.2.7 marker for commit
  `ad8e30f9e9315d4bd7544df85571072fdbcd31ea` and
  `lib/libydlidar_sdk.so`.
- The first launch reproduced the missing libexec error. Its CMake cache had
  `YDLIDAR_BUILD_HARDWARE_NODE=OFF`, left by the interface-only build, so the
  package was registered and its launch file installed without
  `lib/ydlidar/ydlidar_node`.
- `./scripts/colcon.sh build --packages-select ydlidar --cmake-args
  -DYDLIDAR_BUILD_HARDWARE_NODE=ON`: passed; the hardware node was installed.
- `ldd "$(ros2 pkg prefix ydlidar)/lib/ydlidar/ydlidar_node"`: all libraries
  resolved, including `libydlidar_sdk.so` from the persistent prefix.
- `ros2 launch ydlidar ydlidar.launch.py`: SDK 1.2.7 initialized, the F2 lidar
  connected with good health, and scan mode started.
- `timeout -s INT 8s ros2 topic hz /scan`: observed about 6.07 Hz. The launch
  was then stopped with Ctrl+C; the driver reported that scanning stopped.

Post-reboot environment reload remains pending. Record it after rebooting the
board; do not mark that acceptance check complete before then.
