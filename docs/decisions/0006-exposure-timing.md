# Accepted exposure timing amendment

Status: accepted by the independent M0 recheck on 17 October at `20655ca`.
The reviewer reproduced 27 timing boundary cases and all 132 unit tests. The
full verdict is `output/review/M0_INDEPENDENT_RECHECK_20261017.txt`.
No M1 scheduler or capture execution is implemented or approved by this record.

## Authority and conflict

The original v7 plan §6.1 specifies 2 ms integer ticks and a 10 ms exposure with
an actual midpoint snapshot. Starting at tick n would put that midpoint at
n + 2.5 ticks. The independent M0 review required an explicit reviewed resolution
before M1. The preserved original planning files are not edited.

After the implementer proposed 12 ms exposure with unchanged 2 ms ticks and a
separate reviewer, Wei replied: "yes continue 2-3 and you can launch the separate
reviewer etc needed". This authorizes preparing the amendment and launching a
fresh-context reviewer. It does not approve M1 or pre-approve the review result.

## Selected amendment

Change the pilot default `sensors.rgb_exposure_s` from 0.010 to 0.012 seconds.
Keep `simulation.dt_s = 0.002` seconds. For a start at integer tick n:

| Event | Tick | Offset from start |
|---|---:|---:|
| Exposure starts | n | 0 ms |
| Snapshot of the actual state | n + 3 | 6 ms |
| Exposure ends | n + 6 | 12 ms |

The interval remains half-open `[start, end)`. The midpoint remains a single
instantaneous snapshot approximation, not an integrated image. The M1 scheduler
must use the actual state at n + 3 and retain it for later delivery; it must not
round timestamps or render a later state under an earlier timestamp.

This deliberately lengthens the nominal exposure by 2 ms while preserving the
2 ms dynamics/thermal step and the existing configured latency, rate and budget
values. It adds one tick to the exposure interval; future action completion and
budget accounting must include the actual interval. No physical-camera fidelity
or motion-blur model is implied. The existing M0 calibration render is static
and independent of this exposure setting.

Using a 1 ms tick could preserve 10 ms exposure but would alter the planned world
step and double the tick count for the same simulated horizon. Rounding to 4 or
6 ms would mislabel the midpoint. Changing to 12 ms is the bounded amendment
selected for review; it is not evidence that 12 ms is physically calibrated.

## Validation and compatibility

Configuration validation already requires the whole exposure to span integer
ticks. It now also requires its half-duration to span positive integer ticks,
using the existing 1e-9 tick arithmetic tolerance. This handles floating-point representation
and does not permit runtime rounding to a different state. Odd-tick exposures
such as 2, 6, 10 and 14 ms are rejected; even-tick alternatives remain valid.
The committed pilot default is 12 ms.

The public wire schema and `RGBSample` remain unchanged. A standalone historical
10 ms record can still be internally consistent; public records do not import a
private clock. M1 must connect the accepted configuration to its producer and
context checks. This amendment does not claim that runtime connection exists.

The eight initial configuration regressions first produced five failures and three
passes against the original configuration/validator; the first implementation
and its affected checks are recorded under `runs/m0-timing-20261017/`. Earlier
failures and the 127-test desktop evidence remain unchanged. The new full suite
initially had 135 cases (130 unit and five render), but no 135-test live result is
claimed without running it. The independent reviewer assesses whether the new affected
checks and unchanged static-render evidence satisfy M0.

## Reviewer-found lower-bound correction

The fresh reviewer found that 1e-12 s and 1e-15 s exposures were still accepted:
both their whole and midpoint tick counts fall within the arithmetic tolerance
of zero. A positive real duration is insufficient to establish a positive integer
duration on this clock. The midpoint check now also requires its nearest integer
tick count to be at least one, making the minimum representable exposure two
ticks (4 ms). The existing 1e-9 tick arithmetic tolerance is unchanged. The pilot
continues to use six ticks (12 ms).

Both tiny durations were added as regressions. Before this repair the ten-case
timing selection had two failures and eight passes. This is the first bounded
repair of the timing invariant; original failures remain preserved. The current
suite comprises 132 unit cases and five render cases. No 137-case live run is
claimed without executing it. After this repair all ten timing cases passed in
0.08 s and all 132 unit cases passed in 1.18 s; lint and schema checks passed.
The independent recheck accepted this correction. Its 27 boundary cases include
zero, both tiny positive counterexamples and each integer millisecond from 1–24.
