"""Freeze or execute the four paired controlled-source development cases."""

import argparse
import json
from pathlib import Path

from pv_sim.comparison import ROOT, freeze_experiment, run_comparison


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze", type=Path, required=True)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    freeze = args.freeze.resolve()
    if ROOT / "private_eval" not in freeze.parents:
        parser.error("freeze must be inside project private_eval")
    if args.prepare:
        if args.output is not None:
            parser.error("--prepare does not execute a comparison")
        body = freeze_experiment(freeze)
        print(json.dumps({"status": "frozen", "cases": len(body["cases"]),
                          "execution_inputs": len(body["inputs"]), "path": str(freeze)}))
    else:
        if args.output is None:
            parser.error("execution requires a new --output")
        output = args.output.resolve()
        if output.parent != ROOT / "runs":
            parser.error("output must be a direct child of project runs")
        summary = run_comparison(freeze, output)
        print(json.dumps({"status": summary["status"], "pairs": summary["pairs"],
                          "successes": sum(r.get("evaluation", {}).get("success", False)
                                           for r in summary["results"]),
                          "episodes": len(summary["results"]),
                          "counterfactual_history": summary[
                              "context_counterfactual_identical_prequery_history"]}, indent=2))
        if summary["status"] != "complete":
            raise SystemExit(1)


if __name__ == "__main__":
    main()
