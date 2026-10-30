# M0 desktop render — image and live suite passed; review pending

Historical checkpoint: this report predates the independent PNG-validation
finding. The original render/tests remain valid evidence, but general contract
acceptance is superseded by the failed review and its pending correction review.
See [the current PNG review response](M0-png-review-response.md).

Wei executed the existing environment verifier in macOS Terminal at
2026-10-16 10:09:09 UTC. Command label: `m0-desktop-20261016T100908Z`.
Exit code 0; elapsed 0.791 s. Source revision at capture: `6b6a8c4`.

Actual evidence: `runs/m0-desktop-20261016T100908Z/environment.json`,
`agent_rgb.png`, `calibration.xml`; command/stdout/stderr are recorded under
`runs/m0-setup/evidence/`. All input hashes and the PNG hash were independently
checked against the saved files in the implementation session.

| Item | Observed value |
|---|---|
| Project interpreter | Python 3.11.17 in `.venv/bin/python` |
| Recorder interpreter | Conda Python 3.12.12; used only to launch and record the command |
| Engine / renderer | MuJoCo 3.3.7 classic; `mujoco.cgl`, no GL override |
| OpenGL | Apple / Apple M4 / `2.1 Metal - 89.4` |
| Camera | `agent_rgb`, fixed on body 2, optical centre `(0,-0.45,0.35)` m |
| Headlight | Disabled |
| Image | 640×480 RGB uint8; values 0–255; 478 unique colours |
| Pixel standard deviation | 30.47398371687498 |
| PNG SHA-256 | `feb98b0181b2a9826f9062675b0eced712055ed4e0b0466f2a8343a0ccb8fd90` |

The implementer opened the actual PNG with `view_image` and visually inspected it:
eight blue tiles inside a silver border, with red/green/blue sphere markers on a
grey floor. The board is centred and fully visible. No image generation, editing
or mocked rendering was used. The static calibration scope is unchanged.

This successful default-context render strongly localizes the earlier failures
to execution-context differences. It does not identify a specific denied macOS
permission, or establish that the restricted agent shell now supports graphics.
Initial setup comprised two agent-context attempts and one subsequent successful
user desktop probe. Wei then ran the live-render suite documented below.

## Checks and one bounded test repair

Command 032 applied the five existing image/camera assertions to the saved real
capture without opening OpenGL: two passed, three projection checks failed.
The detector selected only brightly lit sphere pixels, biasing centroid y by
2.3–2.5 pixels. The failed results remain preserved.

Decision `docs/decisions/0004-fiducial-measurement.md` records one repair: measure
the coloured silhouette using material chromaticity, retaining dim pixels. Camera
geometry, expected coordinates and the original 2-pixel tolerance are unchanged.
Six added unit cases cover shading invariance and detection of displaced markers.

| Command | Result |
|---|---|
| 032-saved-desktop-render-checks | Exit 4; 2 passed, 3 failed; preserved initial measurement defect |
| 033-fiducial-regression | Exit 0; **91 unit tests passed**, 0 failures/skips; 3.10 s |
| 034-fiducial-lint | Exit 0; Ruff passed |
| 035-saved-render-repair-1 | Exit 0; **all 5 saved-capture assertions passed** |

The saved-capture checks are distinct from the subsequent live-render pytest run.
No further renderer attempt was made by the implementer.

## Final live suite

Wei ran the following in the same desktop Terminal at 10:17:16 UTC:

```sh
env -u MUJOCO_GL python3 scripts/record_command.py --label m0-desktop-tests-20261016T101716Z --timeout 180 -- uv run --locked python -m pytest tests/unit tests/render -q --junitxml=runs/m0-desktop-tests-20261016T101716Z.xml
```

Exit 0; command elapsed 1.508 s. Pytest reported **96 passed in 1.19 s**.
The implementer inspected the actual JUnit file: 96 tests, zero failures, errors
or skips; suite time 1.188 s. It includes all five render cases: nonblank named
RGB, independent camera basis, and three analytic marker-projection checks.
The fixture rendered afresh during this suite.

- JUnit: `runs/m0-desktop-tests-20261016T101716Z.xml`
- SHA-256: `0b00eae8d739ae4e4f6797429cffd4ef9df069e3edf17d36e002dc191f272d8c`
- stdout/stderr: `runs/m0-setup/evidence/m0-desktop-tests-20261016T101716Z.{stdout,stderr}.txt`; stderr empty.
- Command metadata: matching label in `runs/m0-setup/evidence/commands.jsonl`.
- Tested source: `5061ac6dcbea5fefab181248cb98b31d457ea75d`; clean Git state
  and all 42 prior source hashes verified before this documentation update.

No implementation or test code changed after this passing suite. The earlier
failed evidence and checkpoint manifests remain intact. Final handoff hashes
and measured command timings are in `runs/m0-review-ready/handoff-manifest.json`.

M0 implementation checks are complete and ready for independent fresh-session
review. That review and Wei's explicit M1 approval remain pending; no M1 work has
begun. The active coding model/effort remains unverified by tools. The exposure
midpoint convention recorded in `docs/public_contract.md` is a reviewer concern
to resolve before M1 scheduling.
