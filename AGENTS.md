# Repository instructions

## Development

Work from the issue's scope and acceptance criteria. For module design or restructuring, apply `codebase-design`: keep the Interface small, concentrate behaviour in the Implementation, and introduce a Seam where behaviour actually varies. Test observable behaviour through the Interface. Keep ROS wiring and hardware-specific Adapters at the edges.

Keep tracking in dry-run mode unless the user explicitly authorizes hardware actuation. Keep model weights, recordings, proprietary SDK headers, credentials, and generated build output outside source commits.

### Avoid speculative defensive programming

Implement documented contracts directly. Add guards, fallback values, retries,
and exception handling only for specified failure modes or observed failures.
Validate untrusted input at external boundaries, then trust the established
contract internally instead of repeating type, null, or range checks. Let
unexpected programming errors surface rather than silently replacing them with
defaults or success. Keep required safety checks and explicit recovery rules;
every defensive branch must have a concrete reason in the specification or
failure evidence.

### Language-specific style

Before writing, refactoring, or reviewing Python, follow PEP 8 and read
[Python style](docs/agents/python-style.md). Before writing, refactoring, or
reviewing C++, read [C++ style](docs/agents/cpp-style.md). For mixed changes,
read both. The language documents define readability and review requirements;
`pyproject.toml` and `.clang-format` define the formatter settings.

## Agent skills

### Issue tracker

Track work and specifications in GitHub Issues for `200166shang/ros-robot`. Before reading, creating, updating, or closing tickets, read `docs/agents/issue-tracker.md`.

### Triage labels

Use the five canonical triage labels. Before classifying issues, read `docs/agents/triage-labels.md`.

### Domain docs

Use a single-context layout: root `GLOSSARY.md` and `docs/adr/`. Before exploring domain terms or changing module design, read `docs/agents/domain.md`.
