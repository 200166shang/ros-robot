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

## Camera pipeline Orange Pi validation — 2026-10-09 (Asia/Shanghai)

- Issue: [#19 Verify Orange Pi camera preview and ROS 2 pipeline rates](https://github.com/200166shang/ros-robot/issues/19), after blockers #16–#18 were merged.
- Added a camera Image RViz2 preset with Best Effort QoS and made `scripts/rviz2-headless.sh` accept `ROBOT_RVIZ2_CONFIG`, preserving the YDLIDAR view as the default. Updated the decoder and encoder usage guides with noVNC preview, rate observation, backend selection, and a ROS 2 encoder-to-decoder probe.
- OpenCV and MPP/RGA configurations built on Orange Pi. OpenCV physical path: capture 29.8 FPS, camera topic 29.79 FPS, decoder 27.69 FPS. MPP/RGA physical path: 29.8 / 29.79 / 29.79 FPS. With `frame_divider=2`, capture remained 29.8 FPS while camera publication and decode were 14.88 FPS. Measurement windows were 10 seconds after an 8-second warm-up; software-rendered RViz was stopped for rate measurement.
- RViz2 displayed the physical camera image with the Best Effort topic QoS; the noVNC endpoint served HTTP 200 locally. OpenCV and MPP/RGA encoder-to-decoder ROS topic round trips both preserved `jpeg` format/header, returned 320×180 `rgb8`, and passed four-region content checks. Encoder performance was not measured.
- Supplemental bandwidth measurement: during a live OpenCV run, `ros2 topic bw --window 20` measured approximately 0.985 MB/s on `/image_raw/compressed` and 19.66 MB/s on `/camera/image_raw`; three stable outputs per topic were averaged. The report notes the capture reopen and OpenCV JPEG warnings observed during this run, and that MPP/RGA bandwidth was not measured.
- Follow-up documentation in PR #24 adds end-to-end FPS interpretation, bandwidth-vs-payload analysis, and step-by-step commands to rebuild, start, monitor bandwidth/rates, and verify `frame_divider=2` independently.
- Physical camera upper-bound probe: V4L2 enumerates no MJPEG mode above 30 FPS at 1280×720. Direct `usb_camera_node` runs requesting 30 and 60 FPS both stabilized near 29.8 FPS when `exposure_auto_priority=0`; `VIDIOC_G_PARM` returned 30 FPS. With auto-exposure priority enabled in a low-light run, exposure reached 41.9 ms and capture slowed to 24.1 FPS. The setting was restored to enabled after the controlled probe. The standalone `camera_bench` attempt timed out before its first frame; the rate cap was measured through the regular node and `ros2 topic hz`.
- Validation report: [docs/reports/camera-pipeline-orange-pi-2026-10-09.md](docs/reports/camera-pipeline-orange-pi-2026-10-09.md). Next action: PR [#24](https://github.com/200166shang/ros-robot/pull/24) is open for review; leave Issue #19 open pending review/merge.

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

## Camera benchmark pull request — 2026-10-08 (Asia/Shanghai)

- Submitted [PR #13](https://github.com/200166shang/ros-robot/pull/13) from `codex/camera-module` to `main`. The PR includes the standalone camera benchmark, its validation and review evidence, and Chinese comments for the code flow.
- The Chinese annotations in `docs/development-workflow.md` remain local because that path is ignored by the repository; it was not force-added to the PR.
- PR #13 was merged into `main` on 2026-10-08; see the merge checkpoint below.

## Camera benchmark capture flow refactor — 2026-10-08 (Asia/Shanghai)

- Request: review and reduce cognitive load in the USB camera C++ flow while preserving behavior.
- Changed `ros2_ws/src/usb_camera/src/camera_bench_node.cpp`: kept `capture_run()` as the stage orchestrator; removed width/height and V4L2 sequence from cross-stage parameters; separated receiver-drain criteria, report writing, and ROS shutdown from the timer callback; documented thread shutdown/join and cross-thread state purpose. The reusable JPEG buffer and existing capture adapter lifecycle remain unchanged.
- Review scope: checked `CameraBenchNode`, its `V4l2Camera` use and cleanup contract, and `UsbCameraNode`'s worker lifecycle. No changes were needed in the shared V4L2 adapter or normal camera node.
- Behavior: capture/publish/receive accounting, measurement and ROS timestamp windows, 250 ms grace period, one-second receiver quiet window, CSV output, and error exit behavior are unchanged.
- Validation: `clang-format --dry-run --Werror` and `git diff --check` passed. No build or tests were run.
- PR #13 remains open on GitHub, targeting `main`; these changes are uncommitted in the working tree.
- Next action: user reviews the refactor, then decide whether to update PR #13.

## Camera benchmark onboarding readability follow-up — 2026-10-08 (Asia/Shanghai)

- User approved a further readability pass limited to the performance benchmark node.
- Extracted the in-line subscriber logic to `on_image_received()` and per-frame message creation/accounting/publication to `publish_benchmark_frame()`. Added Chinese explanations for JPEG copying, reusable frame-buffer capacity, and why dimensions are saved before `close_device()` resets them. The normal camera node and V4L2 adapter remain unchanged.
- Preserved the existing capture and receive windows, counters, lock scope, and publication order.
- Validation: `clang-format --dry-run --Werror` and `git diff --check` passed; no build or tests were run.
- Changes remain uncommitted; PR #13 has not been updated.
- Next action: user reviews the onboarding readability pass.

## Camera benchmark source organization — 2026-10-08 (Asia/Shanghai)

- User approved a layout-only pass to make related code easier to scan.
- Grouped `CameraBenchNode` methods by execution path: the capture worker stages are contiguous, followed by ROS executor callbacks and report/drain helpers. Added visible setup phases in the constructor and grouped fields by configuration, capture/metrics ownership, thread state, timing/results, and ROS handles.
- No behavior or interface changes were intended.
- Re-applied clang-format after the user changed `.clang-format`'s column limit to 160.
- Validation: `clang-format --dry-run --Werror` and `git diff --check` passed. No build or tests were run.
- Changes remain uncommitted; PR #13 has not been updated.
- Next action: user reviews the source layout.

## Camera benchmark function comments — 2026-10-08 (Asia/Shanghai)

- Added a concise Chinese function-header comment to each named function in `camera_bench_node.cpp`; clarified `capture_run()` as the orchestration point and retained only key inline comments for handoffs and constraints.
- Split constructor validation into named camera-setting and duration checks so the two parameter groups are easier to scan.
- Applied the user's updated `.clang-format` (160-column limit) to the file.
- Validation: `clang-format --dry-run --Werror` and `git diff --check` passed; no build or tests were run.

## Camera benchmark visual block spacing — 2026-10-08 (Asia/Shanghai)

- Added blank lines at the parameter-read/validation/conversion transitions, camera setup success path, measurement setup/loop transition, per-frame message/metrics/publish steps, finish-state gates/summary handoff, and CSV-write/log transition in `camera_bench_node.cpp`.
- No statements, control flow, or runtime behavior changed.
- Validation: formatted with the current `.clang-format`; `clang-format --dry-run --Werror` and `git diff --check` passed. No build or tests were run.

## C++ readability guidance — 2026-10-08 (Asia/Shanghai)

- Added a `C++ readability and review` subsection to root `AGENTS.md`, covering call-chain and member grouping, semantic blank lines, Chinese function comments, named validation concepts, and domain-based function splitting.
- Kept the guidance in the repository instructions so it applies automatically; no separate Skill or RULE file was added.
- Validation: `git diff --check` passed. Documentation-only change; no build or tests apply.

## Camera benchmark intermittent startup timeout — 2026-10-08 (Asia/Shanghai)

- Reproduced the reported `/dev/video0` 640x480, requested 30 FPS run with a 3-second measurement five times: one run logged `camera capture failed: capture timeout`; four runs completed with 89 capture/publish/receive frames, zero sequence gaps, and about 29.67 FPS.
- Source check: the error comes from `select()` timing out in `V4l2Camera::capture()`. The reported log stops before `measuring`, so the timeout is in `warm_up_camera()`'s first frame wait. If no warm-up frame arrives within its 2-second capture timeout, it aborts the run.
- Follow-up on the repeated timeout: a standalone probe linked directly to `V4l2Camera` reproduced the failure without ROS (1 timeout in 5 starts); successful first-frame waits took about 1.74–1.75 seconds. A `v4l2-ctl` one-frame probe took 3.75 seconds once and exceeded a 10-second diagnostic limit on another attempt.
- Device/kernel evidence: `/dev/video0` is a Logitech UVC camera (`046d:0825`) using `uvcvideo` on kernel 5.10.160. Kernel logs show repeated resets of USB device `5-1`; one reset at 14:20:56 followed the reported 14:20:54 capture timeout. A later `fuser` check found no process holding the device.
- Conclusion: the bench's 2-second first-frame deadline explains the error message, while direct V4L2 and kernel evidence point to an unstable USB camera stream/reset as the underlying cause. Extending the bench wait alone may only hide the symptom. No source behavior was changed in this diagnosis. GitHub confirms Issue #12 remains closed and its prior comment also records intermittent warm-up timeouts.
- Next action: test the camera on another USB port/cable or a powered hub and watch kernel USB/UVC logs; revisit a bounded first-frame startup policy only after the device stream is stable.

## Camera benchmark bounded first-frame wait — 2026-10-08 (Asia/Shanghai)

- User authorized raising the startup wait and continuing hardware validation. In `ros2_ws/src/usb_camera/src/camera_bench_node.cpp`, first-frame acquisition now retries in at-most-2-second waits for up to 15 seconds; shutdown remains responsive at each retry. The existing 2-second warm-up now starts after the first frame, and the measurement window and normal capture timeout remain unchanged.
- Validation: root `install/` overlay build succeeded; package test summary is 3 passed, 0 failed; `clang-format --dry-run --Werror` and `git diff --check` passed. The exact 640x480, requested 30 FPS, 3-second bench command completed 5/5 times. First-frame arrival took 1.75–3.25 seconds; each measurement recorded 45 capture/publish/receive frames (15 FPS), zero sequence gaps, and zero publish/receive difference.
- Device observation: `v4l2-ctl --all` reports the MJPEG stream interval as 30 FPS while `exposure_auto_priority` is enabled and exposure is 667; this may explain the 15 FPS measured rate and needs separate confirmation. No USB reset appeared during the five-run interval; a USB reset was logged at 14:35:42 afterward, so hardware link stability remains an open concern.
- No camera control settings were changed. Next action: if 30 FPS is required, investigate exposure/lighting separately; test a different cable/port or powered hub if USB resets continue.

## Camera package usage documentation — 2026-10-08 (Asia/Shanghai)

- Added `ros2_ws/src/usb_camera/README.md` with package build/environment setup, normal camera publisher launch, and `camera_bench` usage. It documents parameter defaults, the 15-second first-frame wait and 2-second warm-up, CSV append behavior, measured metrics, requested-versus-actual FPS, and USB/device troubleshooting.
- Checked the documented launch target, topic, defaults, bench parameter defaults, and metric names against package source. README whitespace/newline validation and `git diff --check` passed. No executable code changed in this documentation step.
- Next action: none for the documentation request.

## Camera benchmark PR merge and branch cleanup — 2026-10-08 (Asia/Shanghai)

- Merged [PR #13](https://github.com/200166shang/ros-robot/pull/13) into `main` as merge commit `5875601e2602451c75973cd54b31ad722c9f17b7`; Issue [#12](https://github.com/200166shang/ros-robot/issues/12) is closed.
- Deleted the remote and local `codex/camera-module` branches. The local `main` is synchronized with `origin/main`.
- At merge time, post-PR changes in `.clang-format`, `AGENTS.md`, `ros2_ws/src/usb_camera/src/camera_bench_node.cpp`, and `ros2_ws/src/usb_camera/README.md` were preserved for a follow-up branch. Generated `install/` and `log/` output remains local and uncommitted.
- The user plans to discuss CSV-to-HTML visualization separately. No new issue or implementation was started here.
- Next action: none for Issue #12; continue the visualization discussion in the user's new thread.

## Camera benchmark readability and usage follow-up — 2026-10-08 (Asia/Shanghai)

- Follow-up to merged [PR #13](https://github.com/200166shang/ros-robot/pull/13): moved the preserved local camera benchmark changes onto `codex/camera-bench-readability-followup` and committed them as `dbde98d`.
- The commit includes the named capture/startup/report stages and Chinese lifecycle comments in `camera_bench_node.cpp`, a 15-second bounded first-frame wait, the `usb_camera` usage README, the repository C++ readability guidance, and the updated clang-format column limit. Generated `install/` and `log/` output is excluded.
- Validation evidence from this code state: ROS Foxy package build passed; package tests passed (3/3); the configured 640x480, requested 30 FPS, 3-second hardware run completed 5/5 times. `clang-format --dry-run --Werror` and `git diff --check` passed again for the follow-up commit.
- Opened [PR #14](https://github.com/200166shang/ros-robot/pull/14), targeting `main`; GitHub reports it mergeable with no configured checks.
- Next action: merge PR #14 and clean up the follow-up branch; handle CSV-to-HTML visualization in the separate discussion the user plans to open.

## Standalone JPEG encoder implementation — 2026-10-09 (Asia/Shanghai)

- Issue: [#18 Add standalone ROS 2 JPEG encoder with OpenCV and MPP/RGA backends](https://github.com/200166shang/ros-robot/issues/18), implemented on independent branch `codex/issue-18-jpeg-encoder`.
- Added `ros2_ws/src/img_encode/`: a ROS 2 C++ `Image` to `CompressedImage` node, configurable topics and JPEG quality, header preservation, JPEG format metadata, OpenCV software encoding, and RGA RGB-to-YUV plus Rockchip MPP JPEG encoding. CMake `IMG_ENCODE_BACKEND=AUTO` chooses MPP on AArch64 and OpenCV elsewhere; explicit `OPENCV` and `MPP` selections are supported.
- The `img_encode` topic test publishes an RGB image through ROS, checks the compressed output header and `jpeg` format, and decodes the JPEG to verify its dimensions. It passed on Orange Pi in both MPP and explicit OpenCV builds. The MPP test exercised RGA and MPP with test-generated input; no camera acquisition or robot actuation was used.
- Validation: both backend builds and package topic tests passed. The available full workspace suite passed 16 tests across 13 packages; `rknn_yolov6` was excluded because its external `rknn_api.h` SDK header is unavailable in this environment. `clang-format --dry-run --Werror` and `git diff --check` passed.
- Review: Standards found no hard breaches; its optional PIMPL suggestion is non-blocking. Spec review found no remaining gaps after mapping MPP quality 100 to its supported maximum `q_factor` of 99. PR [#22](https://github.com/200166shang/ros-robot/pull/22) is open from `codex/issue-18-jpeg-encoder` to `main`; it was behind `main` before this synchronization.
- Next action: user review the synchronized PR #22; Issue #19 remains the later live camera integration and preview verification step.

## ROS 2 camera capture and frame divider — 2026-10-09 (Asia/Shanghai)

- Issue: [#16 Migrate V4L2 camera capture and frame divider to ROS 2](https://github.com/200166shang/ros-robot/issues/16), part of [#15](https://github.com/200166shang/ros-robot/issues/15).
- Implemented on `codex/issue-16-camera-divider`: the camera node now publishes every Nth captured JPEG according to `frame_divider` (default 1), accepts an ordered `device_candidates` parameter with rotation after open failures, and preserves the single `device` parameter as a compatibility fallback. The launch file configures only `/dev/video0`, exposes `frame_divider`, and retains lazy capture and `/enable_camera` behavior. Updated `usb_camera` usage documentation.
- Validation: ROS Foxy `usb_camera` build passed; package tests passed (4/4); launch Python syntax, `.clang-format`, and `git diff --check` passed. On the Orange Pi, a topic subscriber validated JPEG markers, format, and `camera` frame ID. With divider 2, a stable interval logged 26 FPS captured and 13 FPS published. An enable/disable topic check observed 0 messages while disabled and resumed output after enabling. Candidate failover from `/dev/not-a-camera` to `/dev/video0` succeeded. The camera intermittently timed out and reopened during these runs, consistent with the existing V4L2 reconnect path.
- Decision: use ROS topic I/O as the observable test seam; no tracking actuation was performed.
- Next action: submit PR for review; continue with issue #19 after issues #16–#18 are merged or otherwise available.

## Camera capture loop responsibility split — 2026-10-09 (Asia/Shanghai)

- Follow-up to [PR #20](https://github.com/200166shang/ros-robot/pull/20), requested during review. Extracted frame selection into `usb_camera/frame_divider.hpp` and capture/publish rate windows into `usb_camera/frame_rate_stats.hpp`; the ROS node now records events and reports snapshots. Reset the stats window while capture is idle or recovering from a capture error so idle time is excluded. Kept C++14 compatibility, so `reportIfDue` uses a boolean result plus `FpsSnapshot&` instead of `std::optional`.
- Validation: ROS Foxy `usb_camera` build passed; package tests passed (4/4); clang-format and `git diff --check` passed. On the Orange Pi with divider 2, valid JPEG messages were received and the node reported 23.3 FPS captured / 11.6 FPS published. `/enable_camera` still stopped messages while disabled and resumed publication after enabling.
- Next action: push the refactor commit to PR #20 for review.

## JPEG decoder RGA stride correction — 2026-10-09 (Asia/Shanghai)

- Hardware validation of PR [#21](https://github.com/200166shang/ros-robot/pull/21) showed repeated `RGA_BLIT fail: Invalid argument` for 1280x720 RGB888 frames and no `/camera/image_raw` messages. The source RGA descriptor was receiving MPP's horizontal byte stride (3840) as RGA's pixel stride (which should be 1280 for this frame).
- Updated `rockchip_image_processor.cpp` to validate MPP byte stride separately and pass `mpp_frame_get_hor_stride_pixel()` to RGA. Added a 1280x720 ROS topic-interface regression case. Commit: `c6d772c`.
- Validation on the Orange Pi: the new test reproduced the RGA failure before the fix; after the fix the ROCKCHIP backend built and all 3 topic-interface cases passed, including 1280x720 to 640x360. `clang-format --dry-run --Werror` and `git diff --check` passed. MPP/RGA system-header pedantic warnings remain non-fatal.
- Next action: user reruns the live camera pipeline with the updated PR branch; update PR #21 description when the GitHub API is available.

## JPEG decoder usage documentation — 2026-10-09 (UTC)

- Issue/PR: [#17 Migrate JPEG decoding and scaling to ROS 2](https://github.com/200166shang/ros-robot/issues/17), [PR #21](https://github.com/200166shang/ros-robot/pull/21).
- Updated `ros2_ws/src/img_decode/README.md` with Zsh setup/build commands, OpenCV and MPP/RGA backend selection, the physical-camera launch path, lazy-subscription behavior, topic-rate and image-monitor checks, snapshot saving, node parameters, and a separate-node example for parameter overrides. Kept README instructions aligned with the current launch and node interfaces.
- Validation: checked documented executable names, launch parameters, and node defaults against `CMakeLists.txt`, `camera_decode.launch.py`, and the node sources; confirmed ROS Foxy `ros2 topic echo` does not support `--once` and documented Ctrl+C after receiving a frame instead. `git diff --check` passed. No build or tests were run for this documentation-only change.
- Next action: review and commit the README update, then push it to PR #21 for user review.

## YDLIDAR test and SDK setup documentation — 2026-10-09 (UTC)

- Added Chinese and English `ydlidar/README.md` instructions for the ROS interface test and production hardware-node build. The guide explains that the test uses a fake scan source, needs no physical lidar or vendor SDK, and requires `YDLIDAR_BUILD_HARDWARE_NODE=OFF` because the hardware node is enabled by default. It also documents exposing an installed SDK's CMake config and shared libraries.
- Validation on the Orange Pi: built `ydlidar` with `-DYDLIDAR_BUILD_HARDWARE_NODE=OFF`; `test_ydlidar_ros_interface` passed (1/1), covering scan publication and start/stop services. No physical radar was used. `git diff --check` passed.
- Opened [PR #23](https://github.com/200166shang/ros-robot/pull/23) to publish the README update for review.

## JPEG encoder backend separation — 2026-10-09 (UTC)

- Follow-up to [PR #22](https://github.com/200166shang/ros-robot/pull/22): separated ROS image validation/RGB normalization from JPEG encoding behind a private `JpegEncoderBackend` virtual interface. OpenCV and MPP/RGA adapters now live in separate source files; CMake compiles only the adapter selected by `IMG_ENCODE_BACKEND`. The ROS topic interface and build-time backend choice are unchanged.
- Added Chinese responsibility comments to the interface and named functions, plus a short README architecture note. Removed the generated backend config header, which is no longer needed after CMake selects the adapter source directly.
- Validation: OpenCV build and topic test passed (1/1); MPP/RGA build and topic test passed (1/1); `clang-format --dry-run --Werror` and `git diff --check` passed. A full workspace build was attempted but did not complete: `ydlidar` needs an unavailable `ydlidar_sdkConfig.cmake`; `monitor_interfaces` and `usb_camera` were aborted when the overall build reached its five-minute limit. `rknn_yolov6` also remains excluded from available workspace validation because its external `rknn_api.h` is unavailable.
- Review: Standards found no documented violations or supported smells; Spec found no missing Issue #18 requirements or unasked behavior. Commit `6d3ab6c` contains the refactor. PR [#22](https://github.com/200166shang/ros-robot/pull/22) was merged into `main` as `8d6bc42`, closing Issue #18. No tracking actuation or live camera capture was performed.

## JPEG encoder test instructions — 2026-10-09 (UTC)

- Follow-up to [PR #22](https://github.com/200166shang/ros-robot/pull/22): documented the synthetic ROS topic-interface test and exact OpenCV and MPP/RGA build/test commands in `ros2_ws/src/img_encode/README.md`. The test needs no camera; the MPP/RGA configuration still requires the Rockchip headers and libraries and exercises that hardware encoder path.
- Validation on Orange Pi: the documented package build and topic test passed for OpenCV (1/1) and MPP/RGA (1/1). `git diff --check` passed.
- PR [#22](https://github.com/200166shang/ros-robot/pull/22) was merged into `main` as `8d6bc42`; Issue #18 is closed.

## Issue #19 multi-node load observation — 2026-10-09 (UTC)

- Request: evaluate whether running several decoder nodes under high load affects camera pipeline performance.
- Hardware run: one 1280×720 MJPEG camera input stayed near 29.8 FPS while four OpenCV `img_decode_node` processes ran concurrently on separate output topics. The monitored decoder showed about 1.7 FPS overall (observed windows varied around 0.7–2.3 FPS); single-decoder baseline was about 11.4 FPS. Existing `rosbridge_websocket` remained active at roughly 60–68% CPU, each decoder used about 60–75% CPU, and the 4-core system load average was around 5.9–6.5. This is a loaded-session observation, not a clean idle-board benchmark or MPP/RGA result.
- Cleanup: stopped all camera, decoder, and monitor processes started for this run; restored `/dev/video0` `exposure_auto_priority` to `1` and verified it.
- Updated the Issue #19 report with results and repeatable four-node commands. Next action: commit and push the report/runbook update to PR #24.

## RKNN YOLOv6 ROS 2 migration — 2026-10-10 (UTC)

- Spec: [#25 Migrate RKNN YOLOv6 detector behavior to ROS 2](https://github.com/200166shang/ros-robot/issues/25). Implementation ticket: [#26](https://github.com/200166shang/ros-robot/issues/26), linked as a GitHub sub-issue of #25. The specification remains unchanged.
- Implemented the AArch64 RKNN/RGA backend, two capacity-two drop-oldest worker queues, ROS 2 topic adapters, offline image processing/output, and host Haar fallback in `ros2_ws/src/rknn_yolov6/`. Added external SDK/build/run/test instructions and ADR [0002](docs/adr/0002-rknn-yolov6-ros2-migration.md). Commit `e76d3d6`; PR [#27](https://github.com/200166shang/ros-robot/pull/27) is open for review.
- Validation on the Orange Pi: RKNN/RGA build passed against the installed runtime with official v1.4.0 `rknn_api.h` supplied from `/tmp`; the live ROS topic and offline image-save tests passed with the external model and image (CTest 1/1). Explicit Haar build and its topic/offline tests passed with an external cascade (CTest 1/1). `clang-format --dry-run --Werror`, `git diff --check`, launch Python syntax, and package XML parsing passed. No tracking actuation or source-vendored model, cascade, SDK header, or build output was used.
- Issue #26 has its implementation acceptance checklist checked and remains open until PR review/merge. Next action: review and merge PR #27, then close #26 and audit parent #25.

## RKNN detector backend adapters — 2026-10-10 (UTC)

- Follow-up architecture spec [#28](https://github.com/200166shang/ros-robot/issues/28) is linked as a child of migration spec [#25](https://github.com/200166shang/ros-robot/issues/25); implementation ticket [#29](https://github.com/200166shang/ros-robot/issues/29) is linked as a child of #28. The user confirmed reuse of the existing ROS topic seam for both backend builds and offline checks.
- Implemented the production adapter seam on `codex/issue-29-backend-adapters` at commit `6499217`. The ROS-facing node contains shared topic wiring and two-stage frame flow; CMake selects the RKNN/RGA or Haar adapter. Existing detection algorithms, queue policy, output contract, and offline flow are preserved. ADR 0002 and the package README describe this decision.
- Validation: HAAR build and topic/offline tests passed (2 tests, 0 failures or skips) with external cascade/image assets. RKNN/RGA build and topic/offline tests passed (2 tests, 0 failures or skips) with the installed runtime, external official v1.4.0 SDK header, model, labels, and image. `clang-format --dry-run --Werror` and `git diff --check` passed. Build output contains existing warnings in `postprocess.cpp` and the system RGA header. No tracking actuation was enabled and no external assets or generated build output were added to the worktree.
- Pull request [#30](https://github.com/200166shang/ros-robot/pull/30) is stacked on PR #27's branch and should merge after #27. Keep #29 and #28 open through review; next action is review/merge PR #27, then PR #30.

## Detector adapter PR merge — 2026-10-10 (UTC)

- PR [#30](https://github.com/200166shang/ros-robot/pull/30) was squash-merged into `codex/rknn-yolov6-migration` (the base branch of PR [#27](https://github.com/200166shang/ros-robot/pull/27)) at `cf1070d`. This brings the adapter refactor into the migration PR while leaving its final merge to `main` as a separate review step.
- Implementation ticket [#29](https://github.com/200166shang/ros-robot/issues/29) is closed. Spec [#28](https://github.com/200166shang/ros-robot/issues/28) remains open until PR #27 lands on `main`; its comment records the stacked-PR status. Next action: review/merge PR #27, then close #28 and continue the #25/#26 issue audit.
- Remove the merged PR #30 source branch `codex/issue-29-backend-adapters` after confirming no other open PR uses it. Existing backend build and ROS topic/offline validation evidence remains recorded above; no tests were rerun for the merge operation.
