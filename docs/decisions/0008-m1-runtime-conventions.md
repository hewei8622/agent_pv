# M1 runtime conventions and evidence boundaries

The authorized M1 slice is a static, unshaded eight-cell scene. Shared scene
records generate both MuJoCo geometry/lighting and optical quadrature. The
optical code certifies that the complete cell/reference beams clear the rig's
allowed swept volume; unsupported intersecting geometry is rejected. No M2
screens, noise, stalls, weather variation or diagnostic fault corpus is added.
Lighting uses fixed linear DNI/1000 diffuse and DHI/1000 ambient normalization.
These images are qualitative rendered observations, not radiometric PV sensors.

The clock uses 2 ms integer ticks. At reset, scalar/encoder samples are captured
at tick zero and initial state is recorded privately. Reset advances 20 ms to
deliver the initial scalar samples; this is charged elapsed physical time.
Each tick applies eligible commands, advances actual joint dynamics, updates
electrical/thermal state, accounts costs, captures, enqueues, and delivers.
Same-tick delivery ordering is scalar, encoder, RGB, then insertion sequence.
Configured periods are exact tick counts. User durations round up, action
deadlines round down; neither conversion hides extra elapsed time.

RGB is rendered from the actual midpoint snapshot, three ticks after exposure
start. A 12 ms exposure ends at start+6 ticks; delivery is end+50 ticks. Payloads
retain those timestamps. Only requested frames are produced, with a maximum
2 Hz start rate. Motion-triggered exposure starts after actual settlement.
Core tests disable the RGB capability explicitly; this is never a full M1 pass.

Measured camera settlement requires position errors at most 1 mm / 0.01 rad
and rates at most 0.005 m/s / 0.02 rad/s, continuously for 0.20 s. The low-rate
thresholds are declared M1 engineering criteria, not physical hardware limits.
Servos retain the frozen gains, caps, masses and trajectories. Commands update
actuator controls; q is written only during reset or historical render restore.

The load applies after 100 ms, slews at 10 V/s, and settles for 200 ms. A newly
accepted load command can reconnect a previous timeout-disconnected load only
at its delayed application tick. Completion includes delivered V/I captured
after settlement; requested voltage is not substituted for measured voltage.
Above open-circuit voltage, the measured reading is Voc and zero current.

A probe reserves all point tokens before work, then emits an `executing`
feedback record after each settled dwell. Each record confirms matched delivered
V/I from that dwell; the identical samples appear in its containing Observation.
The final `completed` feedback confirms restoration of the pre-probe requested
voltage, including delay/slew/settlement. B1 excludes restoration from point
selection. Confirmation ages are relative to the containing Observation time.

Every new valid or invalid request charges 0.20 s decision overhead. Canonical
retries with the same positive ID return the cached response without time or
cost, including schema-rejected JSON payloads with a valid ID. Conflicting IDs
are rejected. An unidentifiable malformed payload cannot have idempotent retries.
Resource gates reserve the full action timeout plus a 2 s tail before nonterminal
work. Path reservations include conservative braking allowances; actual travel
is charged. Multi-point probes cannot partially execute when over budget.

Timeout cleanup is distinct from action success. Movement halts through the
bounded trajectory and returns a newly delivered encoder measurement. Probe
restoration and disconnection, where necessary, are likewise measured. Cleanup
may use the reserved 2 s tail, is logged privately, and is charged to elapsed
time; a late cleanup still reports `timed_out`. An explicit `safe_stop` disconnects and
brakes, even if the requested timeout is shorter than a physical stop. It becomes
terminal `safe_stop` only after measured low rates and disconnection. A horizon
can instead interrupt cleanup; an otherwise unconfirmed bounded stop is an
explicit incomplete error, never successful safety evidence.

The preliminary reviewer separately identified an unexercised travel-budget
overrun branch that stopped advancing through the generic protection path.
The M1 follow-through now latches that guard, cancels pending load/RGB work,
disconnects, and unwinds the action before advancing bounded physical braking.
Fresh scalar and encoder confirmations are required before terminal `safe_stop`.
The cleanup deadline is fixed at the trigger plus the reserved 2 s; horizon
and protection events take precedence. Missing confirmation raises an explicit
incomplete-stop error and prohibits further advancement until reset. Actual
braking travel and time remain charged. Test-only boundary setups exercise this
branch without changing default reservations, gains, or tolerances.

Thermal energy uses frozen electrical/absorbed power at the interval's initial
temperature after eligible load commands; exact linear cooling integrates heat
loss/storage. End-of-tick V/I/T samples are recomputed at one common instant.
The ledger reports raw PV/absorbed/heat-loss/storage joules and separate actual
travel, actuator work proxy and policy wall time. The optional weighted utility
is dimensionless. There is no claim of net harvested energy or causal superiority.

The B1 pilot uses home/side images, a fixed three-point probe, measured point
choice, a new verification observation and a 2 s retained-load tail. B0 is
implemented and tested independently. The three authorized complete development
pilots are B1 seeds 11/23/47; deterministic M1 has no random perturbations, so
these are three reproducibility runs, not three distinct fault scenarios.
Replay follows recorded actions without policy re-querying. Frozen same-host
replay limits are numeric absolute/relative 1e-10, decoded maximum pixel error
2 and mean absolute pixel error 0.1 in 8-bit channel units. Those are engineering
repeatability limits, not cross-GPU image guarantees or model accuracy claims.

Trusted local policies receive JSON public task/history only. Private config,
source fingerprints, seed streams, actual transforms, irradiances and scores
remain evaluator records. Python process isolation is not claimed. Independent
review and Wei's further approval are required before M2.
