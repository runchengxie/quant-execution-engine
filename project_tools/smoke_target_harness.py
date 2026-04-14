#!/usr/bin/env python3
"""Generate deterministic target-driven scenarios for paper and dry-run workflows."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from quant_execution_engine.cli import run_rebalance
from quant_execution_engine.targets import write_targets_json


def scenario_targets(scenario: str) -> list[dict[str, object]]:
    if scenario == "carry-over":
        return [
            {
                "symbol": "AAPL",
                "market": "US",
                "target_quantity": 2000,
                "notes": "Large parent order for multi-run carry-over smoke testing",
                "metadata": {"scenario": "carry-over", "slice_hint": "multi-run"},
            }
        ]
    return [
        {
            "symbol": "AAPL",
            "market": "US",
            "target_weight": 0.5,
            "metadata": {"scenario": "rebalance"},
        },
        {
            "symbol": "MSFT",
            "market": "US",
            "target_weight": 0.5,
            "metadata": {"scenario": "rebalance"},
        },
    ]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Write deterministic target-driven smoke scenarios and optionally run qexec rebalance.",
    )
    parser.add_argument(
        "--scenario",
        choices=["rebalance", "carry-over"],
        default="rebalance",
        help="Target scenario to emit, default: rebalance",
    )
    parser.add_argument(
        "--output",
        default="outputs/targets/smoke-targets.json",
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
        "--print-json",
        action="store_true",
        help="Print the generated targets payload to stdout",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Run qexec rebalance --execute after writing the target file",
    )
    args = parser.parse_args()

    output_path = Path(args.output)
    targets = scenario_targets(args.scenario)
    write_targets_json(
        output_path,
        asof=f"smoke-{args.scenario}",
        source="smoke-target-harness",
        targets=targets,
    )
    print(f"Wrote {output_path}")
    if args.print_json:
        payload = json.loads(output_path.read_text(encoding="utf-8"))
        print(json.dumps(payload, ensure_ascii=False, indent=2))

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
