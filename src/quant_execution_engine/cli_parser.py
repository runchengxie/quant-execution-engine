"""Parser builder for qexec CLI."""

from __future__ import annotations

import argparse


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="qexec",
        description="Quant Execution Engine broker execution CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  qexec config --broker longport-paper
  qexec account --broker alpaca-paper --format json
  qexec quote AAPL 700.HK --broker longport-paper
  qexec rebalance outputs/targets/2026-04-09.json --broker longport-paper
  QEXEC_ENABLE_LIVE=1 qexec rebalance outputs/targets/2026-04-09.json --broker longport --execute
        """,
    )
    parser.add_argument("--version", action="version", version="%(prog)s 0.2.0")

    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")

    quote_parser = subparsers.add_parser("quote", help="Fetch real-time quotes")
    quote_parser.add_argument("tickers", nargs="+", help="Tickers such as AAPL or 700.HK")
    quote_parser.add_argument(
        "--broker",
        type=str,
        default=None,
        help="Broker backend override, e.g. longport or alpaca-paper",
    )

    rebalance_parser = subparsers.add_parser(
        "rebalance",
        help="Preview rebalance orders from a schema-v2 targets JSON",
    )
    rebalance_parser.add_argument("input_file", type=str, help="targets JSON file")
    rebalance_parser.add_argument(
        "--broker",
        type=str,
        default=None,
        help="Broker backend override, e.g. longport or alpaca-paper",
    )
    rebalance_parser.add_argument(
        "--account",
        type=str,
        default="main",
        help="Broker account/profile label. Unsupported labels fail fast.",
    )
    rebalance_parser.add_argument(
        "--execute",
        action="store_true",
        help="Run the live-mode path. Real brokers additionally require QEXEC_ENABLE_LIVE=1.",
    )
    rebalance_parser.add_argument(
        "--target-gross-exposure",
        type=float,
        default=1.0,
        help="Override target gross exposure when the input file leaves it at 1.0",
    )

    account_parser = subparsers.add_parser("account", help="Show account overview")
    account_parser.add_argument("--funds", action="store_true", help="Only show cash/funds")
    account_parser.add_argument("--positions", action="store_true", help="Only show positions")
    account_parser.add_argument(
        "--broker",
        type=str,
        default=None,
        help="Broker backend override, e.g. longport or alpaca-paper",
    )
    account_parser.add_argument(
        "--account",
        type=str,
        default="main",
        help="Broker account/profile label. Unsupported labels fail fast.",
    )
    account_parser.add_argument(
        "--format",
        choices=["table", "json"],
        default="table",
        help="Output format",
    )

    config_parser = subparsers.add_parser("config", help="Show effective broker config")
    config_parser.add_argument("--show", action="store_true", default=True)
    config_parser.add_argument(
        "--broker",
        type=str,
        default=None,
        help="Broker backend override, e.g. longport or alpaca-paper",
    )

    evidence_maturity_parser = subparsers.add_parser(
        "evidence-maturity",
        help="Show broker execution evidence maturity and remaining smoke gaps",
    )
    evidence_maturity_parser.add_argument(
        "--format",
        choices=["table", "json"],
        default="table",
        help="Output format",
    )

    evidence_pack_parser = subparsers.add_parser(
        "evidence-pack",
        help="Collect audit, state, target, smoke evidence, and notes for one run id",
    )
    evidence_pack_parser.add_argument(
        "run_id",
        type=str,
        help="Audit run id from outputs/orders/*.jsonl",
    )
    evidence_pack_parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Optional bundle output directory, default: outputs/evidence-bundles/<run-id>",
    )
    evidence_pack_parser.add_argument(
        "--operator-note",
        action="append",
        default=None,
        help="Operator note to include in the evidence bundle; may be passed more than once",
    )

    orders_parser = subparsers.add_parser(
        "orders",
        help="Show tracked broker orders from local execution state",
    )
    orders_parser.add_argument(
        "--broker",
        type=str,
        default=None,
        help="Broker backend override, e.g. longport or alpaca-paper",
    )
    orders_parser.add_argument(
        "--account",
        type=str,
        default="main",
        help="Broker account/profile label. Unsupported labels fail fast.",
    )
    orders_parser.add_argument(
        "--status",
        type=str,
        default=None,
        help="Optional broker-order status filter, e.g. open, failure, terminal, or exact status",
    )
    orders_parser.add_argument(
        "--symbol",
        type=str,
        default=None,
        help="Optional symbol filter, e.g. AAPL or AAPL.US",
    )

    exceptions_parser = subparsers.add_parser(
        "exceptions",
        help="Show tracked execution exceptions from local execution state",
    )
    exceptions_parser.add_argument(
        "--broker",
        type=str,
        default=None,
        help="Broker backend override, e.g. longport or alpaca-paper",
    )
    exceptions_parser.add_argument(
        "--account",
        type=str,
        default="main",
        help="Broker account/profile label. Unsupported labels fail fast.",
    )
    exceptions_parser.add_argument(
        "--status",
        type=str,
        default=None,
        help="Optional exception status filter, e.g. failure, open, blocked, partially_filled",
    )
    exceptions_parser.add_argument(
        "--symbol",
        type=str,
        default=None,
        help="Optional symbol filter, e.g. AAPL or AAPL.US",
    )

    reconcile_parser = subparsers.add_parser(
        "reconcile",
        help="Run a manual broker reconcile pass and persist refreshed state",
    )
    reconcile_parser.add_argument(
        "--broker",
        type=str,
        default=None,
        help="Broker backend override, e.g. longport or alpaca-paper",
    )
    reconcile_parser.add_argument(
        "--account",
        type=str,
        default="main",
        help="Broker account/profile label. Unsupported labels fail fast.",
    )

    cancel_parser = subparsers.add_parser(
        "cancel",
        help="Cancel a tracked order by broker_order_id, client_order_id, or child_order_id",
    )
    cancel_parser.add_argument(
        "order_ref",
        type=str,
        help="Tracked order reference: broker_order_id, client_order_id, or child_order_id",
    )
    cancel_parser.add_argument(
        "--broker",
        type=str,
        default=None,
        help="Broker backend override, e.g. longport or alpaca-paper",
    )
    cancel_parser.add_argument(
        "--account",
        type=str,
        default="main",
        help="Broker account/profile label. Unsupported labels fail fast.",
    )

    cancel_all_parser = subparsers.add_parser(
        "cancel-all",
        help="Cancel all tracked open broker orders from local execution state",
    )
    cancel_all_parser.add_argument(
        "--broker",
        type=str,
        default=None,
        help="Broker backend override, e.g. longport or alpaca-paper",
    )
    cancel_all_parser.add_argument(
        "--account",
        type=str,
        default="main",
        help="Broker account/profile label. Unsupported labels fail fast.",
    )

    order_parser = subparsers.add_parser(
        "order",
        help="Show tracked order detail by broker_order_id, client_order_id, or child_order_id",
    )
    order_parser.add_argument(
        "order_ref",
        type=str,
        help="Tracked order reference: broker_order_id, client_order_id, or child_order_id",
    )
    order_parser.add_argument(
        "--broker",
        type=str,
        default=None,
        help="Broker backend override, e.g. longport or alpaca-paper",
    )
    order_parser.add_argument(
        "--account",
        type=str,
        default="main",
        help="Broker account/profile label. Unsupported labels fail fast.",
    )

    retry_parser = subparsers.add_parser(
        "retry",
        help="Retry a zero-fill failed or canceled tracked order",
    )
    retry_parser.add_argument(
        "order_ref",
        type=str,
        help="Tracked order reference: broker_order_id, client_order_id, or child_order_id",
    )
    retry_parser.add_argument(
        "--broker",
        type=str,
        default=None,
        help="Broker backend override, e.g. longport or alpaca-paper",
    )
    retry_parser.add_argument(
        "--account",
        type=str,
        default="main",
        help="Broker account/profile label. Unsupported labels fail fast.",
    )

    reprice_parser = subparsers.add_parser(
        "reprice",
        help="Cancel and resubmit a tracked open LIMIT order at a new limit price",
    )
    reprice_parser.add_argument(
        "order_ref",
        type=str,
        help="Tracked order reference: broker_order_id, client_order_id, or child_order_id",
    )
    reprice_parser.add_argument(
        "--limit-price",
        type=float,
        required=True,
        help="Replacement limit price for the new child order attempt",
    )
    reprice_parser.add_argument(
        "--broker",
        type=str,
        default=None,
        help="Broker backend override, e.g. longport or alpaca-paper",
    )
    reprice_parser.add_argument(
        "--account",
        type=str,
        default="main",
        help="Broker account/profile label. Unsupported labels fail fast.",
    )

    retry_stale_parser = subparsers.add_parser(
        "retry-stale",
        help="Cancel and retry zero-fill tracked open orders older than a threshold",
    )
    retry_stale_parser.add_argument(
        "--older-than-minutes",
        type=int,
        default=5,
        help="Only target locally tracked open orders older than this many minutes",
    )
    retry_stale_parser.add_argument(
        "--broker",
        type=str,
        default=None,
        help="Broker backend override, e.g. longport or alpaca-paper",
    )
    retry_stale_parser.add_argument(
        "--account",
        type=str,
        default="main",
        help="Broker account/profile label. Unsupported labels fail fast.",
    )

    preflight_parser = subparsers.add_parser(
        "preflight",
        help="Run non-mutating broker/account readiness checks",
    )
    preflight_parser.add_argument(
        "symbols",
        nargs="*",
        help="Optional symbols used for quote/depth reachability checks, default: AAPL",
    )
    preflight_parser.add_argument(
        "--broker",
        type=str,
        default=None,
        help="Broker backend override, e.g. longport or alpaca-paper",
    )
    preflight_parser.add_argument(
        "--account",
        type=str,
        default="main",
        help="Broker account/profile label. Unsupported labels fail fast.",
    )

    cancel_rest_parser = subparsers.add_parser(
        "cancel-rest",
        help="Cancel the open remainder of a partially filled tracked order",
    )
    cancel_rest_parser.add_argument(
        "order_ref",
        type=str,
        help="Tracked order reference: broker_order_id, client_order_id, or child_order_id",
    )
    cancel_rest_parser.add_argument(
        "--broker",
        type=str,
        default=None,
        help="Broker backend override, e.g. longport or alpaca-paper",
    )
    cancel_rest_parser.add_argument(
        "--account",
        type=str,
        default="main",
        help="Broker account/profile label. Unsupported labels fail fast.",
    )

    resume_remaining_parser = subparsers.add_parser(
        "resume-remaining",
        help="Submit a new child attempt for the remaining quantity after a partial fill",
    )
    resume_remaining_parser.add_argument(
        "order_ref",
        type=str,
        help="Tracked order reference: broker_order_id, client_order_id, or child_order_id",
    )
    resume_remaining_parser.add_argument(
        "--broker",
        type=str,
        default=None,
        help="Broker backend override, e.g. longport or alpaca-paper",
    )
    resume_remaining_parser.add_argument(
        "--account",
        type=str,
        default="main",
        help="Broker account/profile label. Unsupported labels fail fast.",
    )

    accept_partial_parser = subparsers.add_parser(
        "accept-partial",
        help="Accept a partial fill locally and stop expecting the remaining quantity",
    )
    accept_partial_parser.add_argument(
        "order_ref",
        type=str,
        help="Tracked order reference: broker_order_id, client_order_id, or child_order_id",
    )
    accept_partial_parser.add_argument(
        "--broker",
        type=str,
        default=None,
        help="Broker backend override, e.g. longport or alpaca-paper",
    )
    accept_partial_parser.add_argument(
        "--account",
        type=str,
        default="main",
        help="Broker account/profile label. Unsupported labels fail fast.",
    )

    state_doctor_parser = subparsers.add_parser(
        "state-doctor",
        help="Inspect the local execution state file for consistency issues",
    )
    state_doctor_parser.add_argument(
        "--broker",
        type=str,
        default=None,
        help="Broker backend override, e.g. longport or alpaca-paper",
    )
    state_doctor_parser.add_argument(
        "--account",
        type=str,
        default="main",
        help="Broker account/profile label. Unsupported labels fail fast.",
    )

    state_prune_parser = subparsers.add_parser(
        "state-prune",
        help="Preview or prune old terminal records from the local execution state",
    )
    state_prune_parser.add_argument(
        "--older-than-days",
        type=int,
        default=30,
        help="Only target terminal parent orders older than this many days",
    )
    state_prune_parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually write the pruned state back to disk; default is preview only",
    )
    state_prune_parser.add_argument(
        "--broker",
        type=str,
        default=None,
        help="Broker backend override, e.g. longport or alpaca-paper",
    )
    state_prune_parser.add_argument(
        "--account",
        type=str,
        default="main",
        help="Broker account/profile label. Unsupported labels fail fast.",
    )

    state_repair_parser = subparsers.add_parser(
        "state-repair",
        help="Apply safe local execution state repairs",
    )
    state_repair_parser.add_argument(
        "--clear-kill-switch",
        action="store_true",
        help="Clear the local kill switch and reset consecutive failure count",
    )
    state_repair_parser.add_argument(
        "--dedupe-fills",
        action="store_true",
        help="Remove duplicate fill ids from the local execution state",
    )
    state_repair_parser.add_argument(
        "--drop-orphan-fills",
        action="store_true",
        help="Remove fill events that no longer map to any tracked order",
    )
    state_repair_parser.add_argument(
        "--drop-orphan-terminal-broker-orders",
        action="store_true",
        help="Remove terminal broker orders that are not referenced by any child order",
    )
    state_repair_parser.add_argument(
        "--recompute-parent-aggregates",
        action="store_true",
        help="Recompute parent filled/remaining quantities and status from local child, broker, and fill state",
    )
    state_repair_parser.add_argument(
        "--broker",
        type=str,
        default=None,
        help="Broker backend override, e.g. longport or alpaca-paper",
    )
    state_repair_parser.add_argument(
        "--account",
        type=str,
        default="main",
        help="Broker account/profile label. Unsupported labels fail fast.",
    )

    return parser


