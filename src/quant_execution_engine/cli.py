"""CLI entrypoint for the execution engine."""

from __future__ import annotations

import argparse
import importlib.util
import os
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .account import get_account_snapshot, get_quotes
from .broker import (
    get_broker_adapter,
    get_broker_capabilities,
    is_ibkr_broker,
    is_longport_broker,
    is_paper_broker,
    peek_broker_name,
    probe_ibkr_runtime_config,
    resolve_broker_name,
    resolve_default_account_label,
)
from .broker.longport_credentials import (
    probe_longport_credentials,
    resolve_longport_runtime_value,
)
from .evidence_bundle import (
    EvidenceBundleError,
    create_evidence_bundle,
    render_evidence_bundle_result,
)
from .evidence_maturity import (
    build_broker_evidence_maturity_report,
    render_broker_evidence_maturity,
)
from .execution import ExecutionStateStore, OrderLifecycleService
from .execution import (
    DEFAULT_EXCEPTION_STATUSES,
    FAILURE_BROKER_STATUSES,
    OPEN_BROKER_STATUSES,
    SUCCESS_BROKER_STATUSES,
    TERMINAL_BROKER_STATUSES,
)
from .guards import validate_live_execution_guard
from .logging import get_logger, set_run_id
from .preflight import run_preflight_checks
from .rebalance import RebalanceService
from .risk import get_kill_switch_config, get_risk_config
from .renderers.diff import render_rebalance_diff
from .renderers.jsonout import render_json, render_multiple_account_snapshots_json
from .renderers.table import (
    render_accept_partial_summary,
    render_bulk_cancel_summary,
    render_broker_orders,
    render_cancel_summary,
    render_exception_orders,
    render_multiple_account_snapshots,
    render_preflight_summary,
    render_quotes,
    render_reconcile_summary,
    render_reprice_summary,
    render_resume_remaining_summary,
    render_retry_summary,
    render_state_doctor_summary,
    render_state_prune_summary,
    render_state_repair_summary,
    render_stale_retry_summary,
    render_tracked_order_detail,
)
from .state_tools import StateMaintenanceService
from .targets import read_targets_json

if TYPE_CHECKING:
    from rich.console import Console


@dataclass(slots=True)
class CommandResult:
    """Normalized response returned by CLI handlers."""

    exit_code: int
    stdout: str | None = None
    stderr: str | None = None
    rich_renderable: object | None = None


_RICH_AVAILABLE = importlib.util.find_spec("rich") is not None
_RICH_CONSOLE: Console | None = None

if _RICH_AVAILABLE:
    from rich.console import Console
    from rich.traceback import install as install_rich_traceback

    _RICH_CONSOLE = Console()
    install_rich_traceback(show_locals=False)


_BROKER_STATUS_GROUPS: dict[str, set[str]] = {
    "OPEN": set(OPEN_BROKER_STATUSES),
    "TERMINAL": set(TERMINAL_BROKER_STATUSES),
    "FAILURE": set(FAILURE_BROKER_STATUSES),
    "SUCCESS": set(SUCCESS_BROKER_STATUSES),
    "EXCEPTION": {"PARTIALLY_FILLED", "PENDING_CANCEL", "WAIT_TO_CANCEL", "REJECTED", "EXPIRED", "FAILED"},
}
_EXCEPTION_STATUS_GROUPS: dict[str, set[str]] = {
    "DEFAULT": set(DEFAULT_EXCEPTION_STATUSES),
    "ALL": set(DEFAULT_EXCEPTION_STATUSES),
    "OPEN": {"PARTIALLY_FILLED", "PENDING_CANCEL", "WAIT_TO_CANCEL"},
    "FAILURE": {"BLOCKED", "FAILED", "REJECTED", "EXPIRED"},
}


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


def _handle_command_result(result: int | CommandResult) -> int:
    if isinstance(result, CommandResult):
        if _RICH_CONSOLE is not None and result.rich_renderable is not None:
            _RICH_CONSOLE.print(result.rich_renderable)
            if result.stdout:
                _RICH_CONSOLE.print()
        if result.stdout:
            if _RICH_CONSOLE is not None:
                _RICH_CONSOLE.print(result.stdout, highlight=False)
            else:
                print(result.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        return result.exit_code
    return int(result)


def run_quote(tickers: list[str], broker: str | None = None) -> CommandResult:
    try:
        quotes_dict = get_quotes(tickers, broker_name=broker)
        return CommandResult(exit_code=0, stdout=render_quotes(list(quotes_dict.values())))
    except Exception as exc:
        requested_broker = peek_broker_name(broker) or "(unconfigured)"
        get_logger(__name__).error(
            "Failed to fetch quotes via broker %s: %s",
            requested_broker,
            exc,
        )
        return CommandResult(exit_code=1, stderr=str(exc))


def run_preflight(
    *,
    symbols: list[str] | None = None,
    account: str = "main",
    broker: str | None = None,
) -> CommandResult:
    try:
        result = run_preflight_checks(
            broker_name=broker,
            account_label=account,
            symbols=symbols or ["AAPL"],
        )
        return CommandResult(
            exit_code=1 if result.has_failures else 0,
            stdout=render_preflight_summary(result),
        )
    except Exception as exc:
        msg = f"Preflight failed: {exc}"
        get_logger(__name__).error(msg)
        return CommandResult(exit_code=1, stderr=msg)


def run_account(
    only_funds: bool = False,
    only_positions: bool = False,
    fmt: str = "table",
    account: str = "main",
    broker: str | None = None,
) -> CommandResult:
    try:
        if only_funds and only_positions:
            only_positions = False
        selected_broker = resolve_broker_name(broker)
        snapshot = get_account_snapshot(
            env="paper" if is_paper_broker(selected_broker) else "real",
            broker_name=selected_broker,
            account_label=account,
        )
        snapshots = [snapshot]
        if fmt == "json":
            output = render_multiple_account_snapshots_json(snapshots)
        else:
            output = render_multiple_account_snapshots(
                snapshots,
                only_funds=only_funds,
                only_positions=only_positions,
            )
        return CommandResult(exit_code=0, stdout=output)
    except Exception as exc:
        msg = f"Failed to get account overview: {exc}"
        get_logger(__name__).error(msg)
        return CommandResult(exit_code=1, stderr=msg)


def run_config(show: bool = True, broker: str | None = None) -> CommandResult:
    if not show:
        return CommandResult(exit_code=0)

    def _getenv_both(name_new: str, name_old: str, default: str = "") -> str:
        return os.getenv(name_new) or os.getenv(name_old) or default

    def _to_bool(value: str | None, default: bool = False) -> bool:
        if value is None:
            return default
        return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}

    def _to_float(value: str | None, default: float = 0.0) -> float:
        try:
            return float(str(value)) if value is not None else default
        except Exception:
            return default

    def _to_int(value: str | None, default: int = 0) -> int:
        try:
            return int(float(str(value))) if value is not None else default
        except Exception:
            return default

    def _fmt_unlimited(value: float | int) -> str:
        try:
            if float(value) <= 0:
                return "Unlimited (0)"
        except Exception:
            return str(value)
        return f"{value}"
    try:
        selected_broker = resolve_broker_name(broker)
        capabilities = get_broker_capabilities(selected_broker)
        risk_cfg = get_risk_config()
        kill_switch_cfg = get_kill_switch_config()
        default_account = resolve_default_account_label()

        alpaca_key = os.getenv("ALPACA_API_KEY") or os.getenv("APCA_API_KEY_ID")
        alpaca_secret = os.getenv("ALPACA_SECRET_KEY") or os.getenv("APCA_API_SECRET_KEY")

        def _mask(value: str | None) -> str:
            if not value:
                return "(not set)"
            if len(value) <= 6:
                return "***"
            return value[:3] + "***" + value[-3:]

        lines = [
            "Execution Engine Effective Configuration:",
            "- Broker:                " + selected_broker,
            "- Default Account:       " + default_account,
            "- Account Selection:     "
            + ("supported" if capabilities.supports_account_selection else "single-account only"),
            "- Live Submit:           "
            + (
                "paper-only"
                if is_paper_broker(selected_broker)
                else "supported"
                if capabilities.supports_live_submit
                else "unsupported"
            ),
            "- Cancel / Query:        "
            + (
                "enabled"
                if capabilities.supports_cancel and capabilities.supports_order_query
                else "partial"
            ),
            "- Supported Order Types: " + ", ".join(capabilities.supported_order_types),
            "- Supported TIF:         " + ", ".join(capabilities.supported_time_in_force),
            "- Risk Max Notional:     "
            + _fmt_unlimited(float(risk_cfg.get("max_notional_per_order", 0.0) or 0.0)),
            "- Risk Max Quantity:     "
            + _fmt_unlimited(int(float(risk_cfg.get("max_qty_per_order", 0) or 0))),
            "- Risk Max Spread (bps): " + str(risk_cfg.get("max_spread_bps", 0) or 0),
            "- Risk Participation:    "
            + str(risk_cfg.get("max_participation_rate", 0) or 0),
            "- Kill Switch Env:       "
            + str(kill_switch_cfg.get("env_var") or "QEXEC_KILL_SWITCH"),
            "- Submit Mode:           "
            + str(
                capabilities.notes.get("submit_mode")
                or ("paper" if is_paper_broker(selected_broker) else "real")
            ),
        ]
        if is_longport_broker(selected_broker):
            longport_env_name = "paper" if selected_broker == "longport-paper" else "real"
            region, region_source = resolve_longport_runtime_value(
                ("LONGPORT_REGION", "LONGBRIDGE_REGION"),
                env_name=longport_env_name,
                default="hk",
            )
            overnight, overnight_source = resolve_longport_runtime_value(
                ("LONGPORT_ENABLE_OVERNIGHT", "LONGBRIDGE_ENABLE_OVERNIGHT"),
                env_name=longport_env_name,
                default="false",
            )
            max_notional = _getenv_both(
                "LONGPORT_MAX_NOTIONAL_PER_ORDER",
                "LONGBRIDGE_MAX_NOTIONAL_PER_ORDER",
                "0",
            )
            max_qty = _getenv_both(
                "LONGPORT_MAX_QTY_PER_ORDER", "LONGBRIDGE_MAX_QTY_PER_ORDER", "0"
            )
            tw_start = _getenv_both(
                "LONGPORT_TRADING_WINDOW_START", "LONGBRIDGE_TRADING_WINDOW_START", "09:30"
            )
            tw_end = _getenv_both(
                "LONGPORT_TRADING_WINDOW_END", "LONGBRIDGE_TRADING_WINDOW_END", "16:00"
            )
            credentials = probe_longport_credentials(longport_env_name)
            app_key = credentials.app_key
            app_secret = credentials.app_secret
            token = credentials.access_token
            app_key_source = credentials.app_key_source or "(not found)"
            app_secret_source = credentials.app_secret_source or "(not found)"
            token_source = credentials.access_token_source or "(not found)"
            resolved_region_source = region_source or "(default)"
            resolved_overnight_source = overnight_source or "(default)"
            lines.extend(
                [
                    "- Region:                " + region,
                    "- Region Source:         " + resolved_region_source,
                    "- Overnight:             "
                    + ("enabled" if _to_bool(overnight) else "disabled"),
                    "- Overnight Source:      " + resolved_overnight_source,
                    "- Local Max Notional:    " + _fmt_unlimited(_to_float(max_notional, 0.0)),
                    "- Local Max Quantity:    " + _fmt_unlimited(_to_int(max_qty, 0)),
                    "- Trade Window:          " + f"{tw_start} - {tw_end}",
                    "- App Key:               " + _mask(app_key),
                    "- App Key Source:        " + app_key_source,
                    "- App Secret:            " + _mask(app_secret),
                    "- App Secret Source:     " + app_secret_source,
                    "- Access Token:          " + _mask(token),
                    "- Access Token Source:   " + token_source,
                ]
            )
        elif is_ibkr_broker(selected_broker):
            runtime_cfg = probe_ibkr_runtime_config()
            lines.extend(
                [
                    "- Runtime Stack:         " + runtime_cfg.runtime,
                    "- Gateway Host:          " + runtime_cfg.host,
                    "- Gateway Host Source:   " + runtime_cfg.host_source,
                    "- Paper Port:            " + str(runtime_cfg.port),
                    "- Paper Port Source:     " + runtime_cfg.port_source,
                    "- Client ID:             " + str(runtime_cfg.client_id),
                    "- Client ID Source:      " + runtime_cfg.client_id_source,
                    "- Account ID:            "
                    + (runtime_cfg.account_id or "(auto-detect via IB Gateway)"),
                    "- Account ID Source:     " + runtime_cfg.account_id_source,
                    "- Connect Timeout (s):   " + str(runtime_cfg.connect_timeout_seconds),
                    "- Timeout Source:        " + runtime_cfg.connect_timeout_source,
                    "- Market Scope:          US equities only",
                ]
            )
        elif selected_broker in {"alpaca", "alpaca-paper"}:
            lines.extend(
                [
                    "- Alpaca API Key:        " + _mask(alpaca_key),
                    "- Alpaca Secret:         " + _mask(alpaca_secret),
                ]
            )
        return CommandResult(exit_code=0, stdout="\n".join(lines))
    except Exception as exc:
        return CommandResult(exit_code=1, stderr=str(exc))


def run_evidence_maturity(fmt: str = "table") -> CommandResult:
    try:
        records = build_broker_evidence_maturity_report()
        if fmt == "json":
            return CommandResult(
                exit_code=0,
                stdout=render_json([record.to_payload() for record in records]),
            )
        return CommandResult(exit_code=0, stdout=render_broker_evidence_maturity(records))
    except Exception as exc:
        msg = f"Evidence maturity report failed: {exc}"
        get_logger(__name__).error(msg)
        return CommandResult(exit_code=1, stderr=msg)


def run_evidence_pack(
    *,
    run_id: str,
    output_dir: str | None = None,
    operator_notes: list[str] | None = None,
) -> CommandResult:
    try:
        result = create_evidence_bundle(
            run_id=run_id,
            output_dir=Path(output_dir) if output_dir else None,
            operator_notes=operator_notes,
        )
        exit_code = 1 if result.missing_count else 0
        return CommandResult(exit_code=exit_code, stdout=render_evidence_bundle_result(result))
    except EvidenceBundleError as exc:
        return CommandResult(exit_code=1, stderr=str(exc))
    except Exception as exc:
        msg = f"Evidence pack failed: {exc}"
        get_logger(__name__).error(msg)
        return CommandResult(exit_code=1, stderr=msg)


def run_orders(
    *,
    account: str = "main",
    broker: str | None = None,
    status_filter: str | None = None,
    symbol_filter: str | None = None,
) -> CommandResult:
    adapter = None
    try:
        adapter = get_broker_adapter(broker_name=broker)
        resolved = adapter.resolve_account(account)
        state = ExecutionStateStore().load(adapter.backend_name, resolved.label)
        records = sorted(
            state.broker_orders,
            key=lambda record: (record.updated_at, record.submitted_at, record.broker_order_id),
            reverse=True,
        )
        allowed_statuses = _resolve_broker_status_filter(status_filter)
        allowed_symbols = _resolve_symbol_filter(symbol_filter)
        if allowed_statuses is not None:
            records = [record for record in records if record.status in allowed_statuses]
        if allowed_symbols is not None:
            records = [record for record in records if _symbol_matches_filter(record.symbol, allowed_symbols)]
        if not records and (allowed_statuses is not None or allowed_symbols is not None):
            return CommandResult(
                exit_code=0,
                stdout=f"No tracked broker orders matching filters: {_format_filter_summary(status_filter=status_filter, symbol_filter=symbol_filter)}",
            )
        return CommandResult(exit_code=0, stdout=render_broker_orders(records))
    except Exception as exc:
        msg = f"Failed to load tracked orders: {exc}"
        get_logger(__name__).error(msg)
        return CommandResult(exit_code=1, stderr=msg)
    finally:
        close_fn = getattr(adapter, "close", None)
        if callable(close_fn):
            close_fn()


def run_exceptions(
    *,
    account: str = "main",
    broker: str | None = None,
    status_filter: str | None = None,
    symbol_filter: str | None = None,
) -> CommandResult:
    adapter = None
    try:
        adapter = get_broker_adapter(broker_name=broker)
        service = OrderLifecycleService(adapter)
        statuses = _resolve_exception_status_filter(status_filter)
        allowed_symbols = _resolve_symbol_filter(symbol_filter)
        records = service.list_exception_orders(
            account_label=account,
            statuses=statuses,
        )
        if allowed_symbols is not None:
            records = [record for record in records if _symbol_matches_filter(record.symbol, allowed_symbols)]
        if not records and (status_filter or symbol_filter):
            return CommandResult(
                exit_code=0,
                stdout=f"No tracked execution exceptions matching filters: {_format_filter_summary(status_filter=status_filter, symbol_filter=symbol_filter)}",
            )
        return CommandResult(exit_code=0, stdout=render_exception_orders(records))
    except Exception as exc:
        msg = f"Failed to load tracked execution exceptions: {exc}"
        get_logger(__name__).error(msg)
        return CommandResult(exit_code=1, stderr=msg)
    finally:
        close_fn = getattr(adapter, "close", None)
        if callable(close_fn):
            close_fn()


def run_reconcile(
    *,
    account: str = "main",
    broker: str | None = None,
) -> CommandResult:
    adapter = None
    try:
        adapter = get_broker_adapter(broker_name=broker)
        service = OrderLifecycleService(adapter)
        outcome = service.reconcile(account_label=account)
        return CommandResult(
            exit_code=0,
            stdout=render_reconcile_summary(
                report=outcome.report,
                state_path=str(outcome.state_path),
                tracked_orders=len(outcome.state.broker_orders),
                fill_events=len(outcome.state.fill_events),
                new_fill_events=outcome.new_fill_events,
                refreshed_orders=outcome.refreshed_orders,
                changed_orders=outcome.changed_orders,
            ),
        )
    except Exception as exc:
        msg = f"Manual reconcile failed: {exc}"
        get_logger(__name__).error(msg)
        return CommandResult(exit_code=1, stderr=msg)
    finally:
        close_fn = getattr(adapter, "close", None)
        if callable(close_fn):
            close_fn()


def run_cancel(
    *,
    order_ref: str,
    account: str = "main",
    broker: str | None = None,
) -> CommandResult:
    adapter = None
    try:
        adapter = get_broker_adapter(broker_name=broker)
        service = OrderLifecycleService(adapter)
        outcome = service.cancel_order(account_label=account, order_ref=order_ref)
        return CommandResult(
            exit_code=0,
            stdout=render_cancel_summary(
                broker_name=outcome.broker_name,
                account_label=outcome.account_label,
                order_ref=outcome.order_ref,
                broker_order_id=outcome.broker_order_id,
                client_order_id=outcome.client_order_id,
                status=outcome.status,
                state_path=str(outcome.state_path),
                warnings=outcome.warnings,
            ),
        )
    except Exception as exc:
        msg = f"Cancel failed: {exc}"
        get_logger(__name__).error(msg)
        return CommandResult(exit_code=1, stderr=msg)
    finally:
        close_fn = getattr(adapter, "close", None)
        if callable(close_fn):
            close_fn()


def run_cancel_all(
    *,
    account: str = "main",
    broker: str | None = None,
) -> CommandResult:
    adapter = None
    try:
        adapter = get_broker_adapter(broker_name=broker)
        service = OrderLifecycleService(adapter)
        outcome = service.cancel_all_open_orders(account_label=account)
        return CommandResult(exit_code=0, stdout=render_bulk_cancel_summary(outcome))
    except Exception as exc:
        msg = f"Bulk cancel failed: {exc}"
        get_logger(__name__).error(msg)
        return CommandResult(exit_code=1, stderr=msg)
    finally:
        close_fn = getattr(adapter, "close", None)
        if callable(close_fn):
            close_fn()


def run_cancel_rest(
    *,
    order_ref: str,
    account: str = "main",
    broker: str | None = None,
) -> CommandResult:
    adapter = None
    try:
        adapter = get_broker_adapter(broker_name=broker)
        service = OrderLifecycleService(adapter)
        outcome = service.cancel_remaining_order(account_label=account, order_ref=order_ref)
        return CommandResult(
            exit_code=0,
            stdout=render_cancel_summary(
                broker_name=outcome.broker_name,
                account_label=outcome.account_label,
                order_ref=outcome.order_ref,
                broker_order_id=outcome.broker_order_id,
                client_order_id=outcome.client_order_id,
                status=outcome.status,
                state_path=str(outcome.state_path),
                warnings=outcome.warnings,
            ),
        )
    except Exception as exc:
        msg = f"Cancel-rest failed: {exc}"
        get_logger(__name__).error(msg)
        return CommandResult(exit_code=1, stderr=msg)
    finally:
        close_fn = getattr(adapter, "close", None)
        if callable(close_fn):
            close_fn()


def run_order(
    *,
    order_ref: str,
    account: str = "main",
    broker: str | None = None,
) -> CommandResult:
    adapter = None
    try:
        adapter = get_broker_adapter(broker_name=broker)
        service = OrderLifecycleService(adapter)
        tracked = service.get_tracked_order(account_label=account, order_ref=order_ref)
        return CommandResult(exit_code=0, stdout=render_tracked_order_detail(tracked))
    except Exception as exc:
        msg = f"Order lookup failed: {exc}"
        get_logger(__name__).error(msg)
        return CommandResult(exit_code=1, stderr=msg)
    finally:
        close_fn = getattr(adapter, "close", None)
        if callable(close_fn):
            close_fn()


def run_retry(
    *,
    order_ref: str,
    account: str = "main",
    broker: str | None = None,
) -> CommandResult:
    adapter = None
    try:
        adapter = get_broker_adapter(broker_name=broker)
        service = OrderLifecycleService(adapter)
        outcome = service.retry_order(account_label=account, order_ref=order_ref)
        return CommandResult(
            exit_code=0,
            stdout=render_retry_summary(
                broker_name=outcome.broker_name,
                account_label=outcome.account_label,
                order_ref=outcome.order_ref,
                new_child_order_id=outcome.new_child_order_id,
                broker_order_id=outcome.broker_order_id,
                broker_status=outcome.broker_status,
                state_path=str(outcome.state_path),
                warnings=outcome.warnings,
            ),
        )
    except Exception as exc:
        msg = f"Retry failed: {exc}"
        get_logger(__name__).error(msg)
        return CommandResult(exit_code=1, stderr=msg)
    finally:
        close_fn = getattr(adapter, "close", None)
        if callable(close_fn):
            close_fn()


def run_resume_remaining(
    *,
    order_ref: str,
    account: str = "main",
    broker: str | None = None,
) -> CommandResult:
    adapter = None
    try:
        adapter = get_broker_adapter(broker_name=broker)
        service = OrderLifecycleService(adapter)
        outcome = service.resume_remaining_order(account_label=account, order_ref=order_ref)
        return CommandResult(
            exit_code=0,
            stdout=render_resume_remaining_summary(outcome),
        )
    except Exception as exc:
        msg = f"Resume remaining failed: {exc}"
        get_logger(__name__).error(msg)
        return CommandResult(exit_code=1, stderr=msg)
    finally:
        close_fn = getattr(adapter, "close", None)
        if callable(close_fn):
            close_fn()


def run_accept_partial(
    *,
    order_ref: str,
    account: str = "main",
    broker: str | None = None,
) -> CommandResult:
    adapter = None
    try:
        adapter = get_broker_adapter(broker_name=broker)
        service = OrderLifecycleService(adapter)
        outcome = service.accept_partial_fill(account_label=account, order_ref=order_ref)
        return CommandResult(
            exit_code=0,
            stdout=render_accept_partial_summary(outcome),
        )
    except Exception as exc:
        msg = f"Accept partial failed: {exc}"
        get_logger(__name__).error(msg)
        return CommandResult(exit_code=1, stderr=msg)
    finally:
        close_fn = getattr(adapter, "close", None)
        if callable(close_fn):
            close_fn()


def run_reprice(
    *,
    order_ref: str,
    limit_price: float,
    account: str = "main",
    broker: str | None = None,
) -> CommandResult:
    adapter = None
    try:
        adapter = get_broker_adapter(broker_name=broker)
        service = OrderLifecycleService(adapter)
        outcome = service.reprice_order(
            account_label=account,
            order_ref=order_ref,
            limit_price=limit_price,
        )
        return CommandResult(exit_code=0, stdout=render_reprice_summary(outcome))
    except Exception as exc:
        msg = f"Reprice failed: {exc}"
        get_logger(__name__).error(msg)
        return CommandResult(exit_code=1, stderr=msg)
    finally:
        close_fn = getattr(adapter, "close", None)
        if callable(close_fn):
            close_fn()


def run_retry_stale(
    *,
    older_than_minutes: int = 5,
    account: str = "main",
    broker: str | None = None,
) -> CommandResult:
    adapter = None
    try:
        adapter = get_broker_adapter(broker_name=broker)
        service = OrderLifecycleService(adapter)
        outcome = service.retry_stale_orders(
            account_label=account,
            older_than_minutes=older_than_minutes,
        )
        return CommandResult(exit_code=0, stdout=render_stale_retry_summary(outcome))
    except Exception as exc:
        msg = f"Stale retry failed: {exc}"
        get_logger(__name__).error(msg)
        return CommandResult(exit_code=1, stderr=msg)
    finally:
        close_fn = getattr(adapter, "close", None)
        if callable(close_fn):
            close_fn()


def run_state_doctor(
    *,
    account: str = "main",
    broker: str | None = None,
) -> CommandResult:
    try:
        selected_broker = resolve_broker_name(broker)
        result = StateMaintenanceService().doctor(
            broker_name=selected_broker,
            account_label=account,
        )
        exit_code = 0 if all(issue.severity != "ERROR" for issue in result.issues) else 1
        return CommandResult(exit_code=exit_code, stdout=render_state_doctor_summary(result))
    except Exception as exc:
        msg = f"State doctor failed: {exc}"
        get_logger(__name__).error(msg)
        return CommandResult(exit_code=1, stderr=msg)


def run_state_prune(
    *,
    older_than_days: int,
    apply: bool,
    account: str = "main",
    broker: str | None = None,
) -> CommandResult:
    try:
        selected_broker = resolve_broker_name(broker)
        result = StateMaintenanceService().prune(
            broker_name=selected_broker,
            account_label=account,
            older_than_days=older_than_days,
            apply=apply,
        )
        return CommandResult(exit_code=0, stdout=render_state_prune_summary(result))
    except Exception as exc:
        msg = f"State prune failed: {exc}"
        get_logger(__name__).error(msg)
        return CommandResult(exit_code=1, stderr=msg)


def run_state_repair(
    *,
    clear_kill_switch: bool,
    dedupe_fills: bool,
    drop_orphan_fills: bool,
    drop_orphan_terminal_broker_orders: bool,
    recompute_parent_aggregates: bool,
    account: str = "main",
    broker: str | None = None,
) -> CommandResult:
    try:
        selected_broker = resolve_broker_name(broker)
        result = StateMaintenanceService().repair(
            broker_name=selected_broker,
            account_label=account,
            clear_kill_switch=clear_kill_switch,
            dedupe_fills=dedupe_fills,
            drop_orphan_fills=drop_orphan_fills,
            drop_orphan_terminal_broker_orders=drop_orphan_terminal_broker_orders,
            recompute_parent_aggregates=recompute_parent_aggregates,
        )
        return CommandResult(exit_code=0, stdout=render_state_repair_summary(result))
    except Exception as exc:
        msg = f"State repair failed: {exc}"
        get_logger(__name__).error(msg)
        return CommandResult(exit_code=1, stderr=msg)


def run_rebalance(
    input_file: str,
    account: str = "main",
    dry_run: bool = True,
    target_gross_exposure: float = 1.0,
    broker: str | None = None,
) -> CommandResult:
    logger = get_logger(__name__)
    file_path = Path(input_file)

    if not file_path.exists():
        return CommandResult(exit_code=1, stderr=f"File not found: {input_file}")

    if file_path.suffix.lower() != ".json":
        return CommandResult(
            exit_code=1,
            stderr=(
                "Legacy workbook inputs are deprecated for live execution. "
                "Provide a canonical schema-v2 targets JSON and rerun "
                "'qexec rebalance <targets.json>'."
            ),
        )

    try:
        selected_broker = resolve_broker_name(broker)
        env_name = "paper" if is_paper_broker(selected_broker) else "real"
        guard_error = validate_live_execution_guard(env_name=env_name, dry_run=dry_run)
        if guard_error:
            return CommandResult(exit_code=1, stderr=guard_error)
        logger.info("Mode: %s", "dry-run" if dry_run else "live")
        logger.info("Reading targets file: %s", input_file)
        logger.info("Broker: %s", selected_broker)
        logger.info("Account: %s", account)

        targets_doc = read_targets_json(file_path, require_schema_v2=True)

        service = RebalanceService(
            env=env_name,
            broker_name=selected_broker,
            account_label=account,
        )
        client = service._get_client()
        account_snapshot = get_account_snapshot(
            env=env_name,
            include_quotes=False,
            client=client,
            broker_name=selected_broker,
            account_label=account,
        )

        target_symbols = {
            f"{target.symbol}.{target.market}" for target in targets_doc.targets
        }
        held_symbols = {position.symbol for position in account_snapshot.positions}
        all_symbols = sorted(target_symbols | held_symbols)
        if all_symbols:
            quote_objs = get_quotes(
                all_symbols,
                client=client,
                broker_name=selected_broker,
            )
            quote_map = {symbol: quote.price for symbol, quote in quote_objs.items()}
        else:
            quote_map = {}

        if quote_map and account_snapshot.positions:
            for position in account_snapshot.positions:
                price = float(quote_map.get(position.symbol, position.last_price or 0.0) or 0.0)
                if price > 0:
                    position.last_price = price
                    position.estimated_value = float(price) * float(position.quantity)
            total_market_value = sum(float(position.estimated_value) for position in account_snapshot.positions)
            account_snapshot.total_market_value = total_market_value
            if not account_snapshot.total_portfolio_value:
                account_snapshot.total_portfolio_value = float(account_snapshot.cash_usd) + total_market_value

        try:
            effective_exposure = targets_doc.target_gross_exposure
            if target_gross_exposure != 1.0 and targets_doc.target_gross_exposure == 1.0:
                effective_exposure = target_gross_exposure

            result = service.plan_rebalance(
                targets_doc.targets,
                account_snapshot,
                quotes=quote_map,
                target_gross_exposure=effective_exposure,
            )
            result.dry_run = dry_run
            result.sheet_name = targets_doc.asof or file_path.stem
            result.target_source = targets_doc.source
            result.target_asof = targets_doc.asof or file_path.stem
            result.target_input_path = str(file_path)
            result.broker_name = selected_broker
            result.account_label = account

            result.orders = service.execute_orders(
                result.orders,
                dry_run=dry_run,
                target_source=result.target_source,
                target_asof=result.target_asof,
                target_input_path=result.target_input_path,
            )
            if service._last_reconcile_report is not None:
                result.reconcile_warnings = list(service._last_reconcile_report.warnings)
            audit_log_path = service.save_audit_log(result, dry_run=dry_run)
            result.audit_log_path = str(audit_log_path)
            diff_view = render_rebalance_diff(result, account_snapshot)
            return CommandResult(
                exit_code=0,
                stdout=diff_view.text,
                rich_renderable=diff_view.rich,
            )
        finally:
            service.close()
    except Exception as exc:
        logger.error("Rebalance failed: %s", exc)
        return CommandResult(exit_code=1, stderr=str(exc))


def _resolve_broker_status_filter(raw: str | None) -> set[str] | None:
    if raw is None:
        return None
    normalized = [part.strip().upper().replace("-", "_") for part in raw.split(",") if part.strip()]
    if not normalized:
        return None
    allowed: set[str] = set()
    for part in normalized:
        if part in {"ALL", "*"}:
            return None
        allowed.update(_BROKER_STATUS_GROUPS.get(part, {part}))
    return allowed


def _resolve_exception_status_filter(raw: str | None) -> set[str]:
    if raw is None:
        return set(DEFAULT_EXCEPTION_STATUSES)
    normalized = [part.strip().upper().replace("-", "_") for part in raw.split(",") if part.strip()]
    if not normalized:
        return set(DEFAULT_EXCEPTION_STATUSES)
    allowed: set[str] = set()
    for part in normalized:
        allowed.update(_EXCEPTION_STATUS_GROUPS.get(part, {part}))
    return allowed


def _resolve_symbol_filter(raw: str | None) -> set[str] | None:
    if raw is None:
        return None
    normalized = {part.strip().upper() for part in raw.split(",") if part.strip()}
    return normalized or None


def _symbol_matches_filter(symbol: str, allowed: set[str] | None) -> bool:
    if allowed is None:
        return True
    normalized = str(symbol).strip().upper()
    base = normalized.rsplit(".", 1)[0] if "." in normalized else normalized
    return normalized in allowed or base in allowed


def _format_filter_summary(
    *,
    status_filter: str | None,
    symbol_filter: str | None,
) -> str:
    parts: list[str] = []
    if status_filter:
        parts.append(f"status={status_filter}")
    if symbol_filter:
        parts.append(f"symbol={symbol_filter}")
    return ", ".join(parts) if parts else "none"


def main() -> int:
    run_id = uuid.uuid4().hex[:12]
    set_run_id(run_id)
    logger = get_logger(__name__)

    parser = create_parser()
    try:
        args = parser.parse_args()
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
        if code != 0 and len(sys.argv) > 1:
            logger.error("Unknown command: %s", sys.argv[1])
            return 1
        return code

    if not args.command:
        parser.print_help()
        return 0

    if args.command == "quote":
        return _handle_command_result(
            run_quote(args.tickers, broker=getattr(args, "broker", None))
        )
    if args.command == "preflight":
        return _handle_command_result(
            run_preflight(
                symbols=getattr(args, "symbols", None),
                account=getattr(args, "account", "main"),
                broker=getattr(args, "broker", None),
            )
        )
    if args.command == "rebalance":
        return _handle_command_result(
            run_rebalance(
                args.input_file,
                getattr(args, "account", "main"),
                dry_run=not getattr(args, "execute", False),
                target_gross_exposure=getattr(args, "target_gross_exposure", 1.0),
                broker=getattr(args, "broker", None),
            )
        )
    if args.command == "account":
        return _handle_command_result(
            run_account(
                only_funds=getattr(args, "funds", False),
                only_positions=getattr(args, "positions", False),
                fmt=getattr(args, "format", "table"),
                account=getattr(args, "account", "main"),
                broker=getattr(args, "broker", None),
            )
        )
    if args.command == "config":
        return _handle_command_result(
            run_config(getattr(args, "show", True), broker=getattr(args, "broker", None))
        )
    if args.command == "evidence-maturity":
        return _handle_command_result(
            run_evidence_maturity(fmt=getattr(args, "format", "table"))
        )
    if args.command == "evidence-pack":
        return _handle_command_result(
            run_evidence_pack(
                run_id=getattr(args, "run_id"),
                output_dir=getattr(args, "output_dir", None),
                operator_notes=getattr(args, "operator_note", None),
            )
        )
    if args.command == "orders":
        return _handle_command_result(
            run_orders(
                account=getattr(args, "account", "main"),
                broker=getattr(args, "broker", None),
                status_filter=getattr(args, "status", None),
                symbol_filter=getattr(args, "symbol", None),
            )
        )
    if args.command == "exceptions":
        return _handle_command_result(
            run_exceptions(
                account=getattr(args, "account", "main"),
                broker=getattr(args, "broker", None),
                status_filter=getattr(args, "status", None),
                symbol_filter=getattr(args, "symbol", None),
            )
        )
    if args.command == "reconcile":
        return _handle_command_result(
            run_reconcile(
                account=getattr(args, "account", "main"),
                broker=getattr(args, "broker", None),
            )
        )
    if args.command == "cancel":
        return _handle_command_result(
            run_cancel(
                order_ref=getattr(args, "order_ref"),
                account=getattr(args, "account", "main"),
                broker=getattr(args, "broker", None),
            )
        )
    if args.command == "cancel-rest":
        return _handle_command_result(
            run_cancel_rest(
                order_ref=getattr(args, "order_ref"),
                account=getattr(args, "account", "main"),
                broker=getattr(args, "broker", None),
            )
        )
    if args.command == "cancel-all":
        return _handle_command_result(
            run_cancel_all(
                account=getattr(args, "account", "main"),
                broker=getattr(args, "broker", None),
            )
        )
    if args.command == "order":
        return _handle_command_result(
            run_order(
                order_ref=getattr(args, "order_ref"),
                account=getattr(args, "account", "main"),
                broker=getattr(args, "broker", None),
            )
        )
    if args.command == "retry":
        return _handle_command_result(
            run_retry(
                order_ref=getattr(args, "order_ref"),
                account=getattr(args, "account", "main"),
                broker=getattr(args, "broker", None),
            )
        )
    if args.command == "resume-remaining":
        return _handle_command_result(
            run_resume_remaining(
                order_ref=getattr(args, "order_ref"),
                account=getattr(args, "account", "main"),
                broker=getattr(args, "broker", None),
            )
        )
    if args.command == "accept-partial":
        return _handle_command_result(
            run_accept_partial(
                order_ref=getattr(args, "order_ref"),
                account=getattr(args, "account", "main"),
                broker=getattr(args, "broker", None),
            )
        )
    if args.command == "reprice":
        return _handle_command_result(
            run_reprice(
                order_ref=getattr(args, "order_ref"),
                limit_price=getattr(args, "limit_price"),
                account=getattr(args, "account", "main"),
                broker=getattr(args, "broker", None),
            )
        )
    if args.command == "retry-stale":
        return _handle_command_result(
            run_retry_stale(
                older_than_minutes=getattr(args, "older_than_minutes", 5),
                account=getattr(args, "account", "main"),
                broker=getattr(args, "broker", None),
            )
        )
    if args.command == "state-doctor":
        return _handle_command_result(
            run_state_doctor(
                account=getattr(args, "account", "main"),
                broker=getattr(args, "broker", None),
            )
        )
    if args.command == "state-prune":
        return _handle_command_result(
            run_state_prune(
                older_than_days=getattr(args, "older_than_days", 30),
                apply=getattr(args, "apply", False),
                account=getattr(args, "account", "main"),
                broker=getattr(args, "broker", None),
            )
        )
    if args.command == "state-repair":
        return _handle_command_result(
            run_state_repair(
                clear_kill_switch=getattr(args, "clear_kill_switch", False),
                dedupe_fills=getattr(args, "dedupe_fills", False),
                drop_orphan_fills=getattr(args, "drop_orphan_fills", False),
                drop_orphan_terminal_broker_orders=getattr(
                    args, "drop_orphan_terminal_broker_orders", False
                ),
                recompute_parent_aggregates=getattr(
                    args, "recompute_parent_aggregates", False
                ),
                account=getattr(args, "account", "main"),
                broker=getattr(args, "broker", None),
            )
        )

    logger.error("Unknown command: %s", args.command)
    return 1


def app() -> None:
    sys.exit(main())


if __name__ == "__main__":
    app()
