# Controlled source response validation

On 19 October 2026, Wei said "sound good go ahead" after the planning addendum
identified validation of one controlled output-change scenario as the next
implementation step. This authorizes step 1 of the
[interactive prototype plan](../planning/interactive-pv-prototype-v1.md), followed
by evidence review. It does not start the human or internet interface or declare
the full historical M3 milestone complete.

## Frozen fixture

The [protocol](../../configs/source_response_protocol.json) fixes an eight-second,
noise-free comparison at 1.8 V. Initial direct irradiance is 800 W/m² and diffuse
irradiance is 100 W/m². The treatment changes direct irradiance to 400 W/m² at
exactly 2 s; the control remains unchanged. Geometry, transmission, temperature
initialization, camera, load and all other conditions match. The panel and
reference receive 900 W/m² before the change and 500 W/m² afterward.

The private source schedule is optional. When absent, canonical configuration
hashes and behavior of the accepted M2 fixtures are preserved. Only direct
irradiance changes; source direction, diffuse irradiance and geometry stay fixed.
No public action can alter the source. At the event boundary, complete the
preceding thermal interval with the old source, then update irradiance,
instantaneous electrical state and actual renderer lighting before sensor
capture. Temperature and cumulative energy remain continuous at that boundary.

## Independent expectations

For uniform forward-biased cells with zero series resistance, derive current
directly from the declared cell law: I = Isc × (1 − V / (8 × Voc_cell)). Check
that 0 < I < Isc, so no bypass branch is active. Expected current does not call
the production root solver. Independently integrate
30 dT/dt = 0.054 E − V I(E,T) − 0.6(T−25) with RK4 and a 0.5 ms step;
repeat at 0.25 ms to establish reference convergence. The reference imports no
production PV, optics or thermal implementation.

Freeze tolerances before comparison: 1e-12 A for current at recorded temperature,
1e-11 W for power, 5e-6 K for the temperature trajectory, 1e-9 K for reference
refinement, 1e-4 J for electrical energy and 1e-8 J for absorbed energy and energy
balance. The production thermal update freezes power within each 2 ms interval;
the continuous reference does not. Over this fixture's 25–45 °C range,
|dP/dT| < 0.0022 W/K and heating < 1.62 K/s bound the expected accumulated
temperature discretization error below approximately 1.9e-6 K even at 12 s.
These are numerical consistency tolerances, not measured sensor accuracy.

Starting at 25 °C, the panel keeps warming after the drop, at a reduced rate and
below the control temperature. The control's power also changes slightly with
temperature. No claim of instantaneous cooling or exactly proportional power
is made. The public reference sensor already makes this source change observable;
the fixture does not establish a need for external information gathering.

## Evidence and limits

Retain raw private truth/configuration and independent reference traces, public
sensor observations, commands, source hashes and checks. Validate exact capture
and delivery ordering and preservation of captures delivered after the source
change. Actual RGB must use the same source's classic-renderer light mapping:
diffuse 0.8 to 0.4 and ambient 0.1 unchanged. Brightness comparison is qualitative;
RGB is not calibrated radiometry, and cell materials do not encode electrical
state or temperature.

Use short deterministic fixtures, not additional complete policy pilots. The
agent's previous CGL attempts remain exhausted; prepare the new render checks
for Wei's working desktop Terminal. Keep this step pending until actual images
are inspected and the independent review is complete. Preserve earlier reports,
failed runs and accepted manifests. No new engine, dependency installation,
paid model call, external message or hardware operation belongs to this step.
