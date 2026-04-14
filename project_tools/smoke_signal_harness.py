#!/usr/bin/env python3
"""Generate a deterministic signal-driven smoke target and optionally run qexec."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from quant_execution_engine.cli import run_rebalance
from quant_execution_engine.targets import write_targets_json


def build_signal_target(symbol: str, market: str) -> list[dict[str, object]]:
    closes = [100.0, 101.5, 102.0, 103.5, 105.0]
    fast = sum(closes[-3:]) / 3.0
    slow = sum(closes) / len(closes)
    target_weight = 1.0 if fast >= slow else 0.0
    return [
        {
            "symbol": symbol,
            "market": market,
            "target_weight": target_weight,
            "notes": "Deterministic EMA-style smoke signal",
            "metadata": {
                "fast_ma": round(fast, 4),
                "slow_ma": round(slow, 4),
                "signal": "long" if target_weight > 0 else "flat",
            },
        }
    ]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Write a deterministic signal-driven targets.json and optionally run qexec rebalance.",
    )
    parser.add_argument("--symbol", default="AAPL", help="Base symbol, default: AAPL")
    parser.add_argument("--market", default="US", help="Market suffix, default: US")
    parser.add_argument(
        "--output",
        default="outputs/targets/smoke-signal.json",
        help="Where to write the generated targets JSON",
    )
    parser.add_argument(
        "--broker",
        default="alpaca-paper",
        help="Broker backend for optional execution, default: alpaca-paper",
    )
    parser.add_argument(
        "--account",
        default="main",
        help="Account label passed to qexec rebalance, default: main",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Run qexec rebalance --execute after writing the target file",
    )
    args = parser.parse_args()

    output_path = Path(args.output)
    targets = build_signal_target(args.symbol, args.market)
    write_targets_json(
        output_path,
        asof="smoke-signal",
        source="smoke-signal-harness",
        targets=targets,
    )
    print(f"Wrote {output_path}")

    if not args.execute:
        return 0

    result = run_rebalance(
        str(output_path),
        account=args.account,
        dry_run=False,
        broker=args.broker,
    )
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
