# Phase A: Web Text Interaction, Turn Status, and Browser TTS

Date: 2026-09-25
Implementation branch: `feature/robot-capability-simulation`
Board workspace: `/home/orangepi/code/ros-robot`

This is an implementation record for the first milestone in
`robot-capability-simulation-roadmap.md`. Code and board build are complete for
the software path; real-model inference and Mac listening are still pending.

## Run it

On Orange Pi, from the project root:

```bash
./scripts/run-demo.sh --check-only
./scripts/run-demo.sh
```

On Mac, in a second terminal from a Mac checkout of this repository:

```bash
./scripts/open-ui.sh
```

Then open `http://127.0.0.1:18081/`. Enter a text prompt. After the response
appears, choose “生成语音” and use the browser's audio controls to play it.
The board process owns Qwen and ROS; the Mac script only owns the SSH tunnel.

Normal mode does not automatically replay the fixed WAV or inject synthetic
detections. For the repeatable software probe only, use
`./scripts/run-demo.sh --acceptance` on the board. That profile forces the
recorded WAV source and is not a real-person detection acceptance test. Tracking
remains `dry_run=true`.

## Flow and topics

| Step | Component | Contract |
|---|---|---|
| Submit | Browser → Flask | `POST /api/turn`, text limited to 4,000 characters |
| Correlate | Web node → Qwen ROS bridge | `/llm/turn/request`, JSON schema version 1 with `run_id` and `turn_id` |
| Infer/act | Qwen ROS bridge | `/llm/turn/event`: inference, optional approved command execution, terminal result |
| Render | Browser | Poll `/api/turn/<turn_id>`; show result, stage, elapsed time and error code |
| Speak | Browser → voice node | Explicit `POST /api/turn/<turn_id>/audio` → `/voice/web_tts_request` |
| Play | Mac browser | Fetch one correlated WAV through `GET /api/turn/<turn_id>/audio`; playback is user-triggered |

The existing voice capture route remains on `/llm/user_input` and
`/llm/response`. Tagged web turns do not publish their result on the legacy
response topic, so they cannot satisfy another voice request accidentally.
Only the existing function allowlist is available; unknown functions fail
closed. The real Agent is not replaced by this text adapter.

## Logs and privacy

Each web-node run gets a new ID. The board stores
`local-data/ros-robot/runs/<run_id>/manifest.json` and `events.jsonl`.
The manifest declares `content_logging=false`; event rows contain bounded
stage/status/time/error/command metadata, not user prompts or model replies.
Recent turn contents remain in process memory for the UI.

Requested TTS files are stored under
`local-data/ros-robot/web-audio/<run_id>/<turn_id>.wav`. They are not in Git,
but currently have no automatic retention/cleanup policy. Treat them as user
data and remove them only when their exact run/turn paths are known.

The web process defaults to `127.0.0.1`, and the existing launch config also
uses loopback. Access it through the Mac SSH tunnel; do not expose port 8080 to
the public Internet. If the Qwen ROS bridge has no subscriber, the API returns
503 before creating a turn, avoiding a permanently busy UI.

## Implementation and verification

Changed areas:

- `robot_agent/llm_ros_node.py`: versioned request/event channel; keeps the
  legacy voice path separate.
- `web_video_server/web_video_node.py`, `turn_store.py`, and
  `templates/index.html`: web conversation, bounded in-memory turns,
  metadata-only event records, progress UI, and explicit WAV endpoint.
- `robot_voice/voice_frontend_node.py` and launch file: versioned browser TTS
  requests; reuse the existing Sherpa adapter and avoid ALSA playback in this
  web path.
- `scripts/demo_launcher.py` and bringup launch: interactive default versus
  explicit fixed-WAV/synthetic-detection acceptance profile.
- Tests and operational documentation updated.

Verified on the board:

- `python3 -m unittest discover -s tests -v`: 20 tests passed.
- Modified Python modules and the launch file passed `py_compile`.
- Both `--check-only` profiles passed without launching services; microphone
  plus environment-enabled acceptance was correctly rejected.
- `colcon --log-base log build --packages-select robot_agent robot_voice web_video_server robot_bringup --executor sequential --parallel-workers 1`: all four packages built and installed in the project workspace.
- `ros2 launch robot_bringup person_tracking_demo.launch.py --show-args` reports
  `run_acceptance_probe=false` by default.
- ROS domain 157 smoke checks used a fake Qwen client and fake Agent response:
  a normal web turn correlated correctly; an unapproved function was rejected;
  an explicitly allowed `start_tracking` received a correlated fake success.
  No camera, NPU, motor consumer, or real Agent participated.
- Flask/API smoke verified disconnected-bridge 503 without a stuck turn,
  single-flight behavior, versioned ROS messages, metadata-only event logs, and
  the browser WAV route.
- Voice callback smoke used a fake synthesizer that wrote placeholder bytes.
  It did not run Sherpa inference or create audible audio.

A full clean rebuild of `rknn_yolov6` was not possible because the board does
not have the external Rockchip SDK header `rknn_api.h` in the standard search
paths. Its existing installed package was used as an underlay; no SDK or model
asset was downloaded or replaced. A clean-room rebuild of that package is a
separate environment task.

## Not yet demonstrated

- Real Qwen inference through the browser.
- Actual Sherpa TTS synthesis and listening from the Mac browser.
- Live camera/NPU pipeline with this web chat session.
- Real Agent/camera acknowledgement from the new tagged text path.
- Any physical motion. Keep `dry_run=true`.

Next: run the normal start + Mac tunnel when the operator is present, ask one
ordinary text question, explicitly synthesize/play its reply, and inspect the
run metadata. Then continue with Phase B (expressions/virtual head) or Phase C
(virtual base), without making more benchmark work a prerequisite.
