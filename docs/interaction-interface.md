# Using the Step 2 information interface

This is an offline interface tested with recorded/simulated replies. It does not
yet contact a human, browse the internet or call an AI service. The
[scope record](decisions/0013-information-interface-scope.md) defines its limits.

Create a `PVEnv`, reset it, then construct `InformationSession(env, initial)` with
the initial observation. Use one session to own the episode. Do not attach the
legacy Recorder or advance the environment outside the session.

```python
from pv_sim.interaction import InformationSession
from pv_sim.interaction_contracts import (
    InformationReply, InformationSource, InteractionRequest,
)

task, initial = env.reset(episode_id="example")
session = InformationSession(env, initial)
question = InteractionRequest(
    episode_id=task.episode_id,
    request_id="context_1",
    channel="human",
    question="What changed near the panel?",
    information_gap="Local context is unknown.",
    intended_decision="Decide which observation would reduce uncertainty.",
)
pending = session.begin(question)
# An event loop can poll() while awaiting a response. Simulation is paused.
receipt = session.complete("context_1", InformationReply(
    outcome="available",
    text="No reliable local observation is available in this authored example.",
    provenance="simulated",
    sources=(InformationSource(title="Interface example author"),),
))
```

Read the returned receipt's outcome before treating its text as usable evidence.
An expired response becomes `timed_out`, a malformed response becomes
`invalid_response`, and `cancel(request_id)` releases a pending wait explicitly.
Each accepted new request consumes one of three slots, including follow-ups.
A follow-up uses a new request ID and the completed parent's `parent_request_id`.
It can switch between the human and internet channels.

Submit a physical action separately with
`session.step(PhysicalDecision(action=action, information_refs=("context_1",),
interpretation="..."))`. The action uses the unchanged physical contract and
gate. The returned observation supplies the sensor evidence; inspect its
feedback rather than assuming the command completed. A final Finish must still
complete its measured two-second verification tail.

For transport fixtures, `RecordedTransport` matches every field of the request;
`ReplayTransport` additionally requires its declared order. The convenience
`session.request(question, transport)` is for immediate recorded responses.
If the same request is already pending it returns that handle without calling
the transport again. A completed retry returns its original receipt.

`session.save(path)` writes a new transcript without overwriting existing
evidence. `load_transcript(path)` checks its envelope and checksum.
`replay_interactions(fresh_env, fresh_initial, transcript)` reconstructs the
interaction, with no external calls, from a separately reset environment using
the same evaluator configuration and seed. Use the dedicated interaction replay;
legacy physical replay does not understand these events.

Run the retained fixture with a new output directory:

```sh
.venv/bin/python scripts/validate_information_interface.py \
  --output runs/information-interface-example
```

The fixture deliberately scripts the questions and actions. Its result tests
interface mechanics and replay, not the usefulness of an autonomous agent.
