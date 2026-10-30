# M0 scope and implementation plan

The direct user request selects the existing empty `env` folder in the authorized
workspace. an earlier default location does not exist and is
outside this session's writable roots. It was inspected, not created. This is an
explicit user override of the handoff's default location outside supervision.
No applicable ancestor AGENTS.md was found; the parent is not a Git repository.

User approved project-local official PyPI uv installation and uv-managed Python
3.11. All tools, caches and environments stay here; no global installation or
remote shell installer. Repository remains private with no licence grant, as
selected by the user. Dependency licences are recorded separately.

Requested coding setting: GPT-6 Astra / ultra. Available tools do not expose
authoritative active-session metadata. User replied “I will select it to ultra”.
This records that statement, not verification of either active setting. No other
model session or reviewer is launched.

M0 only:
1. Preserve/hash handoff files; record commands, host and Git state.
2. Create pyproject.toml, .python-version, uv.lock, .gitignore and LICENSE.
3. Implement src/pv_sim/{__init__,contracts,config,cli,calibration}.py.
4. Add complete configs/pilot.toml and configs/tolerances.toml; export public
   schemas with scripts/export_schemas.py. Add scripts/verify_environment.py.
5. Add meaningful tests/unit and tests/render; record initial results and repairs.
6. Reproduce a clean locked install, render 640×480 RGB from agent_rgb, inspect
   the PNG, record versions/licences/hashes and docs/{environment,public_contract,
   model_card,evidence/M0}.md plus README.md. Commit the real lock and source.
7. Stop for independent fresh-session review and Wei's explicit approval.

M1 is planned only: actual rail/yaw/pitch servos, PV/thermal/optics, scheduler,
actions, costs, public/private logs, B0/B1 and replay. No M1 files, policy runs,
physics implementation, or later-stage scaffolding in this milestone.
