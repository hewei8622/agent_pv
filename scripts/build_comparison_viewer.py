#!/usr/bin/env python3
"""Build a source-bound offline R/A replay; never render, run physics or call a model."""

import argparse
import json
from pathlib import Path

from pv_sim.comparison_viewer import build_comparison_index, public_export, write_comparison


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--public-output", type=Path)
    parser.add_argument("--public-only", action="store_true")
    args = parser.parse_args()
    outputs = [args.output] + ([args.public_output] if args.public_output else [])
    if len({p.resolve() for p in outputs}) != len(outputs):
        parser.error("Choose distinct public and evaluator outputs")
    for path in outputs:
        if path.exists() or path.with_suffix(".manifest.json").exists():
            parser.error(f"Refusing to overwrite retained output: {path}")
    index = build_comparison_index(args.manifest, evaluator=not args.public_only)
    for path in outputs:
        data = public_export(index) if path == args.public_output else index
        manifest = write_comparison(data, path)
        with path.with_suffix(".manifest.json").open("x") as stream:
            json.dump(manifest, stream, indent=2)
            stream.write("\n")
        print(json.dumps({k: v for k, v in manifest.items() if k != "sources"}, indent=2))


if __name__ == "__main__":
    main()
