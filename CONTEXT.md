# Project context

## Reading this file

This file is a handoff checkpoint. Recheck source, issue state, and the working tree before treating an entry as current. Record dates with the timezone. Link to authoritative files and issues instead of copying their contents. Keep model assets, credentials, and private recordings out of this document.

## Project pointers

- Purpose and target platform: `README.zh-CN.md` and `README.md`.
- GitHub repository: `200166shang/ros-robot`.
- ROS package source: `ros2_ws/src/`.
- Demo entry: `scripts/run-demo.sh`; lifecycle management: `scripts/demo_launcher.py`.
- Voice-to-tracking composition: `ros2_ws/src/robot_bringup/launch/person_tracking_demo.launch.py`.
- Engineering conventions: `AGENTS.md` and `docs/agents/`.

## Setup checkpoint — 2026-10-05 (Asia/Shanghai)

- Completed: configured Matt Pocock engineering skills for GitHub Issues, `AGENTS.md`, and a single domain context. The user confirmed the draft and the five default triage labels.
- GitHub verified on 2026-10-05 (Asia/Shanghai): `gh` is authenticated as `200166shang`; repository access has ADMIN permission and Issues are enabled. All five labels in `docs/agents/triage-labels.md` exist remotely: four missing labels were created and the existing `wontfix` label was retained.
- No implementation or hardware validation was performed during this documentation setup.
- Validation: `git diff --check` passed. Changes are being prepared for PR review; no build or runtime validation applies to this documentation and ignore-rule setup.
- Next action: review and merge the repository setup PR; for development work, read or create its GitHub issue, establish acceptance criteria, and apply `codebase-design` to any module design work.

## YDLIDAR X2 bring-up and ROS 2 spec checkpoint — 2026-10-07 (Asia/Shanghai)

- Issue: [#5 Bring up YDLIDAR X2 and migrate driver to ROS 2](https://github.com/200166shang/ros-robot/issues/5).
- Confirmed scope: first validate the standalone YDLIDAR SDK/API reads at least one valid scan; then preserve the ROS1 driver's behavior and make only the ROS1-to-ROS2 integration changes; validate in RViz2, then expose the same scan stream to a Mac browser.
- Source review: `/home/orangepi/code/robot/src/ydlidar/` is a ROS1 package with a unified lidar interface, YDLIDAR SDK adapter, configuration loader, and a node that publishes `scan` plus `start_scan`/`stop_scan`. The target repository still has no radar package and its ROS 2 C++ packages use `ament_cmake`.
- Environment and hardware evidence: ROS 2 Foxy is installed. The adapter enumerates as QinHeng HL-340 (`1a86:7523`) with the `ch341` driver at `/dev/ttyUSB0`; the stable `/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0` symlink exists, and the user is in `dialout`. Using the project's pinned YDLIDAR SDK 1.2.7 built under `/tmp`, the X2 settings from the ROS1 launch initialized successfully, reported healthy status, and returned three scans of 510 points each; 176–181 points had finite ranges in the configured interval at about 5.9–6.0 Hz. SDK metadata prints model `F2` although the user identifies the unit as X2; scan acquisition succeeds with the X2 settings. The bundled SDK 1.0.3 sample crashed during scan processing, so use the project's 1.2.7 dependency.
- Specification: issue #5 now contains the agreed scope, user stories, ROS 2 `LaserScan` test seam, implementation/testing decisions, and out-of-scope items. It is labeled `ready-for-agent`.
- Tickets: [#6 ROS 2 driver and LaserScan](https://github.com/200166shang/ros-robot/issues/6) is a child of #5 and ready to start. [#7 RViz2 and Mac browser visualization](https://github.com/200166shang/ros-robot/issues/7) is also a child of #5 and is natively blocked by #6. Both carry the `ready-for-agent` label; GitHub confirms the parent/child and blocking relationships.
- Next action: implement #6, then implement #7's combined RViz2 and Mac browser visualization slice against the same `scan` stream.

## YDLIDAR ROS 2 driver checkpoint — 2026-10-07 (Asia/Shanghai)

- Issue: [#6 ROS 2 driver and LaserScan](https://github.com/200166shang/ros-robot/issues/6).
- Implemented: added `ros2_ws/src/ydlidar/` with an `ament_cmake` ROS 2 Foxy package, SDK 1.2.7 CMake dependency, configurable X2 settings, `LaserScan` publication on relative `scan`, `start_scan`/`stop_scan` services, shutdown stop/disconnect, and a launch entry point defaulting to the validated USB by-id path.
- Decisions: retained the reference node's degree-valued SDK angle options, radians from SDK scan metadata, `ceil` point binning, and default zero fill for invalid ranges. Used distinct `lidar_driver_type` and integer SDK `lidar_type` parameters per #5.
- Validation: launch Python syntax compilation and `git diff --check` passed. Package configuration reached the expected missing external dependency: this host has ROS 2 Foxy but no installed YDLIDAR SDK 1.2.7 CMake package/library; the repository's SDK archive is only a Git LFS pointer in the sibling checkout. No hardware actuation was performed.
- Next action: complete source review and commit the implementation. Build and hardware scan/service smoke checks remain to run on an environment with SDK 1.2.7 installed and the lidar connected.

## Future checkpoint format

Record the active issue URL, resolved decisions or ADR links, completed work, validation evidence, open questions, and next action. Replace stale checkpoint details when work advances.
