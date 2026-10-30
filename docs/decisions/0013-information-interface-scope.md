# 0013 — Offline information interface for prototype Step 2

Date: 19 October 2026. Implementation authorized by Wei's “sound good go ahead”
following the accepted Step 1 scenario and the proposed interface work.

## Decision and scope

Implement the interface in the [interactive prototype plan](../planning/interactive-pv-prototype-v1.md)
using recorded and simulated responses. A scripted driver verifies the mechanics;
it is not an adaptive agent. Step 2 makes no actual human, internet or model-provider
calls. Step 3 will integrate and identify the decision agent and demonstrate live
exchanges separately.

The public version is `interaction/1.0`. Requests name their episode, request ID,
channel, question, information gap, intended decision and optional completed
parent request. Answers carry outcome, text, provenance and source records.
Available answers require attribution. Source dates may be unknown. A URL is
metadata and is never automatically fetched. An attributed answer can still be
incorrect or uncertain.

This version accepts only `recorded` and `simulated` provenance. It cannot label
a fixture as live. A reviewed live transport extension is needed for Step 3.
Both channels are names in the interface, not claims of demonstrated connectivity.

## Frozen protocol

The [protocol configuration](../../configs/interaction_protocol.json) freezes:

- Three requests per episode, shared by human and internet channels. Follow-ups,
  cancellations, unavailable replies and timeouts all consume a request.
- Human deadline: 300 wall-clock seconds. Internet deadline: 30 wall-clock seconds.
- Question, gap and intended-decision fields: at most 2,000 UTF-8 bytes each.
  Reply text: 16,000 bytes; each request/reply wire message: 65,536 bytes.
- At most eight sources per answer, with bounded titles and HTTP(S) URLs.
  JSON rejects unknown or duplicate fields, wrong types and non-finite numbers.

Malformed requests, foreign episode IDs, unknown parents and request-ID conflicts
reject before charging. An identical request retry returns its pending handle or
completed receipt without dispatching again or consuming more time or allowance.
Conflicting duplicate completions reject. Follow-ups to unavailable or cancelled
answers are allowed; they can seek clarification through another channel.

## Simulation and wall time

An accepted request consumes one existing decision and 0.2 simulated seconds.
Events and sensors advance normally during that overhead. Only then does the
world pause. Waiting freezes physics, energy accounting, queued deliveries and
capture timestamps. Completion resumes the same simulated clock.

The bridge requires a settled decision boundary, with no physical action or
pending load/image request in flight. It reserves another decision and enough
time for a later Finish overhead plus the unchanged two-second verification tail.
Physical actions, reset and advancing helpers reject during a pending wait.
Protection during overhead retains the existing stop behavior and produces an
explicit cancelled interaction instead of stranding a pause.

Monotonic wall time determines deadlines, including equality at the deadline.
UTC timestamps are receipt metadata. Waiting is reported separately from
simulated energy and elapsed time. These results concern offline experiments,
not electricity production while a real person takes minutes to answer.

The nonblocking `begin/complete/poll/cancel` API is the underlying interface.
Callers must poll to observe expiry while awaiting a reply; no background timer
or live network worker is provided. The convenience `request` method calls an
immediate recorded adapter. Provider exceptions return unavailable without
exposing exception details. Invalid replies return invalid_response and release
the pause. A bad injected clock rejects without releasing it; fixing that clock
allows explicit cancellation.

## Public boundary and compatibility

The transport receives only a revalidated, immutable public request. It receives
no simulator object, private configuration, seed, evaluator result or future
event schedule. The caller controls the question text, so this is a trusted
orchestrator data boundary, not a sandbox that prevents a malicious Python caller
from accessing local files.

Response text is never executed or parsed into an action. A separate typed
`PhysicalDecision` identifies the prior information used, gives an interpretation
and submits its action through the existing physical gate. The trace links it
to the returned observation and measured confirmations. These references establish
attribution; they do not by themselves prove diagnostic accuracy or causation.

Legacy physical schema `1.0`, its diagnosis labels and measurement-only
`request_help` remain unchanged. External requests do not spend the legacy help
token or its five-second simulated delay. A session must begin at episode reset;
constructing another session mid-episode cannot reset its allowance.

## Recording and replay

Information sessions use a separate versioned transcript containing the initial
public task/observation, request starts, receipts, physical decisions and their
observations. They reject an attached legacy Recorder because legacy replay
cannot reconstruct the new overhead events.

Saving is exclusive and bounded to 16 MiB. The JSON envelope has a SHA-256
integrity checksum; it is not a signature or proof of source truth. A caller may
save a pending transcript for inspection, but complete replay rejects an
unfinished interaction. This prototype does not implement automatic crash
recovery or an append-only production event journal.

Replay runs the same events on a separately reset environment and compares
every resulting public record. It restores original wall-time metadata without
contacting sources; actual replay duration is reported separately. Private seed,
configuration, source hashes and evaluation metrics remain in the evaluator
artifact directory and never enter the public transcript.

## Acceptance boundary

Required evidence is strict-contract tests, pause/queue/energy checks, budget and
retry checks, source-text boundary tests, exact interaction replay, existing
non-render regression tests and independent review. Rendering itself is unchanged;
the accepted Step 1 desktop images remain the visual evidence. No additional
graphics claim or new image is made by this interface-only step.

Live conversation, live retrieval, response-dependent decisions by a declared
agent, and comparison against a fixed investigation sequence remain Steps 3–4.
Agreement with real PV hardware remains a separate validation task.
