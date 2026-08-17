#!/usr/bin/env python3
"""Run a reproducible offline evidence chain for a supported backend.

For ``local-dry-run`` the chain covers: targets parsing -> preflight -> quote ->
account -> plan (dry-run) -> audit log -> evidence JSON. The adapter exposes no
submit, cancel, order query, or reconcile.

For ``mock-sim`` the chain additionally covers: simulated submit -> fill ->
order query -> open-order listing -> persisted state, plus an optional
restart-recovery check that resumes from the same state directory and reports
consistent positions and tracked order counts.

Each ``qexec`` step runs in an isolated subprocess with ``QEXEC_OUTPUTS_DIR``
pointing at the run directory, so audit logs, execution state, and evidence all
land inside one self-contained folder. Interrupted runs can be resumed from that
folder with the same backend.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from quant_execution_engine.paths import PROJECT_ROOT

DEFAULT_SYMBOLS = {
    "local-dry-run": "AAPL",
    "mock-sim": "AAPL",
}
DEFAULT_MARKETS = {
    "local-dry-run": "US",
    "mock-sim": "US",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="evidence_offline_chain",
        description="Reproducible offline evidence chain for local-dry-run or mock-sim.",
    )
    parser.add_argument("--broker", choices=["local-dry-run", "mock-sim"], required=True)
    parser.add_argument(
        "--run-dir",
        type=Path,
        default=None,
        help="Output/state directory, default: outputs/evidence-offline/<timestamp>",
    )
    parser.add_argument("--symbol", default=None, help="Symbol for the chain")
    parser.add_argument("--market", default=None, help="Market for the symbol")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Include broker-order steps (only meaningful for mock-sim)",
    )
    parser.add_argument(
        "--target-quantity",
        type=int,
        default=10,
        help="Target quantity for the mock-sim order (default 10)",
    )
    parser.add_argument(
        "--restart-check",
        action="store_true",
        help="After the chain, simulate a restart and re-read state consistency",
    )
    parser.add_argument(
        "--evidence-output",
        type=Path,
        default=None,
        help="Explicit evidence JSON path, default under the run directory",
    )
    return parser


def _write_targets_json(path: Path, *, symbol: str, market: str, target_quantity: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "asof": "2026-01-01",
        "source": "evidence-offline-chain",
        "target_gross_exposure": 1.0,
        "targets": [{"symbol": symbol, "market": market, "target_quantity": target_quantity}],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _env(run_dir: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(_REPO_ROOT / "src")
    env["QEXEC_OUTPUTS_DIR"] = str(run_dir)
    return env


def _run_qexec_step(
    name: str,
    *argv: str,
    run_dir: Path,
) -> dict:
    completed = subprocess.run(
        [sys.executable, "-m", "quant_execution_engine", *argv],
        cwd=str(PROJECT_ROOT),
        env=_env(run_dir),
        capture_output=True,
        text=True,
        check=False,
    )
    payload = {
        "name": name,
        "exit_code": int(completed.returncode),
        "stdout": completed.stdout.strip() or None,
        "stderr": completed.stderr.strip() or None,
    }
    print(f"\n== {name} ==")
    if payload["stdout"]:
        print(payload["stdout"])
    if payload["stderr"]:
        print(payload["stderr"], file=sys.stderr)
    return payload


def _run_mock_restart_check(*, run_dir: Path, broker: str) -> dict:
    """Simulate a fresh subprocess reading the same state directory."""
    env = _env(run_dir)
    env["QEXEC_MOCK_SIM_STATE_DIR"] = str(run_dir / "mock-sim")
    script = (
        "import json,sys;"
        "from quant_execution_engine.account import get_account_snapshot;"
        "from quant_execution_engine.execution import ExecutionStateStore;"
        f"store=ExecutionStateStore();"
        f"state=store.load('{broker}','main');"
        f"snap=get_account_snapshot(env='paper',broker_name='{broker}',account_label='main');"
        "positions={p.symbol:int(p.quantity) for p in snap.positions};"
        f"print(json.dumps({{'state_loaded':True,'broker_orders':len(state.broker_orders),"
        f"'intents':len(state.intents),'positions':positions,"
        f"'state_path':str(store.path_for('{broker}','main'))}}))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(PROJECT_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    print("\n== restart-check ==")
    print(completed.stdout.strip())
    if completed.returncode != 0:
        return {
            "state_loaded": False,
            "error": completed.stderr.strip() or None,
        }
    return json.loads(completed.stdout.strip())


def _render_evidence(
    *,
    args: argparse.Namespace,
    broker: str,
    steps: list[dict],
    run_dir: Path,
    evidence_path: Path,
    targets_path: Path,
    success: bool = True,
    failure_message: str | None = None,
    restart_check: dict | None = None,
) -> None:
    orders_dir = run_dir / "orders"
    audit_logs = sorted(orders_dir.glob("*.jsonl")) if orders_dir.exists() else []
    latest_audit = str(audit_logs[-1]) if audit_logs else None
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "broker": broker,
        "broker_mode": "paper",
        "run_dir": str(run_dir),
        "execute": bool(args.execute),
        "targets_output": str(targets_path),
        "state_path": str(run_dir / "state" / f"{broker}_main.json"),
        "audit_log_path": latest_audit,
        "success": bool(success),
        "failure_message": failure_message,
        "restart_check": restart_check,
        "steps": steps,
    }
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n== evidence ==\nWrote {evidence_path}")


def _readonly_steps(*, broker: str, symbol: str, run_dir: Path) -> list[dict]:
    steps = []
    steps.append(_run_qexec_step("config", "config", "--broker", broker, run_dir=run_dir))
    steps.append(
        _run_qexec_step("preflight", "preflight", symbol, "--broker", broker, run_dir=run_dir)
    )
    steps.append(_run_qexec_step("quote", "quote", symbol, "--broker", broker, run_dir=run_dir))
    steps.append(
        _run_qexec_step(
            "account",
            "account",
            "--broker",
            broker,
            "--format",
            "json",
            run_dir=run_dir,
        )
    )
    return steps


def _rebalance_step(
    name: str, *, targets_path: Path, broker: str, run_dir: Path, execute: bool
) -> dict:
    argv = ["rebalance", str(targets_path), "--broker", broker]
    if execute:
        argv.append("--execute")
    return _run_qexec_step(name, *argv, run_dir=run_dir)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    broker = args.broker
    symbol = args.symbol or DEFAULT_SYMBOLS[broker]
    market = args.market or DEFAULT_MARKETS[broker]

    run_dir = args.run_dir or (
        PROJECT_ROOT / "outputs" / "evidence-offline" / datetime.now().strftime("%Y%m%d-%H%M%S")
    )
    run_dir = run_dir.resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    if broker == "mock-sim":
        os.environ["QEXEC_MOCK_SIM_STATE_DIR"] = str(run_dir / "mock-sim")

    evidence_path = args.evidence_output or (run_dir / "evidence" / f"{broker}-offline-chain.json")
    targets_path = run_dir / "targets.json"
    _write_targets_json(
        targets_path,
        symbol=symbol,
        market=market,
        target_quantity=args.target_quantity if broker == "mock-sim" else 10,
    )

    steps = _readonly_steps(broker=broker, symbol=symbol, run_dir=run_dir)

    if broker == "local-dry-run":
        steps.append(
            _rebalance_step(
                "rebalance-dry-run",
                targets_path=targets_path,
                broker=broker,
                run_dir=run_dir,
                execute=False,
            )
        )
        _render_evidence(
            args=args,
            broker=broker,
            steps=steps,
            run_dir=run_dir,
            evidence_path=evidence_path,
            targets_path=targets_path,
        )
        return 0

    if not args.execute:
        steps.append(
            _rebalance_step(
                "rebalance-dry-run",
                targets_path=targets_path,
                broker=broker,
                run_dir=run_dir,
                execute=False,
            )
        )
    else:
        steps.append(
            _rebalance_step(
                "rebalance-execute",
                targets_path=targets_path,
                broker=broker,
                run_dir=run_dir,
                execute=True,
            )
        )
        steps.append(
            _run_qexec_step(
                "orders",
                "orders",
                "--broker",
                broker,
                "--symbol",
                symbol,
                run_dir=run_dir,
            )
        )

    restart_check = None
    if args.execute and args.restart_check:
        restart_check = _run_mock_restart_check(run_dir=run_dir, broker=broker)

    _render_evidence(
        args=args,
        broker=broker,
        steps=steps,
        run_dir=run_dir,
        evidence_path=evidence_path,
        targets_path=targets_path,
        restart_check=restart_check,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
