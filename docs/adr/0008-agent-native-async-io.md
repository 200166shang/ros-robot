---
status: accepted
---

# Move Agent I/O to native async implementations in stages

The Agent's module split still leaves readers assembling business flow and
thread lifecycles across files. Keep the `conversation`, `actions`, `voice`,
and `ros` groups, establish explicit business Interfaces, and concentrate
application assembly and lifecycle ownership at a clear entry point.

Let `AgentApplication` orchestrate a voice turn across speech input, session
rules, the Agent, and speech output. Speech input and output are peers of the
Agent; they do not invoke it. Keep the Agent independent of audio and ROS
entry wiring. Use `Agent` as the target name for the existing
`OnlineInteraction` responsibility: model requests, action validation and
execution, and conversation memory, rather than only a model API client.

Move turn orchestration, half-duplex handoffs, and application cleanup out of
`OnlineVoice` into `AgentApplication`, then remove the old orchestration class.
Keep wake/sleep rules, silence timing, and conversation filtering in a concrete
session module with no Agent or I/O calls. Application processing state belongs
to the application; session state belongs to the session rules. The application
supplies observed capability state needed for decisions, such as whether music
is playing, rather than making session rules query the Agent.

Put `AgentApplication` in `application.py` and keep configuration and dependency
assembly in root `runtime.py`. Rename `conversation/interaction.py` to
`conversation/agent.py` as its responsibility migrates. Provide three reading
entries: `AgentApplication.submit_transcript` for a voice turn, `Agent.submit`
for model/action/memory flow, and `ActionExecution.execute` / `reconcile` for
device facts. Keep the WAV command and ROS entry thin and reuse common assembly.

Use concrete classes for application orchestration, session rules, the Agent,
and execution. Introduce small Protocols at actual model, speech, and device
Seams rather than a shared stage abstraction or general workflow framework.
Keep model, parameter-binding, execution, and output complexity behind their
respective Interfaces rather than exposing Futures or callbacks to the caller.

Target native asynchronous network and audio I/O, migrating in stages with
Interface, result-record, and main-flow improvements first. Wrapping blocking
Adapters in executor calls may support migration, but is not the final design:
it retains the underlying worker threads. Preserve the system Python 3.8 and
ROS 2 Foxy constraint from ADR 0007.

Expose I/O-waiting business operations as async Interfaces; keep validation
and state decisions synchronous. Callers await these operations directly.
Represent cross-stage data with named records such as `ModelReply`,
`ActionOutcome`, `ExecutionResult`, `TurnResult`, and `VoiceRecord`, converting
them to the existing JSON representation when publishing or saving. Returned
results retain snapshot semantics when later reconciliation updates the
execution facts.

Data progresses from an untrusted `ModelReply` through a fully bound
`ActionPlan`, then `ExecutionResult`, `TurnResult`, and `VoiceRecord`. The voice
record composes the turn result with input/output facts; speech, playback,
memory, or recording failures cannot rewrite confirmed device facts. Copy or
freeze nested data as well as the enclosing record to preserve snapshots.

Use native tool/function calling with JSON Schema for model-requested actions
instead of model-authored Python-call strings embedded in response text.
Schema and tool declarations belong at the model and action Interfaces;
application-side argument and business validation remain required. Provider
support for schema enforcement must be verified for the deployed model and
endpoint rather than inferred from OpenAI compatibility.

Expose one native `execute_actions` tool whose arguments contain an ordered
action plan. Each action retains its own argument schema. Collect the complete
tool request and validate the entire plan before submitting any action;
execute in order and stop on failure or uncertainty. This preserves the
existing whole-list validation contract instead of letting a model choose
and execute one action at a time in an open-ended tool loop.

Prefer small action input models as the common source for schema generation,
parameter validation, and default binding, subject to the Python 3.8 / ARM64
dependency check. Keep ordinary business results as simple records. For the
first implementation, retain deterministic replies from action receipts and
model text for ordinary conversation; do not add a second model call solely
to phrase the action result. Preserve tool-call correlation when storing
native protocol messages.

Separate model-visible action-argument binding from internal invocation.
Pass the execution deadline explicitly to invocation without making it a
model-visible argument. Preserve existing action names, parameters, defaults,
and aliases.

Classify concrete transport exceptions within Adapters and report expected
failures through explicit business results. Unexpected programming errors
surface after preserving submitted-action facts and performing necessary
cleanup. Give each retry policy one owner and bound attempts by a total time
budget. A transient model request may be retried only before any action is
submitted and after the previous attempt has ended or completed local
cancellation cleanup. Retain bounded ASR reconnection without audio replay
and bounded TTS retries without re-running the model or actions. Do not retry
invalid schemas, permanent configuration failures, entire turns, or submitted
device actions automatically.

Use shutdown with a configurable total time budget: stop accepting turns and
submitting actions, retain receipt delivery while waiting within the remaining
budget, then release local tasks and resources. Record confirmed outcomes and
any remaining uncertainty through existing turn records and diagnostics;
surface recording failures. Local cancellation does not establish device
cancellation. Keep cross-process action recovery and replay outside this
refactor.

Use an asyncio main loop and an explicitly managed ROS executor thread.
Application state is owned by the event loop; ROS Adapters deliver receipts
through thread-safe scheduling. Input owns its capture and recognition tasks,
the model Adapter owns request resources, and action execution retains pending
operations. Keep ROS receipt delivery alive until action cleanup ends. This
defines ownership, not a fixed total thread count. Concrete dependencies and
runtime integration remain subject to Python 3.8 / ARM64 compatibility checks.

Retain the existing single-turn behavior, model-call non-overlap, action
uncertainty and explicit reconciliation, and ASR input pause semantics.
Changing how an operation is awaited must not change what is known about its
execution. Hardware safety settings remain unchanged.
