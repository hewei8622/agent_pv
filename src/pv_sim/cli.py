"""Configuration checks and the bounded M1 rendered pilot / recorded-action replay."""

import argparse
import json
from pathlib import Path

from pv_sim import __version__
from pv_sim.config import load_config


def _pilot_limit(private_root: Path, seed: int) -> None:
    if seed not in (11, 23, 47):
        raise ValueError("M1 pilot seeds are limited to 11, 23, 47 before review")
    completed = []
    for path in private_root.glob("*/manifest.json"):
        manifest = json.loads(path.read_text())
        if (
            manifest.get("metadata", {}).get("purpose") == "m1_pilot"
            and manifest.get("status") == "complete"
        ):
            completed.append(manifest)
    if len(completed) >= 3 or any(m.get("seed") == seed for m in completed):
        raise ValueError("complete M1 pilot allowance exhausted for this seed; review required")


def run_demo(config, seed: int, policy_name: str, output: Path) -> dict:
    from pv_sim.env import PVEnv
    from pv_sim.policies.fixed import FixedPolicy
    from pv_sim.policies.scan import ScanPolicy
    from pv_sim.policy_runner import PolicyRunner
    from pv_sim.recorder import Recorder

    private_root = Path("private_eval")
    _pilot_limit(private_root, seed)
    recorder = Recorder(
        output,
        private_root,
        metadata={
            "purpose": "m1_pilot",
            "policy": policy_name,
            "scope": "synthetic integration evidence; no causal-performance claim",
        },
    )
    env = None
    try:
        env = PVEnv(config, enable_rendering=True, recorder=recorder)
        task, observation = env.reset(seed)
        history = [observation]
        policy = ScanPolicy() if policy_name == "scan" else FixedPolicy()
        runner = PolicyRunner(policy, task)
        failure = None
        while not history[-1].terminal:
            decision = runner.decide(tuple(history))
            env.ledger.policy_wall_s += runner.last_latency_s
            recorder.decision(decision, runner.last_latency_s, runner.last_failure)
            failure = failure or runner.last_failure
            history.append(env.step(decision.action))
        metrics = env.metrics()
        metrics["policy_adapter_failure"] = failure
        metrics["policy"] = policy_name
        # Completion must have measured evidence, not just a finish declaration.
        metrics["pilot_checks"] = {
            "finished": history[-1].terminal_reason == "finished",
            "verification_tail": metrics["verification_tail_complete"],
            "no_adapter_failure": failure is None,
            "energy_balance": abs(metrics["energy_balance_residual_j"])
            <= 0.001 * max(1.0, metrics["absorbed_j"]),
        }
        if policy_name == "scan":
            metrics["pilot_checks"].update(
                home_and_side_images=sum(len(o.rgb) for o in history) >= 2,
                measured_choice=policy.chosen_voltage is not None,
                newer_verification=bool(policy._verification_refs(tuple(history))),
                four_voltage_points=metrics["voltage_points"] == 4,
            )
        metrics["pilot_passed"] = all(metrics["pilot_checks"].values())
        recorder.finish(metrics)
        return {
            "manifest": str(recorder.manifest_path),
            "public_output": str(recorder.public_dir),
            "metrics": metrics,
            "exit_code": 5 if failure else (0 if metrics["pilot_passed"] else 4),
        }
    except Exception as exc:
        recorder.abort(type(exc).__name__, str(exc))
        raise
    finally:
        if env is not None:
            env.close()
        recorder.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="PV simulator: bounded M1 trusted local pilot")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate-config", help="validate and hash private JSON/TOML config")
    validate.add_argument("--config", type=Path, required=True)
    demo = sub.add_parser("demo", help="run one of the three authorized real RGB M1 pilots")
    demo.add_argument("--config", type=Path, required=True)
    demo.add_argument("--seed", type=int, required=True, choices=(11, 23, 47))
    demo.add_argument("--policy", choices=("fixed", "scan"), default="scan")
    demo.add_argument("--output", type=Path, required=True)
    replay_parser = sub.add_parser(
        "replay", help="replay recorded actions without querying a policy"
    )
    replay_parser.add_argument("--manifest", type=Path, required=True)
    replay_parser.add_argument("--output", type=Path, required=True)
    verify = sub.add_parser("verify", help="run the evaluator-only M2 development integrity suite")
    verify.add_argument("--suite", choices=("development",), required=True)
    verify.add_argument("--config", type=Path, required=True)
    verify.add_argument("--seed", type=int, choices=(20261016,), required=True)
    verify.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "verify":
        from pv_sim.verification import run_verification

        try:
            report = run_verification(args.config, args.seed, args.output)
        except (OSError, ValueError):
            parser.exit(2, "verification input refused: unreadable input or schema violation\n")
        print(json.dumps(report, indent=2, allow_nan=False))
        return report["exit_code"]
    if args.command == "replay":
        from pv_sim.env import RenderUnavailable, SafetyStopError
        from pv_sim.replay import ReplayError, replay

        try:
            report = replay(args.manifest, args.output)
        except RenderUnavailable:
            parser.exit(3, "required real camera is unavailable; incomplete evidence retained\n")
        except SafetyStopError:
            parser.exit(4, "bounded safety cleanup failed; incomplete evidence retained\n")
        except (OSError, ValueError, ReplayError) as exc:
            parser.exit(2, f"replay input refused: {type(exc).__name__}\n")
        print(json.dumps(report, indent=2, allow_nan=False))
        return 0 if report["status"] == "passed" else 4
    try:
        config = load_config(args.config)
    except (OSError, ValueError):
        # Do not echo private values or host paths across a CLI error boundary.
        parser.exit(2, "invalid configuration: unreadable file or schema violation\n")
    if args.command == "validate-config":
        print(f"valid configuration sha256={config.sha256()}")
        return 0
    from pv_sim.env import RenderUnavailable, SafetyStopError

    try:
        report = run_demo(config, args.seed, args.policy, args.output)
    except RenderUnavailable:
        parser.exit(3, "required real camera is unavailable; incomplete evidence retained\n")
    except SafetyStopError:
        parser.exit(4, "bounded safety cleanup failed; incomplete evidence retained\n")
    except (OSError, ValueError) as exc:
        parser.exit(2, f"pilot input refused: {type(exc).__name__}\n")
    print(json.dumps(report, indent=2, allow_nan=False))
    return report["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
