# First projection-check repair: measure the silhouette, not the lit cap

Wei ran the unchanged renderer from macOS Terminal on 16 October 2026 at
10:09:09 UTC. The real PNG and environment record are in
`runs/m0-desktop-20261016T100908Z/`. No additional renderer invocation was made
from the restricted agent session.

The image was visually inspected: eight blue tiles, silver border, and red,
green and blue sphere markers on a grey floor; no blank/mock substitute. The
image SHA-256 and all recorded input hashes match the current files.

The five existing render assertions were applied to the saved PNG and recorded
camera data. Shape/nonblank/named-camera checks and the camera basis passed.
All three marker projections failed: intensity >100 selected the lit top of
each sphere, shifting centroid y by -2.341, -2.293 and -2.451 pixels. This is a
measurement defect in the test, not evidence that camera projection is wrong.
The original results and measured residuals are retained as
`saved-render-checks.json` and `projection-diagnostics.json` in that run.

One bounded repair replaces brightness-selected regions with a chromaticity mask.
The fixture's sphere material ratio is 1/0.03 = 33.3, while the board's strongest
dominant/next channel ratio is 0.35/0.13 = 2.69. A ratio of 5 separates the declared
materials while retaining dim portions of the sphere; only zero signal is
excluded. The initial diagnostic comparison used a low 16/255 intensity cutoff;
the implemented method removes that arbitrary brightness cutoff entirely.

No camera geometry, render, calibration, expected projection, 2-pixel tolerance or
acceptance requirement changes. Six synthetic unit cases demonstrate that
asymmetric illumination does not shift the detected centre and that a 4-pixel
displacement still exceeds the original 2-pixel limit. Synthetic detector
fixtures are not counted as real rendering evidence. Fresh render-suite execution
still needs the working desktop context and independent review remains pending.
