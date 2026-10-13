# Repository instructions

## Development

Work from the issue's scope and acceptance criteria. For module design or restructuring, apply `codebase-design`: keep the Interface small, concentrate behaviour in the Implementation, and introduce a Seam where behaviour actually varies. Test observable behaviour through the Interface. Keep ROS wiring and hardware-specific Adapters at the edges.

Keep tracking in dry-run mode unless the user explicitly authorizes hardware actuation. Keep model weights, recordings, proprietary SDK headers, credentials, and generated build output outside source commits.

### C++ readability and review

- Keep the main call chain easy to follow. Group related functions by runtime role or lifecycle stage, and group member variables by purpose and ownership.
- Separate distinct logical blocks with blank lines, such as parameter reading, validation, conversion, setup, execution, and reporting. Keep statements in the same step together.
- Add a brief Chinese comment above each named function, including constructors, destructors, and entry points, to explain its responsibility. Use inline comments for important reasons, handoffs, ordering constraints, and resource ownership.
- For logic with multiple processing stages or consecutive function calls, use numbered comments such as `1.` and `2.` at key call sites to explain the execution order, each step's purpose, and how data flows to the next step. Keep the numbering consistent with the actual call chain; do not force numbering onto simple functions.
- When commenting formulas, explain their purpose, the meaning of each symbol, the coordinate frame and units, and what the result represents. Also document important assumptions, boundary handling, or clamping.
- Use comments to explain intent, handoffs between steps, and the basis for calculations; avoid restating code line by line. Update comments when the code flow changes.
- Name validation conditions or intermediate steps when that makes their meaning easier to scan. Apply the repository `.clang-format` and preserve semantic grouping in the formatted code.
- Split functions by meaningful work. Keep coherent flows together and avoid adding indirection or types solely to shorten functions or make the file look more layered.

### Python 代码规范

本项目 Python 代码遵循 PEP 8、PEP 257 和现代 Python 类型注解规范；类型注解须兼容项目使用的 Python 版本。

1. 使用 Ruff Formatter 统一格式，行宽 160，4 空格缩进，双引号。
2. 使用 Ruff Linter 检查代码质量与导入排序，遵循项目 `pyproject.toml`。
3. 新增函数应包含参数和返回值类型注解；公共接口应具有简洁的 Docstring。
4. 导入顺序为标准库、第三方库、项目内部模块。
5. 字典、列表和复杂函数调用采用清晰的多行格式，不人为压缩代码。
6. 优先使用 `pathlib`、上下文管理器、f-string 和 Python 标准惯用写法。
7. 按职责拆分函数，但避免不必要的抽象类、设计模式和过度封装。
8. 配置、网络请求、响应解析和业务逻辑尽量分离。
9. 保持现有功能、异常语义和安全约束，不因格式重构改变行为。
10. 提交前运行 `ruff check .`、`ruff format --check .`，以及项目配置的类型检查和测试。

原则：代码应简洁、直观、易于阅读和维护，优先遵循项目现有架构，不为形式上的工程化增加复杂度。

## Agent skills

### Issue tracker

Track work and specifications in GitHub Issues for `200166shang/ros-robot`. Before reading, creating, updating, or closing tickets, read `docs/agents/issue-tracker.md`.

### Triage labels

Use the five canonical triage labels. Before classifying issues, read `docs/agents/triage-labels.md`.

### Domain docs

Use a single-context layout: root `GLOSSARY.md` and `docs/adr/`. Before exploring domain terms or changing module design, read `docs/agents/domain.md`.
