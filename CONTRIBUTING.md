# Contributing

Thanks for your interest. Questions, bug reports and ideas are welcome as
[GitHub issues](https://github.com/hewei8622/agent_pv/issues). For code changes,
open a pull request against `main`.

## Set up

```bash
git clone https://github.com/hewei8622/agent_pv.git
cd agent_pv
uv sync --locked --group dev
```

See the [README](README.md#3-quick-start) if you do not have uv yet.

## Before you open a pull request

```bash
uv run ruff check .
uv run pytest tests/unit tests/integration tests/security -q
```

Both should pass. Camera tests need a desktop graphics session and skip
themselves elsewhere; say in the pull request whether you ran them.

## Ground rules

- **Keep hidden truth out of git.** `runs/` and `private_eval/` hold run
  outputs, seeds and the true world settings that the evaluator scores against.
  They are ignored on purpose; never force-add them. A test case whose answer
  is in the repository can no longer be used for fair scoring.
- **Respect the public/private boundary.** A policy may only use what the
  public task and observations give it. New world features go on the private
  side and are exposed through sensors or typed replies (README section 8).
- **Change contracts deliberately.** The JSON schemas in `schemas/` and the
  Pydantic models are the interface every policy relies on. If you change one,
  update the schema, the tests and the docs in the same pull request.
- **Small, explained commits.** Say what changed and why in plain words.

## Notebooks

Notebooks are kept as percent-format scripts (`notebooks/*.py`) next to the
executed `.ipynb`. Edit the script, then rebuild and execute the notebook so the
two stay in step.
