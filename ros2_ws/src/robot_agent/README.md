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
await execution in order, then record the actual reply and explicitly await a
tool-disabled summary when needed. The Agent has no audio dependency.
`ActionExecution` owns
submitted device operations, unknown results, and explicit reconciliation. Model
or summary calls still in flight block a new request; an unknown action blocks
new actions until the original receipt is explicitly reconciled.

`AgentApplication.run` is the only continuous voice orchestration. The ROS node
wires result publication and lifecycle to it; it has no second listen/turn loop.
`voice/runtime.py` recognizes a standalone WAV before reusing
`submit_transcript(direct=True)`. Direct mode bypasses wake and music rules and
retains the existing result JSON and simulated device behavior.

`DashScopeProvider.complete(text, deadline, tools=...)` uses HTTPX native async
HTTP/SSE and owns its response and client resources. Agent owns the single model
attempt task through cancellation cleanup. The default three attempts share one
phase deadline (`model_attempts` accepts 1–5); only classified transient transport failures retry, before actions have
been submitted and after the previous attempt is fully closed. Invalid protocol,
Schema and permanent configuration failures do not retry. A timed-out or cancelled
model result cannot execute actions or apply a late summary.

`ActionRegistry.invoke(command, deadline)` and `ActionExecution.execute(plan,
turn_id)` are native async Interfaces. Instant simulations run in the event loop;
async device implementations are awaited directly. Perception actions await native
ROS receipt delivery without a blocking worker or nested spin. Execution retains
the original operation Task when a wait expires or its caller is cancelled. A completed `unknown` receipt
still blocks admission; `reconcile(turn_id)` only checks that original operation.
Unexpected action/report errors carry `ActionExecutionError.result` and preserve
the original exception as the cause. `Agent.last_result` also retains confirmed
or submitted facts when later memory or programming errors propagate.

Normal microphone input uses native async PCM and continuous ASR. The temporary
`legacy_io.py` Adapters still own blocking WAV input and speech output.
`AgentApplication.aclose(deadline)` closes speech and the Agent, retaining action
receipt delivery within the remaining deadline. Native WAV/output I/O and a
configurable total budget across all resources remain subsequent migration steps.
The model Adapter owns bounded JSON/SSE assembly and returns a complete `ModelReply`.
It exposes one native `execute_actions` tool; ordinary chat is plain model text.
Summaries explicitly disable tools and use one attempt with a separate phase
budget. `actions/contracts.py` declares small strict
Pydantic input models; `ActionRegistry.tool_schema` and `bind_plan` share these
models for Schema, validation and defaults. The catalog preserves aliases, order
and repeats. An invalid final item prevents every action from executing. Internal
`invoke(command, deadline)` passes a deadline to waiting device implementations;
no execution deadline appears in model parameters. Device receipt dictionaries
exist only at device Adapters; the registry returns an `ActionReceipt`.
`ExecutionResult.tool_call_id` keeps the native call associated with execution
and reconciliation without changing the external result JSON. The memory stores
plain exchanges, so it does not persist unpaired native tool messages.
The ROS entry owns the asyncio main loop and explicitly starts `RosExecutor`'s
dedicated thread. Constructing `OnlineVoiceRosNode` only wires ROS; `run()` starts
the shared microphone application. The ROS Adapter retains each original rclpy
Future and transfers its receipt with `loop.call_soon_threadsafe`. A business
wait timeout never cancels that Future or removes the pending service request.
Compound actions share one absolute deadline: a late partial confirmation may
update facts, but cannot submit a later service, camera publication, or plan item.
Camera publication remains a request without device state confirmation.
`Agent.aclose(deadline)` waits for original action completion and records available
facts before the ROS Adapter detaches; `RosPerception.aclose(deadline)` then drains
or disconnects local receipt delivery before `RosExecutor.aclose(deadline)` stops
its thread. Ending local waiting cannot establish device cancellation. Executor
callback errors propagate to the main loop. The current entry uses a five-second
shutdown allowance; configurable total-budget persistence belongs to the shutdown
migration.

Memory storage owns bounded data and atomic persistence; it has no callback that can invoke a model. Clear/new turn
admission stays blocked while summary cleanup is in flight, so retired summaries
cannot write after a successful clear.

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
