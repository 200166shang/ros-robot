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

## Future checkpoint format

Record the active issue URL, resolved decisions or ADR links, completed work, validation evidence, open questions, and next action. Replace stale checkpoint details when work advances.
