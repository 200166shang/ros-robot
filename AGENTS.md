# Repository instructions

## Development

Work from the issue's scope and acceptance criteria. For module design or restructuring, apply `codebase-design`: keep the Interface small, concentrate behaviour in the Implementation, and introduce a Seam where behaviour actually varies. Test observable behaviour through the Interface. Keep ROS wiring and hardware-specific Adapters at the edges.

Read `CONTEXT.md` when starting work or resuming a handoff. Confirm its current-state claims against source and GitHub before relying on them. Update it at a task checkpoint with the issue, decisions, validation evidence, and next action.

Keep tracking in dry-run mode unless the user explicitly authorizes hardware actuation. Keep model weights, recordings, proprietary SDK headers, credentials, and generated build output outside source commits.

### C++ readability and review

- Keep the main call chain easy to follow. Group related functions by runtime role or lifecycle stage, and group member variables by purpose and ownership.
- Separate distinct logical blocks with blank lines, such as parameter reading, validation, conversion, setup, execution, and reporting. Keep statements in the same step together.
- Add a brief Chinese comment above each named function, including constructors, destructors, and entry points, to explain its responsibility. Use inline comments for important reasons, handoffs, ordering constraints, and resource ownership.
- Name validation conditions or intermediate steps when that makes their meaning easier to scan. Apply the repository `.clang-format` and preserve semantic grouping in the formatted code.
- Split functions by meaningful work. Keep coherent flows together and avoid adding indirection or types solely to shorten functions or make the file look more layered.

## Agent skills

### Issue tracker

Track work and specifications in GitHub Issues for `200166shang/ros-robot`. Before reading, creating, updating, or closing tickets, read `docs/agents/issue-tracker.md`.

### Triage labels

Use the five canonical triage labels. Before classifying issues, read `docs/agents/triage-labels.md`.

### Domain docs

Use a single-context layout: root `GLOSSARY.md` and `docs/adr/`. Before exploring domain terms or changing module design, read `docs/agents/domain.md`.
