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
from .broker.longport import LongPortClient
from .logging import get_logger, set_run_id
from .rebalance import RebalanceService
from .renderers.diff import render_rebalance_diff
from .renderers.jsonout import render_multiple_account_snapshots_json
from .renderers.table import render_multiple_account_snapshots, render_quotes
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


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="qexec",
        description="Quant Execution Engine - LongPort-based live portfolio execution",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  qexec config
  qexec account --format json
  qexec quote AAPL 700.HK
  qexec rebalance outputs/targets/2026-04-09.json
  qexec rebalance outputs/targets/2026-04-09.json --execute
        """,
    )
    parser.add_argument("--version", action="version", version="%(prog)s 0.2.0")

    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")

    quote_parser = subparsers.add_parser("quote", help="Fetch real-time quotes")
    quote_parser.add_argument("tickers", nargs="+", help="Tickers such as AAPL or 700.HK")

    rebalance_parser = subparsers.add_parser(
        "rebalance",
        help="Preview or execute rebalance orders from a schema-v2 targets JSON",
    )
    rebalance_parser.add_argument("input_file", type=str, help="targets JSON file")
    rebalance_parser.add_argument("--account", type=str, default="main")
    rebalance_parser.add_argument(
        "--execute", action="store_true", help="Place real orders instead of dry-run preview"
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
        "--format",
        choices=["table", "json"],
        default="table",
        help="Output format",
    )

    config_parser = subparsers.add_parser("config", help="Show effective LongPort config")
    config_parser.add_argument("--show", action="store_true", default=True)

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


def run_quote(tickers: list[str]) -> CommandResult:
    try:
        __import__("quant_execution_engine.broker.longport")
        quotes_dict = get_quotes(tickers)
        return CommandResult(exit_code=0, stdout=render_quotes(list(quotes_dict.values())))
    except ImportError as exc:
        err = (
            "Error importing LongPort module: {msg}\n"
            "Please ensure the 'longport' package is installed: pip install longport"
        ).format(msg=exc)
        get_logger(__name__).error(err)
        return CommandResult(exit_code=1, stderr=err)
    except Exception as exc:
        get_logger(__name__).error("Failed to fetch quotes: %s", exc)
        return CommandResult(exit_code=1, stderr=str(exc))


def run_account(
    only_funds: bool = False,
    only_positions: bool = False,
    fmt: str = "table",
) -> CommandResult:
    try:
        __import__("quant_execution_engine.broker.longport")
        if only_funds and only_positions:
            only_positions = False
        snapshot = get_account_snapshot(env="real")
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
    except ImportError as exc:
        err = (
            "Failed to import LongPort module: {msg}\n"
            "Please ensure the 'longport' package is installed: pip install longport"
        ).format(msg=exc)
        get_logger(__name__).error(err)
        return CommandResult(exit_code=1, stderr=err)
    except Exception as exc:
        msg = f"Failed to get account overview: {exc}"
        get_logger(__name__).error(msg)
        return CommandResult(exit_code=1, stderr=msg)


def run_config(show: bool = True) -> CommandResult:
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

    region = _getenv_both("LONGPORT_REGION", "LONGBRIDGE_REGION", "hk")
    overnight = _getenv_both("LONGPORT_ENABLE_OVERNIGHT", "LONGBRIDGE_ENABLE_OVERNIGHT", "false")
    max_notional = _getenv_both("LONGPORT_MAX_NOTIONAL_PER_ORDER", "LONGBRIDGE_MAX_NOTIONAL_PER_ORDER", "0")
    max_qty = _getenv_both("LONGPORT_MAX_QTY_PER_ORDER", "LONGBRIDGE_MAX_QTY_PER_ORDER", "0")
    tw_start = _getenv_both("LONGPORT_TRADING_WINDOW_START", "LONGBRIDGE_TRADING_WINDOW_START", "09:30")
    tw_end = _getenv_both("LONGPORT_TRADING_WINDOW_END", "LONGBRIDGE_TRADING_WINDOW_END", "16:00")

    app_key = os.getenv("LONGPORT_APP_KEY") or os.getenv("LONGBRIDGE_APP_KEY")
    app_secret = os.getenv("LONGPORT_APP_SECRET") or os.getenv("LONGBRIDGE_APP_SECRET")
    token = os.getenv("LONGPORT_ACCESS_TOKEN") or os.getenv("LONGPORT_ACCESS_TOKEN_REAL")

    def _mask(value: str | None) -> str:
        if not value:
            return "(not set)"
        if len(value) <= 6:
            return "***"
        return value[:3] + "***" + value[-3:]

    lines = [
        "LongPort Effective Configuration:",
        "- Region:        " + region,
        "- Overnight:     " + ("enabled" if _to_bool(overnight) else "disabled"),
        "- Max Notional:  " + _fmt_unlimited(_to_float(max_notional, 0.0)),
        "- Max Quantity:  " + _fmt_unlimited(_to_int(max_qty, 0)),
        "- Trade Window:  " + f"{tw_start} - {tw_end}",
        "- App Key:       " + _mask(app_key),
        "- App Secret:    " + _mask(app_secret),
        "- Access Token:  " + _mask(token),
    ]
    return CommandResult(exit_code=0, stdout="\n".join(lines))


def run_rebalance(
    input_file: str,
    account: str = "main",
    dry_run: bool = True,
    target_gross_exposure: float = 1.0,
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
        __import__("quant_execution_engine.broker.longport")
        logger.info("Mode: %s", "dry-run" if dry_run else "live")
        logger.info("Reading targets file: %s", input_file)
        logger.info("Account: %s", account)

        targets_doc = read_targets_json(file_path, require_schema_v2=True)

        client = LongPortClient(env="real")
        account_snapshot = get_account_snapshot(env="real", include_quotes=False, client=client)

        target_symbols = {
            f"{target.symbol}.{target.market}" for target in targets_doc.targets
        }
        held_symbols = {position.symbol for position in account_snapshot.positions}
        all_symbols = sorted(target_symbols | held_symbols)
        if all_symbols:
            quote_objs = get_quotes(all_symbols, client=client)
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

        service = RebalanceService(env="real", client=client)
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

            result.orders = service.execute_orders(result.orders, dry_run=dry_run)
            service.save_audit_log(result, dry_run=dry_run)
            diff_view = render_rebalance_diff(result, account_snapshot)
            return CommandResult(
                exit_code=0,
                stdout=diff_view.text,
                rich_renderable=diff_view.rich,
            )
        finally:
            service.close()
    except ImportError as exc:
        err = (
            "Failed to import LongPort module: {msg}\n"
            "Please ensure the 'longport' package is installed: pip install longport"
        ).format(msg=exc)
        logger.error(err)
        return CommandResult(exit_code=1, stderr=err)
    except Exception as exc:
        logger.error("Rebalance failed: %s", exc)
        return CommandResult(exit_code=1, stderr=str(exc))


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
        return _handle_command_result(run_quote(args.tickers))
    if args.command == "rebalance":
        return _handle_command_result(
            run_rebalance(
                args.input_file,
                getattr(args, "account", "main"),
                dry_run=not getattr(args, "execute", False),
                target_gross_exposure=getattr(args, "target_gross_exposure", 1.0),
            )
        )
    if args.command == "account":
        return _handle_command_result(
            run_account(
                only_funds=getattr(args, "funds", False),
                only_positions=getattr(args, "positions", False),
                fmt=getattr(args, "format", "table"),
            )
        )
    if args.command == "config":
        return _handle_command_result(run_config(getattr(args, "show", True)))

    logger.error("Unknown command: %s", args.command)
    return 1


def app() -> None:
    sys.exit(main())


if __name__ == "__main__":
    app()
