# Domain docs

## Consumer rules

Before exploring a domain or designing a module, read root `GLOSSARY.md` if present and the ADRs in `docs/adr/` relevant to the change.

If these documents do not exist, proceed with the task. Use `domain-modeling` to create entries when terms or architectural decisions have actually been resolved.

Use the glossary's vocabulary in issues, specifications, code, and tests. If a proposed change contradicts an ADR, identify the conflict and explain why that decision should be revisited.

## Layout

This repository uses a single context even though ROS packages live under `ros2_ws/src/`.

- `GLOSSARY.md`: agreed domain terms.
- `docs/adr/NNNN-short-title.md`: architectural decisions, including context, decision, and consequences.

`CONTEXT.md` holds task checkpoints and pointers. Persistent domain definitions belong in the glossary; architectural decisions belong in ADRs; scope and acceptance criteria belong in GitHub Issues.
