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
- Implemented: added `ros2_ws/src/ydlidar/` with an `ament_cmake` ROS 2 Foxy package, SDK 1.2.7 CMake dependency, configurable X2 settings, `LaserScan` publication on relative `scan`, `start_scan`/`stop_scan` services, shutdown stop/disconnect, and a launch entry point defaulting to the validated USB by-id path. The ROS node accepts an internal scan-source seam so the public ROS interfaces can be tested without hardware.
- Decisions: retained the reference node's degree-valued SDK angle options, radians from SDK scan metadata, `ceil` point binning, and default zero fill for invalid ranges. Used distinct `lidar_driver_type` and integer SDK `lidar_type` parameters per #5.
- Validation: the ROS interface gtest passes (1/1), covering LaserScan metadata/data, invalid range fill, auto-start, stop/start service behavior, and shutdown disconnect. The interface/test target built in ROS 2 Foxy with `-DYDLIDAR_BUILD_HARDWARE_NODE=OFF`; launch Python syntax and `git diff --check` passed. The normal hardware-node build remains unverified because this host lacks the SDK 1.2.7 CMake package/library and the sibling repository has only a Git LFS pointer for its SDK archive. No hardware actuation was performed.
- Review: the Standards and Spec reviews found no remaining issues. Commits: `88df7dc` adds the driver and `50a1f1d` adds the test seam/interface test.
- Next action: run the full driver build and hardware scan/service smoke checks when SDK 1.2.7 is available, then continue with #7's RViz2 and Mac browser visualization slice.

## Future checkpoint format

Record the active issue URL, resolved decisions or ADR links, completed work, validation evidence, open questions, and next action. Replace stale checkpoint details when work advances.

## YDLIDAR SDK and hardware validation checkpoint — 2026-10-07 (Asia/Shanghai)

- Issue: [#6 ROS 2 driver and LaserScan](https://github.com/200166shang/ros-robot/issues/6), now closed after all acceptance criteria were verified.
- SDK/build: fetched the official SDK V1.2.7 release archive; its SHA-256 matched the repository's pinned Git LFS OID. Built and installed the SDK under `/tmp`, then built package `ydlidar` in ROS 2 Foxy with `YDLIDAR_BUILD_HARDWARE_NODE=ON`. The package test passed (1/1); generated SDK/build output remains outside source commits.
- Hardware smoke check: the node connected to `/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0`, SDK 1.2.7 reported healthy status, and `/scan` delivered `laser_link` scans with 255 points and 129–133 valid ranges in observed samples. `/stop_scan` yielded zero new scans over the 1-second observation; `/start_scan` resumed publication. On shutdown the node exited and released `/dev/ttyUSB0`.
- Issue tracker: acceptance criteria were checked, validation evidence was commented, and #6 was closed.
- Next action: continue with #7's RViz2 and Mac browser visualization slice.

## YDLIDAR visualization checkpoint — 2026-10-07 (Asia/Shanghai)

- Issue: [#7 View YDLIDAR scans in RViz2 and from a Mac browser](https://github.com/200166shang/ros-robot/issues/7). GitHub confirms #7 remains open and its only blocker, #6, is closed.
- Branch and implementation: `codex/issue-7-rviz2-mac-browser`; added a bilingual package README with Orange Pi RViz2 and Foxy `rosbridge_server` + Mac Foxglove steps, and an RViz2 preset using `/scan` and fixed frame `laser_link`. Both views use the existing driver topic; no second acquisition path or custom browser app was added. Foxy uses Rosbridge because current Foxglove Bridge binary packages do not support Foxy; Foxglove documents Rosbridge connections and LaserScan support.
- Validation: RViz preset parses as YAML and its LaserScan topic/frame values were checked; Python suite: 29 passed and ROS workspace suite: 10 passed across 13 packages. In Zsh, sourcing the Foxy and workspace `setup.zsh` files resolves `ros2` and `ydlidar`. Diagnosed the initial launch failure: `/tmp/ydlidar-sdk-install/lib` was missing from `LD_LIBRARY_PATH`; `ldd` resolves the SDK after adding that path. With the path set, the driver connected to the by-id serial port using SDK 1.2.7, reported healthy status, and `/scan` output had `frame_id: laser_link`; Ctrl+C stopped the scan and node cleanly. The bilingual guide now includes the SDK library path and Foxy-compatible topic echo commands. No `rviz2` executable is installed, so the RViz GUI and Mac browser connection remain unverified; no chassis actuation was performed.
- Commit: `a0e38f5 docs: add YDLIDAR visualization setup for issue 7`.
- Review: Standards and Spec reviews found no violations, smells, missing criteria, scope creep, or apparent implementation errors.
- Next action: install RViz2 on the Orange Pi if needed, then verify the preset and Mac browser connection against a live scan before checking off or closing #7.

## YDLIDAR browser live-view verification — 2026-10-07 (Asia/Shanghai)

- Issue: [#7 View YDLIDAR scans in RViz2 and from a Mac browser](https://github.com/200166shang/ros-robot/issues/7) remains open; #6 is closed.
- User verification: Foxglove in the Mac browser connected to `ws://192.168.3.101:9090`, displayed live red LaserScan points with frame `laser_link`, and the points changed as an object moved in front of the radar. This confirms the driver → Rosbridge → browser path using the existing `/scan` stream. The Image panel waiting for images is expected because this setup publishes LaserScan, not camera images.
- Remaining acceptance work: RViz2 GUI display on the Orange Pi has not yet been verified; `rviz2` was not installed in the earlier environment check. Keep #7 open until that criterion is tested.
- Next action: install or otherwise make RViz2 available on the Orange Pi, load `ydlidar.rviz`, and verify `/scan` renders in `laser_link`.

## Headless RViz2 / noVNC plan evaluation — 2026-10-07 (Asia/Shanghai)

- Related issues: [ros-robot #7](https://github.com/200166shang/ros-robot/issues/7) remains open for RViz2 validation; [robot-docker #6](https://github.com/200166shang/robot-docker/issues/6) is closed and its current implementation is on `robot-docker` commit `7d7a3c76`.
- Reviewed the `robot-docker` Compose and GUI startup scripts. Its Mac-side noVNC container points to the same project's `sim:5900`; `make sim-rviz` launches ROS 2 Jazzy RViz2 inside that simulation container. The current setup does not display the Orange Pi desktop or subscribe to its Foxy `/scan` by itself.
- Initial recommendation (superseded by the implementation checkpoint below): reuse only the Mac noVNC browser frontend and route it to a VNC server attached to RViz2 on the board.
- Research note: `docs/research/novnc-rviz2-headless-evaluation.md` is intentionally ignored by `.gitignore` as a local research note. No Docker daemon on the Mac was available to this session, so repointing the Mac container and measuring performance remain untested. No hardware state was changed.
- User clarified to borrow the noVNC architecture without modifying `robot-docker`. Updated #7's implementation plan and added pending acceptance criteria for a virtual Orange Pi display, Mac noVNC access over an SSH tunnel, and reconnecting without stopping the driver/RViz2.
- Next action at that checkpoint: confirm the board has (or can install) RViz2 and choose where the noVNC service should run.

## Headless RViz2 implementation checkpoint — 2026-10-07 (Asia/Shanghai)

- User decision: borrow the noVNC approach from `robot-docker` without modifying that repository; migrate the headless RViz2 path into `ros-robot` and run it on the Orange Pi.
- Issue: [#7 View YDLIDAR scans in RViz2 and from a Mac browser](https://github.com/200166shang/ros-robot/issues/7) remains open. Its implementation plan now specifies a board-local virtual display, RViz2, VNC/noVNC services bound to loopback, and a Mac SSH tunnel. The browser/Foxglove criteria remain verified; the headless RViz2 criteria are pending runtime validation.
- Decision: run Xvfb, Openbox, x11vnc, websockify/noVNC, and Foxy RViz2 natively on the Orange Pi. This avoids changing or depending on `robot-docker`'s Jazzy simulation service and avoids exposing VNC to the LAN. The Mac only opens the tunneled noVNC page. Foxglove remains the verified direct ROS-topic view.
- Implemented in this checkout: `scripts/rviz2-headless.sh` manages the headless display and RViz2 process, and `ros2_ws/src/ydlidar/README.md` documents the workflow in Chinese and English. The helper's stop operation leaves the lidar driver running. Both VNC and websockify are configured for loopback only.
- Environment evidence: `rviz2` is installed and resolves after sourcing `/opt/ros/foxy/setup.zsh` and `ros2_ws/install/setup.zsh`. `apt-cache policy` confirms ARM64 Focal candidates for `xvfb`, `openbox`, `x11vnc`, `novnc`, and `websockify`; these packages are not installed. `sudo -n` requires a password, so no packages were installed and no GUI/runtime validation was performed in this session.
- Validation: `bash -n scripts/rviz2-headless.sh` and `git diff --check` passed. A `start` invocation correctly reported the missing Xvfb/Openbox/x11vnc/noVNC packages before starting services. No hardware action was performed. Research details remain in the local, ignored `docs/research/novnc-rviz2-headless-evaluation.md` note.
- Review: Standards review found no documented-rule breaches or clear smells. Spec review found no scope deviations; live display, browser connection, and reconnect acceptance remain pending package installation and runtime validation.
- Commits: `9d1bca2 feat: add headless RViz2 access over noVNC`; checkpoint update follows.
- Issue #7 now records the exact package list, helper/README paths, SSH tunnel/browser URL, and live scan/reconnect validation steps. A progress comment records the pending runtime dependencies. `robot-docker` remains unchanged.
- Next action: install `xvfb openbox x11vnc novnc websockify x11-utils iproute2 libgl1-mesa-dri` on the Orange Pi, start the headless RViz2 helper while the driver is running, then verify the Mac browser view and reconnect behavior before checking off the remaining #7 criteria.
