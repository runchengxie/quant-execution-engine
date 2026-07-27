"""CLI entrypoint for the execution engine.

This package splits the former monolithic ``cli.py`` into focused modules:

* ``cli.parser`` (moved from ``cli_parser.py``) builds the argument parser.
* ``cli.render`` (moved from ``report.py``) renders run reports.
* ``cli.commands.*`` holds the individual command handlers.

This ``__init__`` module keeps the public surface stable: ``app`` (the console
script entrypoint), ``main``, ``CommandResult``, and every ``run_*`` handler
remain importable from ``quant_execution_engine.cli``.
"""

from __future__ import annotations

import importlib.util
import sys
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..logging import get_logger, set_run_id

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


from .commands.account import (
    run_account,
    run_config,
    run_evidence_maturity,
    run_evidence_pack,
    run_exceptions,
    run_health_cmd,
    run_preflight,
    run_quote,
    run_report,
)
from .commands.orders import (
    run_broker_fills,
    run_broker_orders,
    run_orders,
    run_reconcile,
)
from .commands.orders_mutate import (
    run_accept_partial,
    run_cancel,
    run_cancel_all,
    run_cancel_rest,
    run_order,
    run_reprice,
    run_resume_remaining,
    run_retry,
    run_retry_stale,
    run_trace_order,
)
from .commands.rebalance import run_rebalance
from .commands.state import (
    run_state_doctor,
    run_state_prune,
    run_state_repair,
)
from .parser import create_parser

__all__ = [
    "CommandResult",
    "app",
    "create_parser",
    "main",
    "run_accept_partial",
    "run_account",
    "run_broker_fills",
    "run_broker_orders",
    "run_cancel",
    "run_cancel_all",
    "run_cancel_rest",
    "run_config",
    "run_evidence_maturity",
    "run_evidence_pack",
    "run_exceptions",
    "run_health_cmd",
    "run_order",
    "run_orders",
    "run_preflight",
    "run_quote",
    "run_rebalance",
    "run_reconcile",
    "run_report",
    "run_reprice",
    "run_resume_remaining",
    "run_retry",
    "run_retry_stale",
    "run_state_doctor",
    "run_state_prune",
    "run_state_repair",
    "run_trace_order",
]


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
        return _handle_command_result(run_quote(args.tickers, broker=getattr(args, "broker", None)))
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
            run_config(
                getattr(args, "show", True),
                broker=getattr(args, "broker", None),
                check_gates=getattr(args, "check_gates", False),
            )
        )
    if args.command == "evidence-maturity":
        return _handle_command_result(run_evidence_maturity(fmt=getattr(args, "format", "table")))
    if args.command == "evidence-pack":
        return _handle_command_result(
            run_evidence_pack(
                run_id=args.run_id,
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
    if args.command == "broker-orders":
        return _handle_command_result(
            run_broker_orders(
                account=getattr(args, "account", "main"),
                broker=getattr(args, "broker", None),
                status_filter=getattr(args, "status", None),
                symbol_filter=getattr(args, "symbol", None),
                broker_order_id_filter=getattr(args, "order_id", None),
                fmt=getattr(args, "format", "table"),
            )
        )
    if args.command == "broker-fills":
        return _handle_command_result(
            run_broker_fills(
                account=getattr(args, "account", "main"),
                broker=getattr(args, "broker", None),
                symbol_filter=getattr(args, "symbol", None),
                broker_order_id_filter=getattr(args, "order_id", None),
                fmt=getattr(args, "format", "table"),
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
                order_ref=args.order_ref,
                account=getattr(args, "account", "main"),
                broker=getattr(args, "broker", None),
            )
        )
    if args.command == "cancel-rest":
        return _handle_command_result(
            run_cancel_rest(
                order_ref=args.order_ref,
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
                order_ref=args.order_ref,
                account=getattr(args, "account", "main"),
                broker=getattr(args, "broker", None),
            )
        )
    if args.command == "trace-order":
        return _handle_command_result(
            run_trace_order(
                order_ref=args.order_ref,
                account=getattr(args, "account", "main"),
                broker=getattr(args, "broker", None),
                fmt=getattr(args, "format", "table"),
            )
        )
    if args.command == "retry":
        return _handle_command_result(
            run_retry(
                order_ref=args.order_ref,
                account=getattr(args, "account", "main"),
                broker=getattr(args, "broker", None),
            )
        )
    if args.command == "resume-remaining":
        return _handle_command_result(
            run_resume_remaining(
                order_ref=args.order_ref,
                account=getattr(args, "account", "main"),
                broker=getattr(args, "broker", None),
            )
        )
    if args.command == "accept-partial":
        return _handle_command_result(
            run_accept_partial(
                order_ref=args.order_ref,
                account=getattr(args, "account", "main"),
                broker=getattr(args, "broker", None),
            )
        )
    if args.command == "reprice":
        return _handle_command_result(
            run_reprice(
                order_ref=args.order_ref,
                limit_price=args.limit_price,
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
                recompute_parent_aggregates=getattr(args, "recompute_parent_aggregates", False),
                account=getattr(args, "account", "main"),
                broker=getattr(args, "broker", None),
            )
        )
    if args.command == "report":
        return _handle_command_result(
            run_report(
                run_id=getattr(args, "run_id", None),
                broker=getattr(args, "broker", None),
                last_n=getattr(args, "last_n", None),
            )
        )
    if args.command == "health":
        return _handle_command_result(
            run_health_cmd(
                broker=getattr(args, "broker", None),
                account=getattr(args, "account", "main"),
            )
        )

    logger.error("Unknown command: %s", args.command)
    return 1


def app() -> None:
    sys.exit(main())


if __name__ == "__main__":
    app()
