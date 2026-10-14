# Python style

## Scope and conventions

Read this document before writing, refactoring, or reviewing Python in this
repository. Follow [PEP 8](https://peps.python.org/pep-0008/), with repository and
explicit task requirements taking precedence. Preserve external contracts and
Python compatibility when applying style changes.

Write agent-facing style documents in English. Keep code comments and docstrings
in Chinese as required by the existing repository and issue conventions; this
document changes the language of the instructions, not the code documentation.

## Business flow and responsibilities

- Keep the main call chain readable as business steps. Group functions by runtime
  role or lifecycle stage and separate logical stages with semantic blank lines.
- Split parsing, business validation, execution, and reporting where their
  responsibilities differ. Keep coherent work together rather than extracting
  helpers to meet a line-count target.
- Use descriptive business names and named fields for persistent records. Use
  dataclasses or other small record types when they clarify real concepts;
  ordinary local values do not need their own types.
- Keep necessary parsing and parameter-binding complexity at input or Adapter
  boundaries. Validate untrusted data there, then use the established contract
  internally. Introduce abstractions for actual behavior variation.
- Prefer straightforward functions and control flow. Share repeated behavior when
  doing so makes the callers easier to understand.

## Interfaces, errors, and lifecycle

- Annotate public Interfaces and make ordering, failure, and timeout semantics
  explicit. Test observable behavior through the same Interface used by callers.
- Keep protected `try` blocks focused on operations whose errors they classify.
  Separate external I/O failures from validation, record updates, and reporting.
- Preserve execution facts when later stages fail. Once an action is submitted,
  report its known outcome or uncertainty and retain the remaining action list.
- Distinguish a wait timeout, an in-flight call, and a confirmed device outcome.
  A thread finishing is not itself device confirmation. Keep explicit recovery
  rules for uncertain actions, and preserve the agreed no-retry/no-overlap rules.
- Prefer standard concurrency primitives to custom notification protocols. Keep
  turn ownership and device uncertainty separate from transport mechanics.

## Comments and layout

- Give modules and named functions, including constructors and entry points,
  concise Chinese docstrings explaining their responsibility or contract.
- Explain intent, resource ownership, handoffs, and non-obvious constraints.
  Update comments when behavior changes and avoid repeating the code's wording.
- Use consistent numbered comments at key stages of multi-stage business flows;
  simple functions do not need artificial stage numbering.
- Put unconditional imports at the module top, grouped as standard library,
  third-party dependencies, and local application modules. Document any actual
  need for a deferred import.
- Use four-space indentation, snake_case functions and variables, CapWords types,
  and UPPER_CASE constants. Use implicit continuation for multiline expressions.

## Formatting and review

The root `pyproject.toml` is the source of truth for Ruff settings, including the
Python target, line widths, lint rules, import classification, and file scope.
PEP 8 is implemented through those settings and manual review, not a single
formatter mode.

Run `ruff format` on changed files, then `ruff format --check` and `ruff check`.
Check that the changed files are included in the configured scope; extend that
scope intentionally when adding modules. Review the diff for business flow,
exception classification, semantic grouping, and useful comments. Run behavior
and type checks appropriate to the change. A formatter passing is one part of
review, not evidence that the design is readable or correct.
