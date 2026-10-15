# Robot Agent reading guide

Start with `robot_agent/runtime.py:build_application`. It interprets shared
configuration, selects microphone or recording Adapters, and connects the same
music capability to both action execution and session observations. Normal ROS
operation selects the microphone; the independent WAV command selects recording.

Read one voice turn in `AgentApplication.submit_transcript` in
`robot_agent/application.py`: admit the turn, pause real audio, ask `VoiceSession`
for a local decision, await `Agent.submit` when needed, await output and recording,
and restore input in `finally`. The application owns processing and closed state.
`VoiceSession` owns wake state and activity time; it receives text, time, and a
music observation and performs no I/O. Idle input waits advance silence timing;
processing time does not put an active session to sleep.

Read a text turn in `Agent.submit` in `robot_agent/conversation/agent.py`: obtain
memory context, await a complete `ModelReply`, bind the whole native plan,
execute in order, then update memory. The Agent has no audio dependency. `ActionExecution` owns
submitted device operations, unknown results, and explicit reconciliation. Model
or summary calls still in flight block a new request; an unknown action blocks
new actions until the original receipt is explicitly reconciled.

`AgentApplication.run` is the only continuous voice orchestration. The ROS node
wires result publication and lifecycle to it; it has no second listen/turn loop.
`voice/runtime.py` recognizes a standalone WAV before reusing
`submit_transcript(direct=True)`. Direct mode bypasses wake and music rules and
retains the existing result JSON and simulated device behavior.

The temporary `legacy_io.py` Adapters own the still-blocking operations. Each
Agent owns model, execution, and memory call handles; the application owns speech
input and output Adapters. A wait ending does not cancel an underlying operation.
The model Adapter owns JSON/SSE assembly and returns a complete `ModelReply`.
It exposes one native `execute_actions` tool; ordinary chat is plain model text.
Summaries explicitly disable tools. `actions/contracts.py` declares small strict
Pydantic input models; `ActionRegistry.tool_schema` and `bind_plan` share these
models for Schema, validation and defaults. The catalog preserves aliases, order
and repeats. An invalid final item prevents every action from executing. Internal
`invoke(command, deadline)` passes a deadline to waiting device implementations;
no execution deadline appears in model parameters. Device receipt dictionaries
exist only at device Adapters; the registry returns an `ActionReceipt`.
`ExecutionResult.tool_call_id` keeps the native call associated with execution
and reconciliation without changing the external result JSON. The memory stores
plain exchanges, so it does not persist unpaired native tool messages.
Native network/audio I/O and a total shutdown budget are subsequent migration
steps; the accepted `aclose(deadline)` shape does not yet impose that total
budget. The ROS edge temporarily hosts the asyncio
loop in its managed business thread while the ROS executor delivers receipts.

`robot_agent/results.py` defines `ModelReply`, `ActionReceipt`, `ActionOutcome`,
`ExecutionResult`, `TurnResult`, and `VoiceRecord`. A voice record composes its
`turn` with transcript, session, synthesis, playback, audio and save status.
Records freeze nested parameters and device data as well as the action sequence.
Reconciliation creates a new execution and turn snapshot; it never rewrites an
old result or executes the remaining actions. Pending transcripts remain
available even if the first record save failed. `result_to_json` runs only at saving,
publication, and command output to preserve the existing flat JSON fields.

Failures in output do not rerun model requests or actions. Expected speech and
storage errors retain execution facts in the existing record fields. Unexpected
speech implementation errors propagate after input and processing cleanup.
Closing rejects new turns, cancels output retries, closes speech resources, and
prevents a finishing turn from restoring closed input. Tracking remains dry-run.

For deployment and existing JSON fields, see [the operation guide](../../../docs/online-agent.md)
and [voice behavior](../../../docs/online-agent-voice.md). Deterministic tests use
external model, device, and speech Adapters; they are not cloud or hardware
acceptance evidence.
