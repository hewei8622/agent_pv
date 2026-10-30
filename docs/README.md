# Documentation

Start with the repository [README](../README.md) and the two notebooks in
[`notebooks/`](../notebooks). The pages below go deeper.

## Using the simulator

- [Public contract](public_contract.md): what a decision policy may see and do.
- [Interaction interface](interaction-interface.md): the typed actions, observations and replies.
- [Investigation workflow](investigation-workflow.md): running an investigation and building a replay.
- [Paired investigation](paired-investigation.md): comparing two policies on the same hidden cases.
- [Model card](model_card.md): what the physical models represent and where they stop.
- [Environment](environment.md): toolchain, dependency versions and licences.
- [Interaction test guide](testing/interaction-test-guide.md): how the tests are organised.

## Development record

[`MILESTONE_LOG.md`](MILESTONE_LOG.md), [`decisions/`](decisions) and
[`evidence/`](evidence) record how the simulator was built and reviewed between
16 and 19 October 2026, and [`planning/`](planning) holds early design notes.
They are kept for transparency. Their links into `runs/`, `private_eval/` and
the independent review notes refer to local artefacts that are not published:
run outputs and hidden truth are deliberately kept out of version control.
