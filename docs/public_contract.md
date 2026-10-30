# Public contract 1.0 — M0 accepted on 17 October 2026

The independent recheck accepted the M0 contract and timing amendment at
`20655ca`; see `docs/evidence/M0-acceptance-20261017.md`. This does not verify
unimplemented M1 execution or authorize progression.

Generated schemas: `schemas/{public_task,action,observation,decision}.schema.json`
(relative to the repository root). The normative source is
`src/pv_sim/contracts.py`. All records are frozen, extras forbidden, scalar types
strict, numbers finite. Collections use tuples internally and JSON arrays on the
wire. JSON numbers may be integral when a continuous number is expected; strings
and booleans are rejected. JSON arrays are parsed at the JSON boundary.

The eight action kinds follow plan §6.2. Constructing a validated action is not
acceptance or execution. There is no action executor at M0. Advertised capability,
sensor, nominal calibration, hypothesis and past-observation reference checks are
separate public-context validators. Runtime budgets, IDs across requests, cached
retries, timeout and physics protection belong to M1.

Missing scalar/encoder/RGB values are null, with `validity=missing`. Other statuses
retain values and original capture times. Delivery cannot precede capture. RGB
records carry 640×480 RGB PNG bytes in base64, with no metadata chunks, appended
data, host path, segmentation, true pose or depth fields. Exposure midpoint and
interval consistency are validated. All image fixtures in unit tests are expressly
payload-validation examples, not evidence of a successful render.

Plan §6.4 leaves nested field names/containers unspecified. This initial encoding
uses named records for limits, budgets and weights; hypothesis probabilities are
an immutable array of `{hypothesis, probability}` records, with unique labels and
sum one. Context validation requires exactly the publicly declared label set.
`ActionFeedback.commanded_target` is the original typed action or null for malformed
input. `measured_confirmation` contains timestamped allowed samples and ages as of
the containing observation's delivery. These initial choices were accepted at M0;
M1 must preserve their semantics. Public schema generation cannot encode every cross-field check;
Pydantic and the contextual validators remain necessary.

Independent review on 16 October found that the initial PNG validator did not
fully enforce its wire format. The first correction now checks the initial
13-byte IHDR (640x480, 8-bit truecolor and valid methods), chunk order and CRCs,
and an empty terminal IEND. Bounded decompression requires one complete IDAT
zlib stream with exactly the RGB8 scanline count, then Pillow verifies and fully
decodes the image. Interlaced RGB8 and multiple contiguous IDAT chunks remain
supported. The 2,800,000-character payload limit, metadata rejection and public
fields are unchanged. This is format validation, not a guarantee against hidden
information encoded into valid pixels. See `M0-png-review-response.md` under
`docs/evidence/`; the independent 17 October recheck accepted this correction.

Identifiers restrict syntax and exclude paths; producing truly opaque identifiers
remains the trusted producer's responsibility. Free-text rationale is not an
information-flow guarantee. The contracts import no engine/config/evaluator modules.
There is no private scenario generator or private scenario schema at M0.

Timing amendment accepted by independent review: the pilot exposure is now
12 ms with the unchanged 2 ms tick, so a tick-aligned start has a midpoint three
ticks later and an end six ticks later. Configuration validation rejects exposures
whose midpoint falls between ticks or collapses to zero ticks; it never substitutes
a rounded capture time. The midpoint must be at least one tick after the start.
See `docs/decisions/0006-exposure-timing.md` for the user-authorized change to the
v7 default, rationale, scope and review status. No scheduler exists at M0.

The generic `RGBSample` wire format remains version 1.0 and still validates
duration/interval/midpoint consistency without importing private configuration.
Historical 10 ms wire fixtures remain valid as standalone records; a configuration
using that duration with the pilot's 2 ms tick is now rejected. M1 must construct
actual captures using the accepted configuration and validate public context.
