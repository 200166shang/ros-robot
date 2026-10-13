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

### Python 工程化开发规范

目标：编写清晰、可理解、可维护、可扩展的 Python 代码，让开发者快速理解主流程、定位业务逻辑、修改功能和排查问题。遵循 PEP 8、PEP 257 和 Google Python Style Guide，以项目现有规范与架构为优先。优先可读性，其次合理复用，再考虑未来扩展。

#### 代码组织和文件布局

- 先识别业务输入、输出和主流程，再拆分实现。入口负责启动、依赖组装和必要的错误处理；主流程应直接表达业务步骤，具体算法放在对应职责的实现中。
- 按业务职责组织模块，相近逻辑集中，文件名表达用途。按实际需要组织文件和目录，不机械地为每个类创建文件，也不提前建立复杂层级。
- 文件通常依次放置模块说明与 Imports、常量与类型/数据结构、公开主要函数或类、内部辅助函数。复杂类按初始化、公共方法、相关内部方法排列，让读者先看到能力，再看到实现。
- 保持依赖方向清楚，避免循环依赖、跨模块修改可变全局状态。

#### 函数、命名和可读性

- 一个函数完成一个可描述的职责，函数名优先表达业务意图。函数混合多种职责、嵌套复杂或难以测试时再拆分，不强制行数；避免只为缩短代码提取简单转发函数或增加无意义调用层级。
- 相关辅助函数相邻放置，异常条件优先提前返回，保持正常流程清晰。
- 函数和变量用 snake_case，类用 PascalCase，常量用 UPPER_SNAKE_CASE。名称表达业务含义，复杂中间结果和条件使用有语义的变量名。
- 字典、列表和复杂调用采用清晰的多行布局；避免嵌套三元表达式、过度复杂的推导式和人为压缩代码。张量、图像、音频等数据必要时说明 Shape、格式、单位和坐标系。
- 优先采用 pathlib、上下文管理器、f-string 和 Python 标准惯用写法。

#### 抽象、数据和模块边界

- 优先使用简单函数和模块；类用于管理状态、资源或生命周期。稳定字段的数据结构可用 dataclass；现有 JSON 字典契约可用 TypedDict 保持表示与兼容性。
- 只有真实的多实现需求或测试隔离需求才引入接口/Protocol。抽象应降低理解成本，避免假想需求的继承体系、无附加语义的包装，以及没有实际价值的 Manager、Factory、Base、Wrapper。
- 尽量分离配置读取、网络请求、响应解析和业务逻辑，纯计算与外部 I/O 分离；优先复用合理的已有逻辑。

#### 注释、类型和错误处理

- 简单代码依靠命名表达；注释解释设计原因、业务约束和非直观行为，不逐行复述代码。公开接口、复杂算法、有副作用的函数提供必要且简洁的 Docstring，复杂算法说明输入输出、关键公式和边界条件。
- 中文讲解优先使用中文注释，代码标识符仍用英文；注释与实际行为保持一致。
- 新增函数提供参数和返回值类型注解，特别明确公开函数、关键业务函数和模块边界。使用明确类型，Any 仅限未校验的外部动态数据等必要位置；注解兼容项目 Python 版本。
- 在合适的边界验证输入和配置；在可恢复、可转换或可补充上下文处处理异常。避免随意吞掉异常或用大范围 except Exception 掩盖实现错误。
- 如外部 provider/device Adapter 必须隔离任意第三方异常，将捕获范围限定到外部调用，说明恢复语义并提供可观察失败；日志记录安全的业务上下文，不泄露凭证，不重复记录同一异常。
- 保持现有功能、异常语义和安全约束，格式及局部重构不得改变行为。

#### 工具和验证

- 遵循 pyproject.toml：Ruff Formatter 行宽160、4空格缩进、双引号；Ruff Linter 检查质量与导入排序，导入按标准库、第三方库、项目内部模块组织。
- 对核心业务逻辑通过既定 Interface 编写 pytest 测试，覆盖正常路径、边界输入与错误路径。必要时用 Mock/Fake 隔离硬件、网络、文件和模型等外部依赖。
- 提交前运行 ruff check .、ruff format --check .，以及项目配置的类型检查和适用测试。若全仓存在改动范围之外的存量问题，报告范围和实际失败，不掩盖或声称检查全绿。
- 只报告实际执行的验证；局部简化完成后确认原有行为与安全约束仍满足。

#### Agent 开发流程与完成审查

1. 阅读项目结构和相关模块，明确输入、输出及主要执行流程。
2. 确定功能归属的已有模块，优先复用合理逻辑，用最简单清晰的方案实现。
3. 检查职责、模块边界和命名，局部简化过度抽象、重复逻辑、复杂嵌套与不必要调用层级。
4. 编写必要测试并执行适用检查。
5. 审查入口是否易找、主流程是否可独立理解、数据契约是否明确、相关逻辑是否集中、功能修改是否涉及无关文件，以及核心逻辑是否易于独立测试。
6. 确认原有行为与相关验证通过，总结改动、关键调用流程、验证结果和未完成项。

不要为了抽象而抽象，不要为了拆分而拆分；能够运行但明显增加理解和维护成本的代码应优先局部简化。

## Agent skills

### Issue tracker

Track work and specifications in GitHub Issues for `200166shang/ros-robot`. Before reading, creating, updating, or closing tickets, read `docs/agents/issue-tracker.md`.

### Triage labels

Use the five canonical triage labels. Before classifying issues, read `docs/agents/triage-labels.md`.

### Domain docs

Use a single-context layout: root `GLOSSARY.md` and `docs/adr/`. Before exploring domain terms or changing module design, read `docs/agents/domain.md`.
