# M0 accepted by independent review — 17 October 2026

The authorized separate reviewer returned **PASS for M0** and **PASS for the
timing amendment**, with no required corrections remaining. Reviewed runtime
revision: `20655caaee3daf0ebbfb8719a5cde4eb1838e935`. Later acceptance-documentation
changes do not alter that runtime, tests, configuration, schemas or lock.

Original verdict: `output/review/M0_INDEPENDENT_RECHECK_20261017.txt`.
SHA-256: `3ccdb806cb3fdb71a8bd5d05a3743713eabbbeb88191b1e8db8f59d12dd4f434`.
Reviewer manifest: `runs/reviewer-m0-recheck-20261017/review-manifest.json`.
The implementer verified all 50 source hashes and 116 evidence hashes in that
manifest before making the documentation update. The verdict is preserved
unchanged; this page summarizes it and does not substitute for it.

## Evidence accepted

| Evidence | What actually happened |
|---|---|
| Clean locked environment | Reviewer independently installed 23 pinned packages using local tools/cache |
| Current unit suite | Reviewer independently ran 132 tests: all passed in 1.20 s, zero failures/errors/skips |
| PNG correction | Reviewer reproduced all four original assertions; malformed payloads rejected and valid control accepted |
| Timing amendment | Reviewer independently checked 27 cases and exact rational tick arithmetic |
| Import, lint and schema checks | Reviewer independently reproduced passing results |
| Real camera image and full live suite | Wei's desktop run passed 127 tests in 1.35 s; reviewer audited artifacts/logs/hashes and inspected the image |
| Camera projections | Reviewer independently measured three residuals, all below the unchanged 2-pixel tolerance |

The reviewer made no new live graphics attempt. The accepted graphics evidence
is the actual desktop run under `runs/m0-png-fix-20261017T064237Z-50847/`.
Agent-context CGL still fails. The reviewer verified 14 relevant renderer,
contract, test, script, schema and dependency paths unchanged from the desktop
revision, and verified identical generated MJCF. The static render does not
consume exposure duration. The affected timing checks were rerun at the final
revision; no combined 137-case live-suite result is claimed or required by this
review for the bounded amendment.

## Accepted timing decision and repair history

The pilot exposure is 12 ms with 2 ms ticks: exposure start n, actual midpoint
snapshot n+3, exposure end n+6. This replaces the conflicting v7 nominal 10 ms
exposure by an explicit reviewed amendment, [ADR 0006](../decisions/0006-exposure-timing.md).
M0 validates configuration only; actual state capture, immutable delivery,
interval accounting and event ordering remain required M1 implementation/tests.

The reviewer found one new defect: extremely small positive exposure durations
were treated as zero ticks by the arithmetic tolerance. One bounded repair now
requires a positive midpoint tick count, preserving the tolerance. Both failing
counterexamples and before/after tests are retained under `runs/m0-timing-20261017/`.
The original PNG defect used one prior repair round. The reviewer also corrected
one audit-script assumption about log checkpoints and preserved its failed run;
that was not a product evidence-integrity defect.

The original FAIL review, historical PDF, failed probes and all earlier manifests
remain unchanged. Requested reviewer model/effort were Astra/ultra; tools did not
provide authoritative runtime metadata. This is context-separated review and
auditable local evidence, not mathematical proof or tamper-proof attestation.

## Remaining authorization

M0 is ready for Wei's explicit M1 decision. M1 has not started. Approval would
authorize only the planned smallest integrated loop: finite camera servos,
synthetic PV/thermal world, integer-tick captures/actions, B0/B1, private/public
recording and replay, with the three development seeds 11/23/47 and a new stop
for review before M2. No hardware, paid provider calls or broader milestone is
authorized by the M0 verdict.

The reviewer recorded about 33 seconds of command time, plus reading/inspection;
coding-session monetary cost is not exposed. No paid external provider calls
were made. The review environment accounts for about 119.7 MiB, held locally;
all runs and output artifacts were about 174.7 MB before final documentation,
below the 2 GB pilot artifact cap. No physical fidelity or hostile-policy
isolation claim follows from this acceptance.
