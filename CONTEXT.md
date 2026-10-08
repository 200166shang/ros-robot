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
- Issue: [#7 View YDLIDAR scans in RViz2 and from a Mac browser](https://github.com/200166shang/ros-robot/issues/7) remains open for review. Its implementation plan specifies a board-local virtual display, RViz2, VNC/noVNC services bound to loopback, and a Mac SSH tunnel. All acceptance criteria are now checked.
- Decision: run Xvfb, Openbox, x11vnc, websockify/noVNC, and Foxy RViz2 natively on the Orange Pi. This avoids changing or depending on `robot-docker`'s Jazzy simulation service and avoids exposing VNC to the LAN. The Mac only opens the tunneled noVNC page. Foxglove remains the verified direct ROS-topic view.
- Implemented in this checkout: `scripts/rviz2-headless.sh` manages the headless display and RViz2 process, and `ros2_ws/src/ydlidar/README.md` documents the workflow in Chinese and English. The helper's stop operation leaves the lidar driver running. Both VNC and websockify are configured for loopback only.
- Environment evidence: `rviz2` resolves after sourcing `/opt/ros/foxy/setup.zsh` and `ros2_ws/install/setup.zsh`. The board had `xserver-common` held at `2:1.20.13-1ubuntu1~20.04.8`; pinning `xvfb=2:1.20.8-2ubuntu2` allowed APT to install the requested components and 35 new packages with zero upgrades or removals. The held package was not changed.
- Runtime validation: started the YDLIDAR driver with the SDK library path and confirmed a live `/scan` subscription in RViz2. RViz2 showed `/scan` in `laser_link`, LaserScan status was OK, and the captured 1280x800 virtual display contained the red scan points. A ROS 2 echo showed `frame_id: laser_link`, 260 ranges, and about 0.165 seconds per scan. `scripts/rviz2-headless.sh start` and `status` succeeded; noVNC returned HTTP 200, VNC sent `RFB 003.008`, and two WebSocket reconnects returned `101 Switching Protocols` while driver/RViz2/VNC/websockify PIDs stayed unchanged. `stop` removed the GUI services and left the driver running; the GUI service and driver were restarted afterward for user access.
- Validation: `bash -n scripts/rviz2-headless.sh` and `git diff --check` passed. The user confirmed the Mac SSH tunnel/noVNC browser view works and the scan points move with the radar scene. Local checks also confirmed RViz2's live `/scan` rendering, noVNC HTTP/RFB/WebSocket connectivity, and reconnects with service PIDs unchanged. No chassis actuation was performed. Research details remain in the local, ignored `docs/research/novnc-rviz2-headless-evaluation.md` note.
- Review: Standards review found no documented-rule breaches or clear smells. Spec review found no scope deviations apart from runtime items that were pending at review time; local runtime checks above now cover the Orange Pi display and service reconnect path.
- Commits: `9d1bca2 feat: add headless RViz2 access over noVNC`; installer guidance and runtime notes are committed. Issue #7 records the implementation plan and all acceptance criteria as complete. `robot-docker` remains unchanged.
- User verification: Mac browser access through the SSH tunnel works, and the scan points move with the radar scene. Issue #7 was updated with this evidence.
- Next action: review and merge the PR for Issue #7.

## YDLIDAR visualization completion and branch cleanup — 2026-10-07 (Asia/Shanghai)

- Issue: [#7 View YDLIDAR scans in RViz2 and from a Mac browser](https://github.com/200166shang/ros-robot/issues/7) is closed. GitHub shows all 7 acceptance criteria checked; the user verified Mac noVNC access and live scan motion.
- Merge: [PR #9](https://github.com/200166shang/ros-robot/pull/9) merged into `main` at `875a4e4`.
- Cleanup: synchronized local `main` to `origin/main` with fast-forward; deleted the merged local and remote branch `codex/issue-7-rviz2-mac-browser`.
- Validation: GitHub confirms #7 closed and PR #9 merged. Working tree is clean on `main`; no implementation tests were needed for this repository synchronization and branch cleanup task.
- Next action: none for YDLIDAR bring-up and visualization; continue with a new issue when needed.

## Camera module preparation — 2026-10-08 (Asia/Shanghai)

- Spec: [#11 Add a repeatable USB camera performance benchmark](https://github.com/200166shang/ros-robot/issues/11), published with the `ready-for-agent` label after the user confirmed the test seam.
- Implementation ticket: [#12 Add a standalone camera capture-to-ROS benchmark](https://github.com/200166shang/ros-robot/issues/12), a single child ticket with no blockers, also labeled `ready-for-agent`.
- Branch: created `codex/camera-module` from clean `main` at `95b245f`.
- Decisions: add a standalone `camera_bench` executable in `usb_camera`; reuse `V4l2Camera`; measure capture, publish, and receive FPS/counts, V4L2 sequence gaps, aggregate publish/receive count difference, average publish-to-receive latency, and average JPEG size. Defaults are 2 seconds warm-up and 30 seconds measurement; print a concise summary and append CSV. The confirmed test seam is deterministic observations into the metrics/report interface, with hardware validation as a separate manual run.
- Preparation changes: formatted the three C++ files in `ros2_ws/src/usb_camera/` with repository `.clang-format`; added Chinese comments for V4L2 setup, MMAP ownership/queue flow, copying, cleanup, and ROS capture/publish. Added the root glossary terms used by the spec. No runtime behavior was changed.
- Validation: the issue body and `ready-for-agent` label were verified on GitHub; `clang-format --dry-run --Werror` and `git diff --check` passed. No tests or hardware validation were run.
- Next action: implement Issue #12 when implementation work begins.

## Camera benchmark implementation — 2026-10-08 (Asia/Shanghai)

- Issue: [#12 Add a standalone camera capture-to-ROS benchmark](https://github.com/200166shang/ros-robot/issues/12), still open pending review and tracker completion.
- Implemented: added a separate `camera_bench` ROS 2 executable that reuses `V4l2Camera`, publishes compressed frames on its private benchmark topic, and receives them through a ROS subscription. It uses a fixed 2-second warm-up, defaults to a 30-second measurement window, reports capture/publish/receive counts and rates, V4L2 sequence gaps, publish/receive count difference, average latency and JPEG size, and appends completed runs to CSV. Setup, capture, and CSV failures do not produce a completed row.
- Design: `CameraBenchMetrics` is the deterministic observation/report interface and has no ROS or camera dependency. V4L2 sequence metadata is optional for existing camera callers; `usb_camera_node` runtime behavior remains unchanged.
- Validation: ROS 2 Foxy package build succeeded; the full workspace test run passed (14 tests, 0 failures); `clang-format --dry-run --Werror` and `git diff --check` passed. Hardware run on `/dev/video0` at 640x480, requested 30 fps: 64 captured/published/received frames over 3 seconds, zero sequence gaps and count difference, 0.65 ms average latency, 26.2 kB average JPEG. A second 1-second run appended a second CSV row without duplicating the header. No chassis actuation was performed.
- Review: Standards review found no documented-rule breaches; its minor unclear `s` summary parameter finding was fixed. Spec review found all requested behavior, and its fixed post-run wait concern was addressed with count-equality detection plus a one-second quiet drain window when counts differ. The quiet window is a bounded practical drain policy; it cannot prove middleware queues empty under arbitrarily delayed delivery.
- Validation after the drain fix: package build and full workspace tests passed (14 tests, 0 failures). A repeated ROS hardware run timed out during warm-up; `v4l2-ctl` still streams at 30 fps, but a direct probe of both the changed and baseline `V4l2Camera` also timed out. The earlier end-to-end ROS run and CSV append check succeeded before the reporting-only drain adjustment.
- Tracker: acceptance criteria were checked, implementation/review/validation evidence and the repeated hardware-run limitation were posted in [the #12 implementation comment](https://github.com/200166shang/ros-robot/issues/12#issuecomment-6056446572), and #12 was closed on 2026-10-08 (Asia/Shanghai).
- Next action: none for Issue #12.

## Development workflow Chinese annotations — 2026-10-08 (Asia/Shanghai)

- Updated [docs/development-workflow.md](docs/development-workflow.md) with Chinese notes for the source-of-truth and responsibility chain, build/test commands, hardware demo boundary, and Git hygiene checks. Commands and existing safety settings were left unchanged.
- Validation: `git diff --check` passed; this documentation-only edit does not require a build or runtime test.
- Next action: none.

## Camera benchmark Chinese code comments — 2026-10-08 (Asia/Shanghai)

- Added Chinese comments to the camera benchmark ROS node, metrics Interface/Implementation, unit-test cases, and CMake target/test declarations. The comments explain the worker/executor split, warm-up and measurement clocks, intentional end-of-window frame skips, metrics accounting, receiver drain, CSV failure handling, and test intent. No runtime behavior changed.
- Validation: `clang-format --dry-run --Werror` and `git diff --check` passed; no tests were run for this comments-only change.
- Next action: none.
