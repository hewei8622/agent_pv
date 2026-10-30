# Paired investigation evidence — 19 October 2026

The five authorized items are delivered for the first controlled development
comparison: two decision systems; four paired physical/context cases; complete
investigation records; explanatory R/A plots and 3D replay; and measured
evaluation with an 11-page PDF. This is a bounded deterministic comparison,
not a live or held-out open-world demonstration.

The separate independent reviewer returned **PASS for this four-case scope**,
with no unresolved runtime, data or scientific-claim blocker. The manual browser
orbit-drag check remains explicitly unverified, as detailed below.

## Results

All eight scheduled episodes completed, met the frozen success rubric and
replayed exactly with equal final metrics. All 16 numerical voltage predictions
passed. All seven scored error categories were false in all episodes. No failed
formal trial was discarded and no result-driven change was made to the rubric.

| Case | Allowed decision | R / A ready (s) | Queries / probe points per arm | R / A PV energy over 16 s (J) |
|---|---|---:|---:|---:|
| C01 unchanged, known hold | Verify nominal hold | 3.32 / 3.32 | 0 / 0 | 15.843560 / 15.843560 |
| C02 incident-light reduction | Recognize reference reduction; verify hold | 3.32 / 3.32 | 0 / 0 | 9.604737 / 9.604737 |
| C03 unknown service context, hold reply | Ask, then verify hold | 3.52 / 3.52 | 1 / 0 | 15.843560 / 15.843560 |
| C04 unknown service context, survey reply | Ask, survey, select measured best, verify | 6.92 / 6.92 | 1 / 3 | 15.466694 / 15.466694 |

Every pair has identical physical configuration, seed, public prior, tools,
information access and budgets. All run to 16 s. C03/C04 have identical local
histories before the query for each arm; the differing service instruction
changes the permitted decision. The physical experiment in C04 costs three
points and 0.376866 J of simulated production relative to C03. It does not improve
the final selected voltage in this case: the best measured candidate is already
the nominal 1.8 V. Both arms avoid a redundant set-voltage action.

R and A tie on supported outcomes, physical resources and energy in every pair.
This establishes a functioning evidence-to-action loop and comparison method;
there is no demonstrated adaptive performance advantage. Single-run local wall
times vary and support no speed ranking. These are development cases with one
deterministic episode per arm, not statistical estimates across unseen conditions.

## What was implemented

- `comparison_policies.py`: competent frozen measured procedure R and
  deterministic goal-driven planner A, sharing evidence-validation helpers.
- `comparison_sources.py`: same public brief for both arms and a controlled
  typed current-service record endpoint accepting newly worded questions.
- `comparison.py` and `scripts/run_paired_investigation.py`: executable freeze,
  paired schedule, public-only policy contexts, pre-dispatch timing and audit,
  independent public-evidence scoring, exact replay and retained outcomes.
- `comparison_viewer.py`, its HTML template and build command: synchronized
  decisions, questions/replies, world/self records, alternatives, pre-action
  predictions, verification, plots, costs and evaluator 3D.
- `scripts/build_paired_report.py`: source-bound plots, 3D reconstruction,
  explanatory tables, outcomes, test interpretation and follow-on experiments.

A recomputes unmet goals and selects eligible operators using explicit fixed
priorities. It uses no LLM, trained model, semantic internet search, live human
exchange, image interpretation or cross-episode memory. Its world belief and
self record are compact symbolic summaries. The simulator's private world model
generates hidden states; those states are not supplied to either decision policy.

The three intentional compatibility changes are recorded in
[scope decision 0015](../decisions/0015-paired-investigation-scope.md).
Marked investigation recording is opt-in; physical-only legacy replay rejects
the new protocol before creating output. Old default behavior and replay remain
covered by the regression suite. Earlier accepted source/interaction/foundation
changes in the working tree have been preserved.

## Actual execution and tests

The executable freeze was created at 13:35:48 UTC, before the formal comparison
started at 13:36:57 UTC. It hashes 42 execution inputs and records versions,
private cases/corpora, seed, mechanisms, deadline, budgets and rubric. The runner
checked it before each episode and again before writing the summary. Engineering
smoke checks and test fixtures preceded the freeze; no held-out claim is made.

- Full unit, integration and security suite: **875 passed in 63.98 s**;
  zero failures, errors or skips. JUnit suite duration is 63.974 s; the slight
  difference is reporting precision, not a separate execution.
- Final viewer regression after presentation fixes: **25 passed in 11.67 s**.
  These overlap the full suite and must not be added to 875 as unique tests.
- Formal batch: **8/8 success**, **8/8 exact replays**, **16/16 numerical
  predictions**, all four common-horizon pair checks and both pre-query
  counterfactual-history checks pass.
- Independent review checked all 147 indexed artifacts, original recorder
  bindings, availability/freshness and source permission, and recomputed energy.

Tests include irrelevant/unavailable/conflicting/stale context, bounded
clarification, failed/dropped probe evidence, an alternate candidate requiring a
real set-voltage action, stale/contradictory voltage, foreign/duplicate action
feedback, exact capture matching, retrospective finish-tail claims, computation
overrun rejection, public export and replay. These robustness tests are not extra
primary performance episodes.

Operational readiness and exact-time prediction verification are distinct. In
C04, a matched V/I pair captured at 6.90 s supports the operating decision when
returned at 6.92 s. The separately precommitted 7.10 s voltage prediction becomes
assessable only at 12.12 s. It cannot justify the earlier claim retrospectively.
At the final 16 s boundary, terminal cleanup disconnects the simulated plant
after the last integrated interval; there is no claim of post-episode generation.

## Visual review and limitation

The final paired viewer is `output/workflow/paired-03/`. Earlier builds are
retained. Browser inspection covered case selection, source-event time gating,
next-decision navigation, play/pause, public perspective, displayed questions,
predictions, plots, 3D reconstruction, final costs and the separate public export.
The final public export omits private payloads, disables evaluator view and had
no console errors. Three browser screenshots and a hash-bound QA record are saved.

The browser approval review rejected raw pointer input for the manual orbit-drag
test, reporting declined permission. No workaround was attempted. The 3D scene
and reset control were inspected, but the manual drag gesture remains unverified.
This is a disclosed UI QA limit, not a failed experiment or a completed drag test.

All 11 final PDF pages were rendered and visually inspected. The root reviewer
also inspected every page; the last cosmetic diagram correction changed only
page 2, and the other ten rendered PNGs were confirmed byte-identical.
No new camera frames were acquired in these numeric episodes. The 3D views are
evaluator reconstructions, not agent RGB images. Existing original camera
evidence remains separately available in the earlier B1 replay.

## Evidence map

- [Capability and case-design explanation v2](../../output/pdf/PV_INVESTIGATION_CAPABILITIES_AND_CASES_v2.pdf)
  reorganizes this same retained evidence around what the system can do, why each
  case was selected and the actual R/A mechanism contrast. It adds no new trial.
- Independent explanation review
  passed for clarity, evidence consistency and all ten rendered pages; this
  reviews the revised report rather than accepting another experiment batch.
- [Paired explanatory report](../../output/pdf/PAIRED_INVESTIGATION_REPORT_20261019.pdf)
- [Workflow viewer, public view](../../output/workflow/paired-03/paired-public.html)
- [Public workflow viewer](../../output/workflow/paired-03/paired-public.html)
- [Run and interpretation guide](../paired-investigation.md)
- Independent review
- [Freeze](../../private_eval/paired-investigation-freeze-20261019.json)
- [Batch manifest](../../runs/paired-investigation-20261019/paired_manifest.json)
- [Private comparison summary](../../private_eval/paired-investigation-20261019/comparison.json)
- [Artifact index](../../private_eval/paired-investigation-20261019/artifact-index.json)
- [Full-suite JUnit](../../runs/paired-build-20261019/nonrender.xml)
- [Final viewer JUnit](../../runs/paired-build-20261019/viewer-regression-03.xml)
- [Recorded commands](../../runs/paired-build-20261019/evidence/commands.jsonl)
- [Browser QA](../../output/workflow/paired-03/browser-qa.json)

## What remains scientifically unproved

Noisy or held-out performance, useful plan revision under disruption, live
human/web interaction, learning and hardware fidelity remain separate work.
The next bounded comparison should add capability failures, expiring or
conflicting instructions and difficult sensing while preserving a strong R.
Physical validation requires independent synchronized irradiance, temperature,
I-V/power and transient measurements, declared error tolerances and uncertainty.
A passing digital test alone does not establish agreement with real PV.
