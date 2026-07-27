from __future__ import annotations

from ...broker import resolve_broker_name
from ...logging import get_logger
from ...renderers.table import (
    render_state_doctor_summary,
    render_state_prune_summary,
    render_state_repair_summary,
)
from ...state_tools import StateMaintenanceService
from .. import CommandResult


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
