"""Parser builder for qexec CLI."""

from __future__ import annotations

import argparse


_BROKER_HELP = "Broker backend override, e.g. longport or alpaca-paper"
_ACCOUNT_HELP = "Broker account/profile label. Unsupported labels fail fast."
_ORDER_REF_HELP = (
    "Tracked order reference: broker_order_id, client_order_id, or child_order_id"
)


def _add_broker_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--broker",
        type=str,
        default=None,
        help=_BROKER_HELP,
    )


def _add_account_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--account",
        type=str,
        default="main",
        help=_ACCOUNT_HELP,
    )


def _add_broker_account_args(parser: argparse.ArgumentParser) -> None:
    _add_broker_arg(parser)
    _add_account_arg(parser)


def _add_format_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--format",
        choices=["table", "json"],
        default="table",
        help="Output format",
    )


def _add_order_ref_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "order_ref",
        type=str,
        help=_ORDER_REF_HELP,
    )


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
    _add_broker_arg(quote_parser)

    rebalance_parser = subparsers.add_parser(
        "rebalance",
        help="Preview rebalance orders from a canonical targets JSON",
    )
    rebalance_parser.add_argument("input_file", type=str, help="targets JSON file")
    _add_broker_account_args(rebalance_parser)
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
    _add_broker_account_args(account_parser)
    _add_format_arg(account_parser)

    config_parser = subparsers.add_parser("config", help="Show effective broker config")
    config_parser.add_argument("--show", action="store_true", default=True)
    _add_broker_arg(config_parser)

    evidence_maturity_parser = subparsers.add_parser(
        "evidence-maturity",
        help="Show broker execution evidence maturity and remaining smoke gaps",
    )
    _add_format_arg(evidence_maturity_parser)

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
    _add_broker_account_args(orders_parser)
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

    broker_orders_parser = subparsers.add_parser(
        "broker-orders",
        help="Show broker-side read-only order history where supported",
    )
    _add_broker_account_args(broker_orders_parser)
    broker_orders_parser.add_argument(
        "--status",
        type=str,
        default=None,
        help="Optional broker-order status filter, e.g. open, failure, terminal, or exact status",
    )
    broker_orders_parser.add_argument(
        "--symbol",
        type=str,
        default=None,
        help="Optional symbol filter, e.g. AAPL or AAPL.US",
    )
    broker_orders_parser.add_argument(
        "--order-id",
        type=str,
        default=None,
        help="Optional broker-native order id filter",
    )
    _add_format_arg(broker_orders_parser)

    broker_fills_parser = subparsers.add_parser(
        "broker-fills",
        help="Show broker-side read-only fill history where supported",
    )
    _add_broker_account_args(broker_fills_parser)
    broker_fills_parser.add_argument(
        "--symbol",
        type=str,
        default=None,
        help="Optional symbol filter, e.g. AAPL or AAPL.US",
    )
    broker_fills_parser.add_argument(
        "--order-id",
        type=str,
        default=None,
        help="Optional broker-native order id filter",
    )
    _add_format_arg(broker_fills_parser)

    exceptions_parser = subparsers.add_parser(
        "exceptions",
        help="Show tracked execution exceptions from local execution state",
    )
    _add_broker_account_args(exceptions_parser)
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
    _add_broker_account_args(reconcile_parser)

    cancel_parser = subparsers.add_parser(
        "cancel",
        help="Cancel a tracked order by broker_order_id, client_order_id, or child_order_id",
    )
    _add_order_ref_arg(cancel_parser)
    _add_broker_account_args(cancel_parser)

    cancel_all_parser = subparsers.add_parser(
        "cancel-all",
        help="Cancel all tracked open broker orders from local execution state",
    )
    _add_broker_account_args(cancel_all_parser)

    order_parser = subparsers.add_parser(
        "order",
        help="Show tracked order detail by broker_order_id, client_order_id, or child_order_id",
    )
    _add_order_ref_arg(order_parser)
    _add_broker_account_args(order_parser)

    retry_parser = subparsers.add_parser(
        "retry",
        help="Retry a zero-fill failed or canceled tracked order",
    )
    _add_order_ref_arg(retry_parser)
    _add_broker_account_args(retry_parser)

    reprice_parser = subparsers.add_parser(
        "reprice",
        help="Cancel and resubmit a tracked open LIMIT order at a new limit price",
    )
    _add_order_ref_arg(reprice_parser)
    reprice_parser.add_argument(
        "--limit-price",
        type=float,
        required=True,
        help="Replacement limit price for the new child order attempt",
    )
    _add_broker_account_args(reprice_parser)

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
    _add_broker_account_args(retry_stale_parser)

    preflight_parser = subparsers.add_parser(
        "preflight",
        help="Run non-mutating broker/account readiness checks",
    )
    preflight_parser.add_argument(
        "symbols",
        nargs="*",
        help="Optional symbols used for quote/depth reachability checks, default: AAPL",
    )
    _add_broker_account_args(preflight_parser)

    cancel_rest_parser = subparsers.add_parser(
        "cancel-rest",
        help="Cancel the open remainder of a partially filled tracked order",
    )
    _add_order_ref_arg(cancel_rest_parser)
    _add_broker_account_args(cancel_rest_parser)

    resume_remaining_parser = subparsers.add_parser(
        "resume-remaining",
        help="Submit a new child attempt for the remaining quantity after a partial fill",
    )
    _add_order_ref_arg(resume_remaining_parser)
    _add_broker_account_args(resume_remaining_parser)

    accept_partial_parser = subparsers.add_parser(
        "accept-partial",
        help="Accept a partial fill locally and stop expecting the remaining quantity",
    )
    _add_order_ref_arg(accept_partial_parser)
    _add_broker_account_args(accept_partial_parser)

    state_doctor_parser = subparsers.add_parser(
        "state-doctor",
        help="Inspect the local execution state file for consistency issues",
    )
    _add_broker_account_args(state_doctor_parser)

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
    _add_broker_account_args(state_prune_parser)

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
        help=(
            "Recompute parent filled/remaining quantities and status from "
            "local child, broker, and fill state"
        ),
    )
    _add_broker_account_args(state_repair_parser)

    return parser
