#!/usr/bin/env python3
"""Build an offline evidence replay without running physics, rendering or control."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pv_sim.workflow_replay import build_replay_index, public_export, write_replay


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public-dir", type=Path, required=True)
    parser.add_argument("--evaluator-dir", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--public-output", type=Path)
    parser.add_argument("--title", default="PV investigation: sensing, probing and verification")
    parser.add_argument("--policy-label", default="B1 fixed procedural scan · retained evidence")
    args = parser.parse_args()
    if args.public_output and args.public_output.resolve() == args.output.resolve():
        parser.error("Public and evaluator outputs must be different files")
    outputs = [args.output] + ([args.public_output] if args.public_output else [])
    for output in outputs:
        if output.exists() or output.with_suffix(".manifest.json").exists():
            parser.error(f"Refusing to overwrite retained output: {output}")
    index = build_replay_index(
        args.public_dir,
        evaluator_dir=args.evaluator_dir,
        title=args.title,
        policy_label=args.policy_label,
    )
    for output in outputs:
        payload = public_export(index) if output == args.public_output else index
        manifest = write_replay(payload, output)
        output.with_suffix(".manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        print(json.dumps({k: v for k, v in manifest.items() if k != "sources"}, indent=2))


if __name__ == "__main__":
    main()
