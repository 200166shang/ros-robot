# C++ style

- Keep the main call chain easy to follow. Group related functions by runtime role or lifecycle stage, and group member variables by purpose and ownership.
- Separate distinct logical blocks with blank lines, such as parameter reading, validation, conversion, setup, execution, and reporting. Keep statements in the same step together.
- Add a brief Chinese comment above each named function, including constructors, destructors, and entry points, to explain its responsibility. Use inline comments for important reasons, handoffs, ordering constraints, and resource ownership.
- For logic with multiple processing stages or consecutive function calls, use numbered comments such as `1.` and `2.` at key call sites to explain the execution order, each step's purpose, and how data flows to the next step. Keep the numbering consistent with the actual call chain; do not force numbering onto simple functions.
- When commenting formulas, explain their purpose, the meaning of each symbol, the coordinate frame and units, and what the result represents. Also document important assumptions, boundary handling, or clamping.
- Use comments to explain intent, handoffs between steps, and the basis for calculations; avoid restating code line by line. Update comments when the code flow changes.
- Name validation conditions or intermediate steps when that makes their meaning easier to scan. Apply the repository `.clang-format` and preserve semantic grouping in the formatted code.
- Split functions by meaningful work. Keep coherent flows together and avoid adding indirection or types solely to shorten functions or make the file look more layered.

## Formatting and verification

Use the root `.clang-format` as the formatting source of truth. Format changed C++ files, inspect semantic grouping after formatting, and run the relevant build and behavior checks. Keep unrelated files outside the formatting change.
