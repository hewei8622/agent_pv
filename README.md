# PV investigation simulator

A small, deterministic digital world in which a photovoltaic (PV) panel, a
movable camera, electrical sensors and a controllable load are simulated
together, so that a decision system (a hand-written procedure today, an AI
agent tomorrow) can **sense, reason, choose an action, act and verify the
result**, and so that two decision systems can be compared fairly on the same
hidden conditions.

It is the preliminary model tool for the *Agentic PV Systems* programme at
King's College London (2026-27). It runs on a laptop, needs no GPU, and is free
to use under the MIT licence.

**New here?** Read the four-page plain-language overview
[`output/pdf/Agentic_PV_Overview_Plain_Language_2026-10-30.pdf`](output/pdf/Agentic_PV_Overview_Plain_Language_2026-10-30.pdf)
(scope, approach, this tool, what it shows, what comes next), then try it:

```bash
git clone https://github.com/hewei8622/agent_pv.git && cd agent_pv
uv sync --locked --group dev           # installs the pinned Python packages (needs uv)
uv run --with jupyter --with matplotlib jupyter lab notebooks/quickstart.ipynb
```

[Section 3](#3-quick-start) has the full set-up, including how to get uv.
Two notebooks teach the tool: `notebooks/quickstart.ipynb` for the mechanics and
`notebooks/multimodality_and_agent_loop.ipynb` for the ideas.

**Status (30 October 2026).** Milestones M0, M1 and M2 and the first paired
comparison (R versus A on four cases, eight episodes) passed independent review
on 17 to 19 October 2026. The non-render test suite passes 875 tests. The paired
comparison tied: the symbolic planner A chose the same operators at the same
times as the procedural reference R. No large language model, no image
interpretation by any policy, no cross-episode memory and no physical hardware
are involved yet. Everything in this repository is simulation evidence, not
hardware validation. The milestone history is in
[docs/MILESTONE_LOG.md](docs/MILESTONE_LOG.md) and a map of all documentation
is in [docs/README.md](docs/README.md).

---

## Contents

1. [What this project is, and is not](#1-what-this-project-is-and-is-not)
2. [The idea in one loop](#2-the-idea-in-one-loop)
3. [Quick start](#3-quick-start)
4. [Running things](#4-running-things)
5. [How the simulator works](#5-how-the-simulator-works)
6. [Repository map](#6-repository-map)
7. [Writing your own policy](#7-writing-your-own-policy)
8. [Changing the world](#8-changing-the-world)
9. [Evidence so far and limitations](#9-evidence-so-far-and-limitations)
10. [Vocabulary](#10-vocabulary)
11. [Further reading](#11-further-reading)
12. [Licence, contributing and citation](#licence-contributing-and-citation)

---

## 1. What this project is, and is not

**It is**

- A simplified but internally consistent PV world: geometry, light, shadows,
  an eight-cell electrical model, a thermal model, a camera on a servo rail,
  timed and noisy sensors, and a bounded set of actions.
- A strict **public/private boundary**. The decision policy sees only typed,
  timestamped observations and a declared task. The simulator's hidden state
  (true irradiance, true cell transmission, scenario seeds) is kept for the
  evaluator and never reaches the policy.
- A **recording and replay** system. Every episode can be replayed exactly and
  every claim can be traced back to a recorded observation.
- A **comparison harness**. Two policies run on identical hidden conditions,
  identical tools and identical budgets, and are scored by an independent
  evaluator.
- A browser **viewer** that replays an episode with synchronised plots, the
  recorded decisions, the camera images and a 3D reconstruction.

**It is not**

- A validated solar-cell model. The electrical model is an explicitly
  synthetic piecewise surrogate (`src/pv_sim/pv.py`). Agreement with a real
  panel is separate, unstarted work.
- An agent. The three policies that exist (B0 fixed, B1 scan, and the paired
  R and A) are hand-written. The point of the repository is that you can plug
  in a better one and measure it honestly.
- A benchmark with held-out results. The four cases run so far are
  development cases, frozen before the run but designed by the same people
  who wrote the policies.

## 2. The idea in one loop

```
   hidden world change  -->  evidence available to the policy  -->  interpretation
          ^                                                             |
          |                                                             v
   measured outcome   <--  bounded action or information request  <--  choice
          |
          v
   fresh verification: did the action do what was predicted?
```

Each turn the policy receives the full **public history** (every observation
so far) and returns one **decision**: an action plus its stated hypotheses,
the evidence it relies on, any numerical predictions, and a one-line
rationale. The simulator executes the action, charges its cost against the
budgets, and returns a new observation that contains the sensor samples and
the **feedback** for that action: was it accepted, executing, completed,
rejected, timed out? A sent command is never evidence that it was applied. The
policy must read the measurements that came back.

Three things are deliberately separated and should stay separated in anything
you build on top:

| Layer | What it holds | Who may read it |
|---|---|---|
| Public task and observations | Declared sensors, actions, limits, budgets, nominal calibration, hypothesis classes; timestamped samples and action feedback | The policy |
| Private world | True irradiance and its schedule, true per-cell transmission, scene geometry, seeds, sensor-noise draws | The simulator and the evaluator only |
| Evaluator records | Truth trace, metrics, independent reference calculations, scores | People reviewing results |


### How the code maps onto the loop

The plain-language overview draws the loop as six boxes. This is where each
box lives in the code today, and what is still missing.

| Loop stage | In the code today | Not yet |
|---|---|---|
| Sense | `sensors.py`: voltage, current, temperature and reference light at 10 Hz, encoders at 20 Hz, images on request; latency, noise, stale and dropped samples in `dev.toml` | shading that the camera can see |
| Believe | `Decision.hypothesis_probabilities` over five classes, `unresolved_hypotheses`, `evidence_refs`; `WorldBelief` and `SelfModel` in `investigation.py` | an unlisted-cause class; a calibrated or learned belief update |
| Decide | budgets and cost weights in the public task; policies B0, B1, R and A, and the three controllers in the second notebook | planning by value of information; any language model |
| Act | eight actions through the gate in `actions.py`; servo dynamics in the MuJoCo backend | battery or demand actuation |
| Verify | feedback codes, `measured_confirmation`, numerical predictions checked at their declared capture times | nothing structural |
| Finish and interact | `finish` with `resolved`, `unresolved` or `help_needed`; `InformationSession` with one typed source; exact replay and the HTML viewer | a live human or web source; a dialogue with the user |

## 3. Quick start

Requirements: macOS (arm64) or Linux, Python 3.11.17 (pinned), [uv](https://docs.astral.sh/uv/)
0.13.1 (pinned in `pyproject.toml`). No GPU. Rendering camera images needs a
real OpenGL context; on macOS that means a desktop terminal session, not an
SSH shell. Everything except image capture runs headless.

```bash
# 1. Get the code
git clone https://github.com/hewei8622/agent_pv.git
cd agent_pv

# 2. Install uv once, then let it install the pinned Python and the locked packages
pip3 install --user uv            # or: curl -LsSf https://astral.sh/uv/install.sh | sh
uv python install 3.11.17
uv sync --locked --group dev

# 3. Check that it works (no rendering needed)
uv run pytest tests/unit -q
uv run pv-sim validate-config --config configs/pilot.toml

# 4. Open the quick-start notebook
uv run --with jupyter --with matplotlib jupyter lab notebooks/quickstart.ipynb
# or run the same material as a script
uv run --with matplotlib python notebooks/quickstart.py
```

The notebook walks the observe, decide, act loop one step at a time, runs
whole episodes, injects a cloud and a shaded cell, collects camera frames while
moving the rig and watching the encoders, shows what the camera can and cannot
see (a cloud yes, a shaded cell not in this build), runs a probing policy, then
a monitoring policy that investigates only an unexplained power drop, and ends
with the metrics, the budgets and a template for your own policy. The camera
sections need a desktop graphics session and skip themselves otherwise; the
committed `.ipynb` was executed with rendering on, so the images are in it.

A second notebook, `notebooks/multimodality_and_agent_loop.ipynb`, is the
conceptual companion: it shows what multi-modality is (five hidden causes,
four passive senses, who notices what), why it matters (how many causes remain
possible as senses are added), sensing as an action (an IV sweep separates the
two causes the passive senses confuse), what the agent loop is (the loop in
fifteen lines, three controllers built on it) and why it matters (a fixed rule,
a smart threshold and an agent loop across six worlds, including a two-cause
surprise). Start there if you want the ideas before the mechanics.

## 4. Running things

### Command line

`uv run pv-sim --help` lists four commands.

| Command | What it does | Needs rendering |
|---|---|---|
| `validate-config --config FILE` | Validate a TOML or JSON configuration and print its hash | No |
| `demo --config FILE --seed {11,23,47} --policy {fixed,scan} --output DIR` | Run one M1 pilot episode with real camera images, recording everything | Yes |
| `replay --manifest FILE --output DIR` | Re-execute a recorded episode from its manifest and check that it reproduces exactly | Only if the original captured images |
| `verify --suite development --config FILE --seed 20261016 --output DIR` | Run the evaluator-only M2 integrity suite | Yes |

The `demo` command is intentionally limited to three seeds and refuses to run
once three complete pilots exist in `private_eval/`. That guard protected the
accepted evidence; for your own experiments use the Python API (section 7) or
copy `run_demo` from `src/pv_sim/cli.py` into your own script.

### The paired comparison (R versus A)

The comparison runs four cases, each once with the procedural reference R and
once with the goal-driven planner A, numeric-only, with no rendering:

| Case | Hidden condition | Service instruction | Expected behaviour |
|---|---|---|---|
| C01 | Unchanged light | Known: hold | Verify the nominal 1.8 V, no query, no probe |
| C02 | Direct irradiance drops 800 to 400 W/m² at 2 s | Known: hold | Report the measured light reduction, hold and verify |
| C03 | Unchanged light | Unknown; source replies hold | Ask once, then hold and verify |
| C04 | Unchanged light | Unknown; source replies survey | Ask once, probe 0.8, 1.8 and 3.0 V, select the best measured point, verify |

Reproduce it with new output paths (never overwrite retained evidence):

```bash
pv_pair_id="paired-investigation-$(date -u +%Y%m%dT%H%M%SZ)-$$"
uv run python scripts/run_paired_investigation.py --prepare --freeze "private_eval/$pv_pair_id-freeze.json"
uv run python scripts/run_paired_investigation.py --freeze "private_eval/$pv_pair_id-freeze.json" --output "runs/$pv_pair_id"
uv run python scripts/build_comparison_viewer.py \
  --manifest "runs/$pv_pair_id/paired_manifest.json" \
  --output "output/workflow/$pv_pair_id/paired-evaluator.html" \
  --public-output "output/workflow/$pv_pair_id/paired-public.html"
```

The freeze hashes 42 execution inputs, including source files, so it refuses
to run if you have changed the code since freezing. Freeze again after a
change. See [docs/paired-investigation.md](docs/paired-investigation.md).

### Viewers

Open the HTML files in `output/workflow/` in a browser, no server needed.
`paired-03/paired-public.html` is the retained R/A replay and
`build-03/b1-public.html` is a B1 episode with real camera images. These public
views omit the hidden truth; the evaluator views that include it are rebuilt
locally with the commands above. Scrub the timeline, step by decision, and read the world-belief and
self-model records beside the plots.

### Tests

```bash
uv run pytest tests/unit tests/integration tests/security -q   # headless, about a minute
uv run pytest tests/render -q                                   # desktop graphics session only
uv run ruff check .
```

Render tests are marked `render` and are never silently skipped: if there is
no OpenGL context they fail, by design. Two headless tests have external
needs: one runs the viewer's JavaScript under Node.js, and one calls `uv` and
needs it on `PATH` (for a `pip install --user` install that is
`$HOME/Library/Python/3.X/bin` on macOS). Node.js can be installed without
administrator rights by unpacking the official arm64 tarball into
`~/.local/node` and linking `node` into `~/.local/bin`.

Reference result, 28 October 2026, Apple Silicon Mac, desktop login shell:
all 875 headless tests pass and all 34 render tests pass. Over SSH on the same
hardware the render tests fail for lack of a graphics context, as expected.

## 5. How the simulator works

### 5.1 The world

Everything is configured from one file, `configs/pilot.toml` (clean, no noise)
or `configs/dev.toml` (noise, delays and actuator failures on). The main parts:

- **Scene and camera** (`scene.py`, `backends/mujoco_backend.py`). A 0.30 by
  0.20 m panel of 4 by 2 cells lies flat at the origin. A camera on a slide
  rail with yaw and pitch joints is simulated in MuJoCo with real finite
  servos: commands take time, overshoot is possible, and encoders report the
  actual pose. Home position is 0.45 m in front and 0.35 m above the panel.
- **Optics** (`optics.py`). Direct and diffuse irradiance from a point source
  direction, a per-cell transmission factor in [0, 1] that stands in for
  soiling or shading, and an occlusion grid. A reference light sensor sits
  beside the panel and reports plane-of-array irradiance.
- **Electrical** (`pv.py`). Eight cells in two series substrings of four,
  each substring with a bypass path. Short-circuit current scales with
  irradiance; open-circuit voltage follows a logarithmic irradiance term and a
  temperature coefficient. The requested voltage is a load setting; the
  returned voltage is the terminal reading. Limits: 0.2 to 4.0 V, 2.0 A.
- **Thermal** (`thermal.py`). A lumped heat balance: absorbed light minus
  electrical output heats the module, conductance to ambient cools it, a trip
  at 90 °C ends the episode.
- **Sensors** (`sensors.py`). Voltage and current at 10 Hz, encoders at
  20 Hz, images at most 2 Hz, each with a latency and, in `dev.toml`, Gaussian
  noise, stale and dropped samples. Every sample carries a capture time and a
  delivery time; delivery cannot precede capture.
- **Clock** (`scheduler.py`). A 2 ms tick. An episode runs to a horizon
  (60 s by default, 16 s in the paired comparison) or ends earlier on finish,
  safe stop, thermal trip, overcurrent, joint limit or numerical error.

### 5.2 What the policy is told: the public task

`PublicTask` (in `contracts.py`) is the only description of the world the
policy receives. It declares:

- `sensors`: `voltage_v`, `current_a`, `temperature_c`, `reference_w_m2`,
  `encoders`, and `rgb` when rendering is enabled;
- `available_actions` and `limits` (rail travel, yaw, pitch, voltage range);
- `budgets`: time, image frames, voltage points, help requests, decisions,
  rail path and angular path;
- `cost_weights`, used only for a synthetic dimensionless utility;
- `nominal_calibration`: the published camera geometry, which is not the
  true geometry;
- `hypothesis_classes`: `source_change`, `transmission_change`,
  `electrical_change`, `thermal_change` and `actuation_or_sensing_change`.
  Today a decision may only name hypotheses from this list. An *unlisted cause*
  class is part of the module's minimal goal (see the programme brief, Case A).

### 5.3 What the policy sees: observations

Each `Observation` carries a sequence number, a delivery time, scalar samples,
encoder samples, image samples, action feedback, remaining budgets and a
terminal flag. Samples have a `validity` of `valid`, `missing`, `saturated` or
`stale`. Voltage and current should be paired only when their capture times
match exactly; `policies/protocol.py` provides `matched_pairs` for that.

### 5.4 What the policy can do: actions

All actions carry `schema_version`, a strictly increasing `action_id` and a
`timeout_s` of at most 15 s.

| Action | Fields | Effect and cost |
|---|---|---|
| `set_voltage` | `voltage_v` | Command the load to a voltage; counts one voltage point |
| `probe_voltage` | `voltages_v` (1 to 3), `dwell_s` (0.2 to 2.0) | Visit each voltage, dwell, report matched V/I per point, then restore the previous setting; counts one point per voltage |
| `move_camera` | `slide_m`, `yaw_rad`, `pitch_rad`, `capture_after_settle` | Drive the servos; charges rail and angular path; optionally captures an image when settled |
| `capture_rgb` | none | Capture one 640 by 480 image at the current pose; counts one frame |
| `wait` | `duration_s` (0.1 to 5) | Let time pass and collect the ordinary sensor stream |
| `request_help` | `measurement` | Ask for a reference irradiance reading or a rear inspection; delayed, counts one help request; not advertised in the current task |
| `safe_stop` | none | Always available; ends the episode safely |
| `finish` | `resolution`: `resolved`, `unresolved` or `help_needed` | Declare the end; a 2 s verification tail of measurements must still complete |

Every action also costs the fixed `decision_overhead_s` (0.2 s) and consumes
one of the decision budget. The gate in `actions.py` rejects actions that are
out of range, over budget or unavailable before anything moves.

### 5.5 Feedback and verification

Action feedback codes are `accepted`, `executing`, `completed`, `rejected`,
`timed_out`, `failed` and `cancelled`, each with a reason where relevant. A
completed `set_voltage` carries `measured_confirmation`: the matched samples
taken after acceptance. The existing policies refuse to treat a setpoint as
achieved unless a fresh sample within 0.03 V confirms it. Numerical
predictions made in a decision are checked by the evaluator at their declared
capture times, never retrospectively.

### 5.6 Information requests and the investigation session

Beyond physical actions, a policy can ask a question through
`InformationSession` (`interaction.py`). In the current code the only source is
a typed, controlled service record that answers whether a voltage survey is
permitted. The simulation pauses at a settled physical boundary while the
question is outstanding, up to three requests per episode. Live human or web
sources are specified but not implemented.

`InvestigationSession` (`investigation.py`) wraps the environment and the
information session into one decision loop. Its `context()` gives the policy
an `AgentContext`: task, history, completed replies, remaining requests, and
the policy's own `WorldBelief` and `SelfModel` records from the previous turn.
The policy returns a `PhysicalChoice` or an `InformationChoice`, both of which
carry an updated belief and self-model. This is the interface the paired
policies R and A use, and the one a future LLM agent should use.

### 5.7 Recording, replay and the evaluator

`Recorder` writes a public directory (observations, decisions, images) and a
private directory (configuration, truth trace, seeds, metrics). `replay.py`
re-executes recorded actions on a fresh environment and checks every
observation and image reproduces exactly. `comparison.py` owns the private
cases of the paired study and scores each episode independently of the
policies. `private_eval/` and `runs/` are ignored by git on purpose.

## 6. Repository map

```
configs/        pilot.toml (clean), dev.toml (noisy), tolerances.toml, experiment freezes
docs/           how-to guides (index in docs/README.md), decision and evidence records
  decisions/    0001-0015: scope and convention decisions, in order
  evidence/     what was run, when, with which hashes, and what the reviewer found
  planning/     interactive prototype plan v1, v2 and the visualisation spec
notebooks/      quickstart (mechanics) and multimodality_and_agent_loop (ideas), .ipynb and .py
output/         overview and report PDFs, public HTML replays (open in a browser)
schemas/        JSON schemas generated from the contracts
scripts/        experiment runners, report and viewer builders, evidence tools
src/pv_sim/
  contracts.py            every public record: task, actions, observations, decisions
  config.py               configuration schema and loader
  env.py                  PVEnv: reset, step, metrics, close
  scene.py, optics.py     geometry and light
  pv.py, thermal.py       electrical and thermal models
  sensors.py              sensor timing, noise, public task builder
  actions.py              the action gate
  backends/               MuJoCo servo and camera backend
  policies/               protocol, B0 fixed, B1 scan
  policy_runner.py        the serialisation boundary around a policy
  interaction*.py         information requests and replies
  investigation.py        AgentContext, WorldBelief, SelfModel, InvestigationSession
  comparison*.py          paired cases, R and A policies, evaluator, viewer
  recorder.py, replay.py  evidence recording and exact replay
  workflow_replay.py      HTML viewer builder
tests/          unit, integration, security (headless) and render (desktop only)
```

## 7. Writing your own policy

A policy is any object with `reset(task)` and `act(history) -> Decision`.
Inherit from `PublicBaseline` to get the bookkeeping for action identifiers,
completion checks and safe stops. The smallest useful policy below probes
three voltages, picks the highest measured power, verifies it and finishes.

```python
from pv_sim.config import load_config
from pv_sim.env import PVEnv
from pv_sim.policies.scan import ScanPolicy
from pv_sim.policy_runner import PolicyRunner
from pathlib import Path

class ProbePolicy(ScanPolicy):
    """B1 without the two camera moves: probe, select, verify, finish.
    See notebooks/quickstart.py for the full version, which also skips a
    redundant set command when the best point is already applied."""
    def act(self, history):
        if self.stage == "start":
            self.stage = "probe"
            return self._emit(history, "probe_voltage",
                              "Measure three candidate voltages.",
                              voltages_v=(0.8, 1.8, 3.0), dwell_s=0.5)
        return super().act(history)

config = load_config(Path("configs/pilot.toml"))
env = PVEnv(config, enable_rendering=False)      # headless: no rgb sensor, no capture_rgb
task, observation = env.reset(seed=1)
history = [observation]
runner = PolicyRunner(ProbePolicy(), task)
while not history[-1].terminal:
    decision = runner.decide(tuple(history))
    history.append(env.step(decision.action))
print(env.metrics()["pv_energy_j"], history[-1].terminal_reason)
env.close()
```

Rules that the runner and the gate enforce, so design for them:

1. The policy receives only JSON-serialised public records. Keep no reference
   to the environment, the configuration or any file under `private_eval/`.
2. `action_id` must be exactly the next integer. `PublicBaseline` handles it.
3. Hypotheses must come from `task.hypothesis_classes`; probabilities, if
   given, must cover the whole set and sum to one.
4. A decision larger than 64 kB or slower than 30 s is replaced by a safe stop.
5. `finish` needs a 2 s verification tail inside the remaining time budget.
6. Read the feedback. `completed` plus a fresh matching measurement is the
   only acceptable evidence that a setpoint was reached.

To use the richer investigation interface with beliefs, self-model and
information requests, start from `comparison_policies.py` and
[docs/investigation-workflow.md](docs/investigation-workflow.md).

## 8. Changing the world

Configuration is a frozen, strict Pydantic model. Change it by dumping to a
plain dictionary, editing, and validating again through JSON (the JSON route
turns lists into the tuples the strict contracts require, exactly as
`load_config` does):

```python
import json
from pv_sim.config import Config
raw = config.model_dump(mode="python")
raw["simulation"]["horizon_s"] = 12.0
raw["budgets"]["time_s"] = 12.0                       # must equal the horizon
raw["source_schedule"] = [{"time_s": 4.0, "dni_w_m2": 300.0}]   # a cloud at 4 s
raw["private_world"]["transmission"] = [1, 1, 0.3, 1, 1, 1, 1, 1]  # one shaded cell
config = Config.model_validate_json(json.dumps(raw, allow_nan=False))
```

What exists today as hidden conditions: a stepped change of direct
irradiance (`source_schedule`), a static per-cell transmission vector, the
source direction, ambient and initial temperature, series resistance, and the
M2 view fixtures in `m2_fixtures.py` (a screen that blocks the camera's view
without changing the light, a locked rail). What does **not** exist yet, and
is the first job of the module's minimal goal: time-varying shade masks,
soiling that appears during an episode, an occluding object in the 3D scene,
and any environment or demand model (tariff, weather, occupancy, battery).
Add such things on the private side of the boundary and expose them to the
policy only through sensors and declared information sources.

## 9. Evidence so far and limitations

| Claim | Evidence | Not established |
|---|---|---|
| The loop works end to end: sense, ask, probe, verify, record, replay | 8 of 8 paired episodes complete and replay exactly; 16 of 16 numerical predictions pass; 875 tests pass | Behaviour under noise, on held-out cases, or with an adaptive policy |
| Camera motion and images are real simulated evidence | M1 and M2 desktop batches with 33 rendered cases and inspected images | Any policy using the pixels |
| A can select operators by goal rather than by script | Recorded priorities and eligible alternatives in each A decision | Any performance advantage: R and A tied on every metric |
| Public and private data stay apart | Security tests on policy, information and investigation boundaries | Isolation from hostile code; this is a data boundary, not a sandbox |

Known limits: the electrical model is synthetic; the information source is a
fixture, not a human or the web; the threshold for detecting a light change
is prescribed, not learned; rendering needs a desktop session; the Google
Drive copy of this folder is not a runnable environment (its virtual
environment points at files the sync does not keep locally), so work from a
local clone.


### Roadmap: illustrative minimal goal and stretch goals

| | Have now (October 2026) | Illustrative minimal goal (this module, 2026-27) | Illustrative stretch goals |
|---|---|---|---|
| Simulator and predictor | simulated eight-cell panel and camera rail; hidden cloud, shading, series resistance and overheating; 875 tests | shading the camera can see; dust, objects, moving shadows; a simple building with tariff, weather and occupancy | a predictor of panel and surroundings, learned from the agent's own investigations, that says what will happen next and what acting or waiting costs (physics, data or both is part of the work); calibrated models of real modules; battery and demand packages on the same interface |
| Agent | three hand-built controllers; the agent loop beats a smart threshold and can name two causes at once | an agent built in OpenCode that reads images, uses the models as tools and reports back to the user, scored like the baselines | an unlisted-cause answer; goals given in words; planning by value of information; comparison with language-model agents |
| Proof and hardware | evaluator with hidden truth, paired scoring and replay viewer; two notebooks and this README | a bench rig (small panel, lamp, controllable load, camera on a rail) and a live demonstration | held-out cases with causes on no list (Case A); compound environment and demand scenarios (Case B) |

The four-page overview `output/pdf/Agentic_PV_Overview_Plain_Language_2026-10-30.pdf`
explains the same roadmap in plain language, with the figures.

## 10. Vocabulary

- **Policy**: the decision system under test. **Agent** is used loosely for a
  policy that keeps a belief and chooses evidence; it carries no claim of
  intelligence.
- **Episode**: one run from `reset` to a terminal observation.
- **Public / private**: what the policy may see versus what only the
  simulator and evaluator see.
- **Feedback**: the typed status of an action, distinct from the sensor
  samples that show its effect.
- **Verification**: a fresh measurement after an action that agrees with what
  was commanded or predicted.
- **R and A**: the procedural reference and the goal-driven planner of the
  paired comparison. **B0 and B1**: the fixed-voltage and scripted-scan
  baselines of M1.
- **Freeze**: a hash of every input to an experiment, taken before the run.
- **World belief / self model**: the policy's own short records of what it
  thinks is happening and what it can currently do.

## 11. Further reading

- [docs/paired-investigation.md](docs/paired-investigation.md): running and reading the R/A comparison.
- [docs/investigation-workflow.md](docs/investigation-workflow.md): the AgentContext interface and the viewer.
- [docs/interaction-interface.md](docs/interaction-interface.md): information requests.
- [docs/public_contract.md](docs/public_contract.md): the wire format and its validation rules.
- [docs/planning/interactive-pv-prototype-v2.md](docs/planning/interactive-pv-prototype-v2.md): the research question and the planned experimental arms.
- [docs/decisions/](docs/decisions/): why things are the way they are, one decision per file.
- [docs/evidence/](docs/evidence/): what was run and what the independent reviewer found.
- `output/pdf/PV_INVESTIGATION_CAPABILITIES_AND_CASES_v2.pdf`: a ten-page explanation of the capabilities and the four cases.
- [docs/MILESTONE_LOG.md](docs/MILESTONE_LOG.md): the full milestone-by-milestone history that used to be this README.

## Licence, contributing and citation

MIT licence (see [`LICENSE`](LICENSE)). Third-party packages keep their own
licences; the inventory is in `docs/environment.md`. Issues and pull requests
are welcome; [CONTRIBUTING.md](CONTRIBUTING.md) explains the ground rules, the
most important being that hidden truth (`runs/`, `private_eval/`) never goes into
git. To cite the simulator, use [CITATION.cff](CITATION.cff) or GitHub's
"Cite this repository" button.
