"""Execution-oriented command line interface."""

from __future__ import annotations

import argparse
import importlib.util
import sys
import uuid
from typing import TYPE_CHECKING

from .commands.result import CommandResult
from ..shared.logging import get_logger, set_run_id

if TYPE_CHECKING:
    from rich.console import Console

_RICH_AVAILABLE = importlib.util.find_spec("rich") is not None
_RICH_CONSOLE: Console | None = None

if _RICH_AVAILABLE:
    from rich.console import Console
    from rich.traceback import install as install_rich_traceback

    _RICH_CONSOLE = Console()
    install_rich_traceback(show_locals=False)


def create_parser() -> argparse.ArgumentParser:
    """Create command line argument parser.

    Returns:
        argparse.ArgumentParser: Configured argument parser
    """
    parser = argparse.ArgumentParser(
        prog="stockq",
        description=(
            "Stock Execution Engine - 基于 canonical schema-v2 targets.json 的 "
            "LongPort 调仓与执行工具"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例用法:
  stockq lb-config
  stockq lb-account --format json
  stockq lb-quote AAPL 700.HK
  stockq lb-rebalance outputs/targets/2025-09-05.json
  stockq lb-rebalance outputs/targets/2025-09-05.json --execute
        """,
    )

    # Add version information
    parser.add_argument("--version", action="version", version="%(prog)s 0.1.0")

    # Create subcommands
    subparsers = parser.add_subparsers(
        dest="command", help="可用的命令", metavar="COMMAND"
    )
    parser._subparsers_action = subparsers  # type: ignore[attr-defined]

    # LongPort quote command
    lb_quote_parser = subparsers.add_parser(
        "lb-quote",
        help="获取LongPort实时报价",
        description="通过LongPort API获取指定股票的实时报价",
    )
    lb_quote_parser.add_argument(
        "tickers", nargs="+", help="股票代码列表（如 AAPL MSFT 700.HK）"
    )

    # LongPort rebalance command
    lb_rebalance_parser = subparsers.add_parser(
        "lb-rebalance",
        help="根据目标组合调整仓位",
        description=(
            "读取 canonical schema-v2 targets JSON，生成仓位调整订单（默认干跑模式）"
        ),
    )
    lb_rebalance_parser.add_argument(
        "input_file",
        type=str,
        help=(
            "目标输入文件：canonical targets JSON（如 outputs/targets/2025-09-05.json）"
        ),
    )
    lb_rebalance_parser.add_argument(
        "--account", type=str, default="main", help="账户名称（默认：main）"
    )
    lb_rebalance_parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="干跑模式，只打印不实际下单（默认开启）",
    )
    lb_rebalance_parser.add_argument(
        "--execute", action="store_true", help="实际执行交易（关闭干跑模式）"
    )
    lb_rebalance_parser.add_argument(
        "--target-gross-exposure",
        type=float,
        default=1.0,
        help="目标总敞口比例覆盖值（当 targets.json 未显式给出时使用，默认 1.0）",
    )

    # No longer expose env, default to real; --execute controls actual order execution

    # LongPort account overview command
    lb_account_parser = subparsers.add_parser(
        "lb-account",
        help="查看 LongPort 真实账户概览",
        description="展示真实账户的资金与持仓",
    )
    lb_account_parser.add_argument("--funds", action="store_true", help="只看资金")
    lb_account_parser.add_argument("--positions", action="store_true", help="只看持仓")
    lb_account_parser.add_argument(
        "--format",
        choices=["table", "json"],
        default="table",
        help="输出格式：table 表格 / json JSON格式",
    )

    # LongPort configuration display
    lb_cfg_parser = subparsers.add_parser(
        "lb-config",
        help="显示 LongPort 相关环境配置",
        description="读取环境变量并显示LongPort区域、隔夜、下单上限与交易时段等配置",
    )
    lb_cfg_parser.add_argument(
        "--show",
        action="store_true",
        default=True,
        help="显示配置（默认）",
    )

    return parser


def _handle_command_result(result: int | CommandResult) -> int:
    """Normalize command results to an exit code while emitting output."""

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
        return result.exit_code
    return int(result)


def main() -> int:
    """Main entry function.

    Responsible only for argument parsing and command dispatching.

    Returns:
        int: Exit code (0 indicates success)
    """
    run_id = uuid.uuid4().hex[:12]
    set_run_id(run_id)
    logger = get_logger(__name__)

    parser = create_parser()
    try:
        args = parser.parse_args()
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 1
        if code != 0 and len(sys.argv) > 1:
            logger.error("Unknown command: %s", sys.argv[1])
            return 1
        return code

    # Show help if no command is provided
    if not args.command:
        parser.print_help()
        return 0

    # Dispatch to corresponding handler function based on command
    try:
        if args.command == "lb-quote":
            return _handle_command_result(run_lb_quote(args.tickers))
        elif args.command == "lb-rebalance":
            # If --execute is specified, disable dry-run mode
            dry_run = not getattr(args, "execute", False)
            return _handle_command_result(
                run_lb_rebalance(
                    args.input_file,
                    getattr(args, "account", "main"),
                    dry_run,
                    "real",
                    getattr(args, "target_gross_exposure", 1.0),
                )
            )
        elif args.command == "lb-account":
            return _handle_command_result(
                run_lb_account(
                    only_funds=getattr(args, "funds", False),
                    only_positions=getattr(args, "positions", False),
                    fmt=getattr(args, "format", "table"),
                )
            )
        elif args.command == "lb-config":
            return _handle_command_result(run_lb_config(getattr(args, "show", True)))
        else:
            logger.error("Unknown command: %s", args.command)
            return 1
    except ImportError as e:
        logger.error(f"无法导入命令模块: {e}")
        return 1


def run_lb_quote(tickers: list[str]) -> int:  # type: ignore[override]
    """Forwarder for lb_quote to support test patching and lazy import."""
    from .commands.lb_quote import run_lb_quote as _run_lb_quote

    return _handle_command_result(_run_lb_quote(tickers))


def run_lb_rebalance(
    input_file: str,
    account: str = "main",
    dry_run: bool = True,
    env: str = "real",
    target_gross_exposure: float = 1.0,
) -> int:  # type: ignore[override]
    """Forwarder for lb_rebalance to support test patching and lazy import."""
    from .commands.lb_rebalance import run_lb_rebalance as _run_lb_rebalance

    return _handle_command_result(
        _run_lb_rebalance(
            input_file,
            account,
            dry_run,
            env,
            target_gross_exposure,
        )
    )


def run_lb_account(
    only_funds: bool = False,
    only_positions: bool = False,
    fmt: str = "table",
) -> int:  # type: ignore[override]
    """Forwarder for lb_account with lazy import."""
    try:
        from .commands.lb_account import run_lb_account as _run_lb_account
    except ImportError:
        logger = get_logger(__name__)
        logger.error(
            "Failed to import LongPort module. Please install it via 'pip install "
            "longport'"
        )
        return 1

    return _handle_command_result(
        _run_lb_account(
            only_funds=only_funds,
            only_positions=only_positions,
            fmt=fmt,
        )
    )


def run_lb_config(show: bool = True) -> int:  # type: ignore[override]
    """Forwarder for lb_config with lazy import."""
    from .commands.lb_config import run_lb_config as _run_lb_config

    return _handle_command_result(_run_lb_config(show))


def app() -> None:
    """Application entry point for the ``stockq`` console script.

    The entry point is defined after the helper forwarders so that when this
    module is executed as ``python -m stock_analysis.cli``, all required
    functions are already bound before :func:`main` dispatches to them.
    """

    sys.exit(main())


if __name__ == "__main__":
    app()
