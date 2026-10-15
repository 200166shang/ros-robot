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
memory context, await the model, validate the whole action list, execute in order,
then update memory. The Agent has no audio dependency. `ActionExecution` owns
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
The old protocol, audio Implementation, retries, playback, and record writing are
reused. Native network/audio I/O, typed result internals, and a total shutdown
budget are subsequent migration steps; the accepted `aclose(deadline)` shape does
not yet impose that total budget. The ROS edge temporarily hosts the asyncio
loop in its managed business thread while the ROS executor delivers receipts.

Failures in output do not rerun model requests or actions. Expected speech and
storage errors retain execution facts in the existing record fields. Unexpected
speech implementation errors propagate after input and processing cleanup.
Closing rejects new turns, cancels output retries, closes speech resources, and
prevents a finishing turn from restoring closed input. Tracking remains dry-run.

For deployment and existing JSON fields, see [the operation guide](../../../docs/online-agent.md)
and [voice behavior](../../../docs/online-agent-voice.md). Deterministic tests use
external model, device, and speech Adapters; they are not cloud or hardware
acceptance evidence.
