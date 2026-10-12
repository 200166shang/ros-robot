# Issue #48 YDLIDAR SDK validation record

Date: 2026-10-13 (Asia/Shanghai)

## Automated checks

- `python3 tests/test_install_ydlidar_sdk.py`: 6 tests passed. This includes
  mocked install/reuse/failure cases, Zsh environment exports, and a CMake
  `find_package(ydlidar_sdk 1.2.7)` probe.
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

Pending. The installer has not been run against the persistent user prefix, and
the real SDK build, dynamic-link check, physical `/scan` publication, and
post-reboot environment reload have not been performed. Record each result here
after running the commands in `ros2_ws/src/ydlidar/README.md`; do not report
board acceptance as complete before then.
