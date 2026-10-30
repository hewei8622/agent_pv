# M2 observation and action conventions

M2 adds an optional private `m2` configuration record. Its absence retains the
canonical M1 configuration digest and deterministic captures. Public schemas
remain version 1.0 unchanged; the new `private_scenario.schema.json` describes
the expanded evaluator configuration, not a policy-accessible scenario tool.

## Captures and delivery

Scalar and encoder noise uses the v7 nominal Gaussian sigmas. Each draw uses a
fresh PCG64 generator keyed by SHA256 of compact JSON containing the versioned
capture namespace, named stream seed, channel, capture tick and purpose. Adding
actions or earlier draws does not advance later noise. The existing named seed
namespace is preserved; M2 manifests also record the capture namespace.

Numeric V/I/T/reference channels have separate Gaussian errors and one common
transport outcome for a simultaneous capture. Encoder axes have independent
errors. No rate-noise model or physical sensor measurement range was specified:
noisy encoder rates are omitted, and noisy measurements are not clipped to
actuation limits. RGB pixels remain noise-free. This is simulated instrument
noise, not evidence of calibrated physical sensors.

Configured extra delay and inclusive uniform integer-tick jitter affect only
delivery. Scalar/encoder latency starts at capture; RGB latency starts at the
end of its unchanged 12 ms exposure. Dropout emits an explicitly missing/null
record at its scheduled delivery, still charging the requested capture. A stale
record retains all original values/pixels and timestamps; `stale` means age at
transport delivery strictly exceeds the configured threshold. Additional age
at observation is recoverable from timestamps. Later transport packets never
replace an earlier capture with a newer pose or value.

Reset captures tick zero, drains zero-latency events and advances the nominal
numeric latency (20 ms). With delayed/noisy transport the first observation may
contain fewer or no scalar packets; it does not fabricate them or reset time.
Confirmation caches retain the freshest valid capture; late older, missing and
stale packets remain in public history but cannot verify action application.

For M2, an exposure can start if its physical interval fits before the action
deadline, even when delivery will be late. The action reports a sensor timeout;
a later move/wait can receive its historical packet. Waiting creates no new RGB.
Stale/missing packets do not produce completed valid-image feedback. Ordinary
scalar/encoder acquisitions continue through action and cleanup time.

## Actuation and cleanup

Private fixture schedules identify issued command ordinals, not public action
IDs. Counters reset per episode, include probe restoration, and exclude rejected
requests and idempotent retries. Configured load commands can silently drop or
receive an added tick-exact delay. The private actuation stream distinguishes
issued, applied, dropped and cancelled commands; replay compares this stream.
No hidden failure label enters public feedback.

The move-stall fixture is specifically drive-command inhibition: finite servos
brake/hold while actual MuJoCo integration continues. It is not a mechanical
obstruction model, a teleport, frozen qpos or a gain change. Public acceptance
acknowledges a request; completion still requires actual settlement and fresh
valid measured feedback. Unchanged motion/load produces a tracking timeout.

The action gate applies advertised narrowed camera/load limits even for direct
trusted environment calls. Rail-lock exposes slide limits (0,0), retaining the
pan/tilt action. Timeout recovery has one fixed reserved two-second cleanup
window. Failed probe restoration leaves time for disconnection confirmation;
it cannot repeatedly extend that window. Missing measured stop confirmation is
an explicit incomplete error that blocks further stepping until reset. Pending
load commands are cancelled before they could reconnect during later waits.

## Visibility fixtures

F1 moves the declared reference patch to (0.40,0.10,0.01) m. Its unobstructed
home ray is outside the field of view; bounded yaw/pitch reframes it without
translation. F2 uses a finite box centred at (0,-0.15,0.125) m, half-depth 0.001 m,
half-height 0.125 m and half-width 0.03 m (narrow) or 0.06 m (wide).
One immutable screen record generates MJCF, view-ray intersections and source
clearance checks. Narrow-screen centre rays clear at lateral endpoints; wide
screen rays remain blocked over the whole allowed rail. Rotation preserves the
optical centre and cannot disocclude the same point.

These fixtures certify that screens do not intersect the source beams. New
partial-shading or self-shadow physics remains M3 work. Production frames have
no fiducial overlays. Separate calibration scenes use a visible locator only to
test analytic image projection/visibility and are labelled accordingly.
