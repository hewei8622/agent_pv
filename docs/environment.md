# Actual M0 environment — desktop graphics verified

Observed 16 October 2026. Initial imports and a subsequent clean locked installation/import/unit-suite reproduction passed. The real render subsequently succeeded in Wei’s desktop Terminal with the same pinned versions. The agent shell’s graphics access remains unresolved. This does not establish cross-host reproducibility.

| Item | Actual value |
|---|---|
| Host | macOS 15.7.4 (24G517), Darwin 24.6.0, arm64; Apple M4, 10 GPU cores |
| System Python | 3.9.6, unchanged; used only for local bootstrap/evidence runner |
| Project Python | 3.11.17, uv-managed, pinned in `.python-version` |
| uv | uv 0.13.1 (62faed335 2026-10-13 aarch64-apple-darwin) |
| Renderer | MuJoCo 3.3.7 classic, default macOS CGL; MUJOCO_GL unset |
| OpenGL vendor/version | User desktop: Apple / Apple M4 / 2.1 Metal - 89.4 |
| Initial agent-context graphics failure | `CGLChoosePixelFormat`: `invalid CoreGraphics connection`; user desktop succeeded |
| Network | Enabled by session policy; actual PyPI wheel and Python download succeeded |
| Tools | zsh, exec_command, apply_patch, rg, git, curl and view_image exposed; actual desktop PNG inspected |
| Session model/effort | Unverified; requested Astra/ultra; user said they will select ultra |

## Installed packages and licence metadata

All entries below are read from the actual installed distributions. Full copied notices and hashes are in `runs/environment/dependency_notices/` and `runs/environment/environment.json`.

| Package | Version | Licence metadata |
|---|---|---|
| absl-py | 2.5.1 | Apache-2.0 |
| annotated-types | 0.8.0 | MIT |
| etils | 1.14.0 | Apache-2.0, bundled notice inspected |
| fsspec | 2026.9.0 | BSD-3-Clause |
| glfw | 2.11.0 | MIT |
| hypothesis | 6.170.0 | MPL-2.0 |
| iniconfig | 2.3.1 | MIT |
| mujoco | 3.3.7 | Apache-2.0 |
| numpy | 2.4.6 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause |
| pillow | 12.3.0 | MIT-CMU |
| pluggy | 1.7.0 | MIT |
| pv-investigation-sim | 0.0.1 | MIT (since 30 October 2026; private with no licence grant before) |
| pydantic | 2.14.1 | MIT |
| pydantic_core | 2.50.1 | MIT |
| Pygments | 2.21.0 | BSD-2-Clause |
| PyOpenGL | 3.1.10 | BSD-style core terms plus distinct bundled-component notices retained from exact source release |
| pytest | 9.1.1 | MIT |
| ruff | 0.17.1 | MIT |
| sortedcontainers | 2.4.0 | Apache 2.0 |
| typing-inspection | 0.4.4 | MIT |
| typing_extensions | 4.16.0 | PSF-2.0 |
| zipp | 4.1.1 | MIT |

At M0 the repository was private with no licence grant; it was released under the MIT licence on 30 October 2026. No third-party scene assets were downloaded. Optional pvlib 0.13.1 is resolved in uv.lock but not installed or used (M3). The continuation recorded 33 runtime/dev/bootstrap/build package entries plus CPython and PyOpenGL source notices in `runs/m0-continuation/licences/inventory.json`. uv carries MIT/Apache-2.0 notices; CPython’s full composite notice is retained. Exact build versions are pinned in pyproject.toml/uv.lock: Hatchling 1.32.4, packaging 26.3, pathspec 1.1.1, pluggy 1.7.0, tomlkit 0.15.2, trove-classifiers 2026.9.21.13, editables 0.6. The source archive hash is verified against exact-release PyPI metadata; no archive code was executed. This is a licence evidence record, not legal clearance.

## Sources consulted

- [MuJoCo 3.3.7 Python API](https://mujoco.readthedocs.io/en/3.3.7/python.html): default rendering context, thread ownership and macOS mjpython semantics.
- [MuJoCo 3.3.7 XML reference](https://mujoco.readthedocs.io/en/3.3.7/XMLreference.html): fixed named camera, xyaxes, headlight and offscreen framebuffer.
- Installed MuJoCo 3.3.7 `renderer.py`, `cgl/__init__.py`, and `cgl/cgl.py` inspected after the context failure.
- [uv installation](https://docs.astral.sh/uv/getting-started/installation/): official PyPI wheel in an isolated environment; approved by Wei. No remote shell installer.
- [Codex configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference): effort availability depends on model/client; documentation does not verify an active session.
- Versioned Pydantic 2.12/2.14 documentation fetches failed; no claim that those pages were successfully used. Strict/frozen/finite behaviour was checked against the installed 2.14.1 runtime in tests.

## Original attempt input hashes

```json
{
  "uv.lock": "1091f90997b249d3aa5b2810e3b01a913de1439d32a8936a1e5b4f47986a117c",
  "pyproject.toml": "00d18584b477dbc2bc93acbdd1a9207719b0fbe7e4110adb935f29126334fe22",
  ".python-version": "994bd8b49c741ad0971f8134ae4199fb91148e6b591623f51302165e390cf4e0",
  "configs/pilot.toml": "1b90debe91c92a9e38acdc7710b5046b3c612c857a76a2926499f470c8438caa",
  "configs/tolerances.toml": "1993c6467d32a6c2b54ab83ad237fface1a83ad8d82af749957e37c44dd1757d"
}
```

The original attempt also hashed three planning handoff files that are not part of
the public repository.

## Local command environment

`scripts/record_command.py` prepends `.tools/bootstrap/bin` and places UV caches, managed Python, tools, and pip cache under `.tools`. `UV_LINK_MODE=copy` avoids filesystem link assumptions. Exact overrides are included per command in the JSONL log. No system or global installation was made.

For a reviewer-approved future attempt, from this repository root:
```sh
python3 scripts/record_command.py --label reviewer-m0-render -- uv run --locked python scripts/verify_environment.py --render --output runs/reviewer-environment
```
This is a proposed reviewer command, not executed here. Do not reuse an existing label/output. The two-attempt limit for this implementation session has been reached.

## Clean-install continuation

`UV_PROJECT_ENVIRONMENT=.venv-repro-m0 uv sync --locked --group dev` created a second empty environment and installed the same 23 versions. Import/config probe exited 0; 85 unit tests passed; Ruff exited 0. New exact hashes and interpreter paths are in `runs/environment-repro-core/environment.json` and the continuation handoff manifest. Cached wheels and the pinned Python installation were reused. No render was attempted in this environment.

The build constraints use the [documented uv setting](https://docs.astral.sh/uv/reference/settings/#build-constraint-dependencies); the environment path uses [UV_PROJECT_ENVIRONMENT](https://docs.astral.sh/uv/concepts/projects/config/#project-environment-path). No runtime/dev package version changed when the build constraints were added to the lock.

## Successful desktop render

`runs/m0-desktop-20261016T100908Z/environment.json` records actual Python 3.11.17 and MuJoCo 3.3.7 with a working CGL context. The outer command recorder used Wei’s Conda Python 3.12.12; it launched the uv-managed project interpreter and did not replace it. The brief uninstall/install messages accompanied local project reinstallation; recorded dependency versions remained unchanged. See `docs/evidence/M0-desktop-render.md` for inspection and image-check results.

The subsequent desktop command `m0-desktop-tests-20261016T101716Z` exited 0:
96 tests passed in 1.19 s, including five tests using a fresh real render.
JUnit records zero failures, errors or skips. The source matched commit
`5061ac6` and all 42 hashes in the preceding handoff manifest.
This is the historical checkpoint. The subsequent independent review found a PNG
validation defect; its correction and acceptance status are recorded in
`docs/evidence/M0-png-review-response.md`.

## Return to env on 17 October 2026

The project was found back at `env`, with `env 3` absent. The main `.venv` still
contained an absolute interpreter link into `env 3`, so that link was broken.
It was preserved as `.venv-before-return-20261017`, then `uv sync --locked
--group dev` recreated `.venv` from the unchanged lock and installed the same 23
package versions. Python remains 3.11.17 and uv remains 0.13.1. No global Python
or packages changed. Cached dependencies and the existing managed Python were
reused; this is a location repair, not a new platform compatibility result.

Imports passed; 122 unit tests passed in 3.61 s with no failures/errors/skips;
Ruff and generated-schema checks passed. No graphics were attempted. The outer
recorder now reports Python 3.14.8, distinct from the pinned project interpreter.
Exact commands and evidence are linked in `docs/evidence/M0-return-env.md`.
Keep the project at its current location; historical auxiliary environments may
contain absolute paths and should not be treated as portable installations.

## Desktop recheck after the PNG correction

On 17 October at 06:42:37 UTC, Wei ran the real render and combined suite in macOS
Terminal. Both commands exited 0. The new PNG was inspected; all 127 tests passed
in 1.35 s, including five fresh-render cases with zero failures/errors/skips.
The project versions, default CGL context and Apple M4 OpenGL renderer match the
earlier successful desktop run. The outer recorder used Conda Python 3.12.12;
project execution used the pinned Python 3.11.17. See
`docs/evidence/M0-post-fix-desktop.md` for hashes and exact evidence paths.

The agent context still failed a separately preserved probe at 05:47 UTC with
`invalid CoreGraphics connection`. Desktop success does not establish that the
agent context can render or that the independent reviewer has accepted M0.
