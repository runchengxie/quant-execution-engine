#!/usr/bin/env python3
"""Run a fixed execution/operator smoke workflow against a broker backend."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from quant_execution_engine.account import get_account_snapshot
from quant_execution_engine.broker import (
    get_broker_adapter,
    is_paper_broker,
    resolve_broker_name,
)
from quant_execution_engine.cli import (
    run_account,
    run_cancel_all,
    run_config,
    run_exceptions,
    run_order,
    run_orders,
    run_quote,
    run_rebalance,
    run_reconcile,
)
from quant_execution_engine.execution import ExecutionStateStore
from quant_execution_engine.targets import write_targets_json


def canonical_symbol(symbol: str, market: str) -> str:
    base = str(symbol).strip().upper()
    suffix = str(market).strip().upper()
    if not base:
        raise ValueError("symbol must not be empty")
    if not suffix:
        raise ValueError("market must not be empty")
    if base.endswith(f".{suffix}"):
        return base
    if "." in base:
        return base
    return f"{base}.{suffix}"


def build_operator_smoke_targets(
    *,
    symbol: str,
    market: str,
    current_quantity: int,
) -> list[dict[str, object]]:
    base_symbol = str(symbol).strip().upper().split(".", 1)[0]
    target_quantity = max(1, int(current_quantity) + 1)
    return [
        {
            "symbol": base_symbol,
            "market": str(market).strip().upper(),
            "target_quantity": target_quantity,
            "notes": "Deterministic operator smoke target with +1 share delta",
            "metadata": {
                "scenario": "operator-smoke",
                "current_quantity": int(current_quantity),
                "target_quantity": target_quantity,
                "delta_quantity": target_quantity - int(current_quantity),
            },
        }
    ]


def latest_tracked_order_ref(
    *,
    broker_name: str,
    account_label: str,
    symbol_filter: str | None = None,
    state_store: ExecutionStateStore | None = None,
) -> str | None:
    store = state_store or ExecutionStateStore()
    state = store.load(broker_name, account_label)
    allowed = None if not symbol_filter else {str(symbol_filter).strip().upper()}
    records = sorted(
        state.broker_orders,
        key=lambda record: (record.updated_at, record.submitted_at, record.broker_order_id),
        reverse=True,
    )
    for record in records:
        if allowed is not None and not symbol_matches(record.symbol, allowed):
            continue
        return record.broker_order_id
    return None


def symbol_matches(symbol: str, allowed: set[str] | None) -> bool:
    if allowed is None:
        return True
    normalized = str(symbol).strip().upper()
    base = normalized.rsplit(".", 1)[0] if "." in normalized else normalized
    return normalized in allowed or base in allowed


def run_step(name: str, result: object) -> dict[str, object]:
    exit_code = int(getattr(result, "exit_code", 1))
    stdout = getattr(result, "stdout", None)
    stderr = getattr(result, "stderr", None)
    print(f"\n== {name} ==")
    if stdout:
        print(stdout)
    if stderr:
        print(stderr, file=sys.stderr)
    if exit_code != 0:
        raise RuntimeError(f"{name} failed with exit code {exit_code}")
    return {
        "name": name,
        "exit_code": exit_code,
        "stdout": stdout,
        "stderr": stderr,
    }


def write_evidence(
    *,
    args: argparse.Namespace,
    broker: str,
    account_label: str,
    canonical: str,
    steps: list[dict[str, object]],
    output_path: Path,
    latest_order_ref: str | None,
) -> Path | None:
    evidence_output = getattr(args, "evidence_output", None)
    if not evidence_output:
        return None
    evidence_path = Path(evidence_output)
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "broker": broker,
        "account_label": account_label,
        "symbol": canonical,
        "execute": bool(args.execute),
        "preflight_only": bool(args.preflight_only),
        "cleanup_open_orders": bool(args.cleanup_open_orders),
        "allow_non_paper": bool(args.allow_non_paper),
        "targets_output": str(output_path),
        "state_path": str(ExecutionStateStore().path_for(broker, account_label)),
        "latest_tracked_order_ref": latest_order_ref,
        "steps": steps,
    }
    evidence_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n== evidence ==\nWrote {evidence_path}")
    return evidence_path


def run_operator_smoke_workflow(args: argparse.Namespace) -> int:
    broker = resolve_broker_name(args.broker)
    if not is_paper_broker(broker) and not args.allow_non_paper:
        print(
            "Refusing non-paper broker for smoke operator harness. "
            "Pass --allow-non-paper to override.",
            file=sys.stderr,
        )
        return 2

    adapter = get_broker_adapter(broker_name=broker)
    try:
        resolved_account = adapter.resolve_account(args.account)
        account_label = resolved_account.label
    finally:
        close_fn = getattr(adapter, "close", None)
        if callable(close_fn):
            close_fn()

    canonical = canonical_symbol(args.symbol, args.market)
    steps: list[dict[str, object]] = []
    output_path = Path(args.output)
    steps.append(run_step("config", run_config(True, broker=broker)))
    steps.append(run_step("account", run_account(account=account_label, broker=broker)))
    steps.append(run_step("quote", run_quote([canonical], broker=broker)))

    if args.preflight_only:
        print("\n== preflight ==\nPreflight checks passed; skipping targets and broker mutation steps.")
        write_evidence(
            args=args,
            broker=broker,
            account_label=account_label,
            canonical=canonical,
            steps=steps,
            output_path=output_path,
            latest_order_ref=None,
        )
        return 0

    snapshot = get_account_snapshot(
        env="paper" if is_paper_broker(broker) else "real",
        include_quotes=False,
        broker_name=broker,
        account_label=account_label,
    )
    current_quantity = next(
        (
            int(position.quantity)
            for position in snapshot.positions
            if position.symbol.upper() == canonical
        ),
        0,
    )
    targets = build_operator_smoke_targets(
        symbol=args.symbol,
        market=args.market,
        current_quantity=current_quantity,
    )
    write_targets_json(
        output_path,
        asof="smoke-operator",
        source="smoke-operator-harness",
        targets=targets,
        notes=f"operator smoke for {canonical}",
    )
    print(f"\n== targets ==\nWrote {output_path} with target_quantity={targets[0]['target_quantity']}")

    steps.append(
        run_step(
            "rebalance",
            run_rebalance(
                str(output_path),
                account=account_label,
                dry_run=not args.execute,
                broker=broker,
            ),
        )
    )

    if not args.execute:
        write_evidence(
            args=args,
            broker=broker,
            account_label=account_label,
            canonical=canonical,
            steps=steps,
            output_path=output_path,
            latest_order_ref=None,
        )
        return 0

    steps.append(
        run_step(
            "orders",
            run_orders(
                account=account_label,
                broker=broker,
                symbol_filter=args.symbol,
            ),
        )
    )
    order_ref = latest_tracked_order_ref(
        broker_name=broker,
        account_label=account_label,
        symbol_filter=args.symbol,
    )
    if order_ref:
        steps.append(
            run_step(
                "order",
                run_order(
                    order_ref=order_ref,
                    account=account_label,
                    broker=broker,
                ),
            )
        )
    else:
        print("\n== order ==\nNo tracked broker order found after rebalance")

    steps.append(
        run_step(
            "reconcile",
            run_reconcile(
                account=account_label,
                broker=broker,
            ),
        )
    )
    steps.append(
        run_step(
            "exceptions",
            run_exceptions(
                account=account_label,
                broker=broker,
                symbol_filter=args.symbol,
            ),
        )
    )

    if args.cleanup_open_orders:
        steps.append(
            run_step(
                "cancel-all",
                run_cancel_all(
                    account=account_label,
                    broker=broker,
                ),
            )
        )

    write_evidence(
        args=args,
        broker=broker,
        account_label=account_label,
        canonical=canonical,
        steps=steps,
        output_path=output_path,
        latest_order_ref=order_ref,
    )

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run a fixed smoke workflow for config/account/quote/rebalance/operator "
            "commands against a broker backend. Defaults to alpaca-paper."
        )
    )
    parser.add_argument(
        "--broker",
        default="alpaca-paper",
        help="Broker backend to exercise, default: alpaca-paper",
    )
    parser.add_argument(
        "--account",
        default="main",
        help="Account label passed to CLI handlers, default: main",
    )
    parser.add_argument(
        "--symbol",
        default="AAPL",
        help="Base symbol for quote and target generation, default: AAPL",
    )
    parser.add_argument(
        "--market",
        default="US",
        help="Market suffix for quote and target generation, default: US",
    )
    parser.add_argument(
        "--output",
        default="outputs/targets/smoke-operator.json",
        help="Where to write the generated targets JSON",
    )
    execution_mode = parser.add_mutually_exclusive_group()
    execution_mode.add_argument(
        "--execute",
        action="store_true",
        help="Run broker-backed rebalance and operator steps after writing the target file",
    )
    execution_mode.add_argument(
        "--preflight-only",
        action="store_true",
        help="Only run config/account/quote checks without writing targets or submitting orders",
    )
    parser.add_argument(
        "--cleanup-open-orders",
        action="store_true",
        help="Run qexec cancel-all at the end of an executed smoke flow",
    )
    parser.add_argument(
        "--allow-non-paper",
        action="store_true",
        help="Allow running the harness against non-paper brokers",
    )
    parser.add_argument(
        "--evidence-output",
        default=None,
        help="Optional JSON file used to persist a reproducible smoke evidence record",
    )
    args = parser.parse_args()
    try:
        return run_operator_smoke_workflow(args)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
