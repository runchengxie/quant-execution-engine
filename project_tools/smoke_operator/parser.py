"""Argument parsing and entrypoint for the operator smoke harness."""

from __future__ import annotations

import argparse
import sys

from project_tools.smoke_operator.workflow import (
    run_operator_smoke_workflow,
)


def build_parser() -> argparse.ArgumentParser:
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
    parser.add_argument(
        "--operator-note",
        action="append",
        dest="operator_notes",
        default=[],
        help="Optional manual note preserved in evidence JSON; repeat as needed",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return run_operator_smoke_workflow(args)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
