from __future__ import annotations

from ...broker import get_broker_adapter
from ...broker.base import UnsupportedBrokerOperationError
from ...execution import ExecutionStateStore, OrderLifecycleService
from ...logging import get_logger
from ...renderers.jsonout import render_json
from ...renderers.table import (
    render_broker_fill_history,
    render_broker_order_history,
    render_broker_orders,
    render_reconcile_summary,
)
from .. import CommandResult
from ._common import (
    _close_broker_adapter,
    _format_filter_summary,
    _resolve_broker_status_filter,
    _resolve_identifier_filter,
    _resolve_symbol_filter,
    _symbol_matches_filter,
)


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
            key=lambda record: (
                record.updated_at,
                record.submitted_at,
                record.broker_order_id,
            ),
            reverse=True,
        )
        allowed_statuses = _resolve_broker_status_filter(status_filter)
        allowed_symbols = _resolve_symbol_filter(symbol_filter)
        if allowed_statuses is not None:
            records = [record for record in records if record.status in allowed_statuses]
        if allowed_symbols is not None:
            records = [
                record
                for record in records
                if _symbol_matches_filter(record.symbol, allowed_symbols)
            ]
        if not records and (allowed_statuses is not None or allowed_symbols is not None):
            filter_summary = _format_filter_summary(
                status_filter=status_filter,
                symbol_filter=symbol_filter,
            )
            return CommandResult(
                exit_code=0,
                stdout=f"No tracked broker orders matching filters: {filter_summary}",
            )
        return CommandResult(exit_code=0, stdout=render_broker_orders(records))
    except Exception as exc:
        msg = f"Failed to load tracked orders: {exc}"
        get_logger(__name__).error(msg)
        return CommandResult(exit_code=1, stderr=msg)
    finally:
        _close_broker_adapter(adapter)


def run_broker_orders(
    *,
    account: str = "main",
    broker: str | None = None,
    status_filter: str | None = None,
    symbol_filter: str | None = None,
    broker_order_id_filter: str | None = None,
    fmt: str = "table",
) -> CommandResult:
    adapter = None
    try:
        adapter = get_broker_adapter(broker_name=broker)
        resolved = adapter.resolve_account(account)
        broker_order_ids = _resolve_identifier_filter(broker_order_id_filter)
        records = adapter.list_order_history(
            resolved,
            symbol=symbol_filter if symbol_filter and "," not in symbol_filter else None,
            broker_order_id=next(iter(broker_order_ids))
            if broker_order_ids and len(broker_order_ids) == 1
            else None,
        )
        allowed_statuses = _resolve_broker_status_filter(status_filter)
        allowed_symbols = _resolve_symbol_filter(symbol_filter)
        if allowed_statuses is not None:
            records = [record for record in records if record.status in allowed_statuses]
        if allowed_symbols is not None:
            records = [
                record
                for record in records
                if _symbol_matches_filter(record.symbol, allowed_symbols)
            ]
        if broker_order_ids is not None:
            records = [record for record in records if record.broker_order_id in broker_order_ids]
        records = sorted(
            records,
            key=lambda record: (
                record.updated_at,
                record.submitted_at,
                record.broker_order_id,
            ),
            reverse=True,
        )
        if fmt == "json":
            return CommandResult(exit_code=0, stdout=render_json(records))
        if not records and (
            allowed_statuses is not None
            or allowed_symbols is not None
            or broker_order_ids is not None
        ):
            return CommandResult(
                exit_code=0,
                stdout=(
                    "No broker-side order history matching filters: "
                    + _format_filter_summary(
                        status_filter=status_filter,
                        symbol_filter=symbol_filter,
                        broker_order_id_filter=broker_order_id_filter,
                    )
                ),
            )
        return CommandResult(exit_code=0, stdout=render_broker_order_history(records))
    except UnsupportedBrokerOperationError as exc:
        msg = f"Broker order history is unavailable: {exc}"
        get_logger(__name__).error(msg)
        return CommandResult(exit_code=1, stderr=msg)
    except Exception as exc:
        msg = f"Failed to load broker-side order history: {exc}"
        get_logger(__name__).error(msg)
        return CommandResult(exit_code=1, stderr=msg)
    finally:
        _close_broker_adapter(adapter)


def run_broker_fills(
    *,
    account: str = "main",
    broker: str | None = None,
    symbol_filter: str | None = None,
    broker_order_id_filter: str | None = None,
    fmt: str = "table",
) -> CommandResult:
    adapter = None
    try:
        adapter = get_broker_adapter(broker_name=broker)
        resolved = adapter.resolve_account(account)
        broker_order_ids = _resolve_identifier_filter(broker_order_id_filter)
        records = adapter.list_fill_history(
            resolved,
            symbol=symbol_filter if symbol_filter and "," not in symbol_filter else None,
            broker_order_id=next(iter(broker_order_ids))
            if broker_order_ids and len(broker_order_ids) == 1
            else None,
        )
        allowed_symbols = _resolve_symbol_filter(symbol_filter)
        if allowed_symbols is not None:
            records = [
                record
                for record in records
                if _symbol_matches_filter(record.symbol, allowed_symbols)
            ]
        if broker_order_ids is not None:
            records = [record for record in records if record.broker_order_id in broker_order_ids]
        records = sorted(
            records,
            key=lambda record: (
                record.filled_at,
                record.broker_order_id,
                record.fill_id,
            ),
            reverse=True,
        )
        if fmt == "json":
            return CommandResult(exit_code=0, stdout=render_json(records))
        if not records and (allowed_symbols is not None or broker_order_ids is not None):
            return CommandResult(
                exit_code=0,
                stdout=(
                    "No broker-side fill history matching filters: "
                    + _format_filter_summary(
                        status_filter=None,
                        symbol_filter=symbol_filter,
                        broker_order_id_filter=broker_order_id_filter,
                    )
                ),
            )
        return CommandResult(exit_code=0, stdout=render_broker_fill_history(records))
    except UnsupportedBrokerOperationError as exc:
        msg = f"Broker fill history is unavailable: {exc}"
        get_logger(__name__).error(msg)
        return CommandResult(exit_code=1, stderr=msg)
    except Exception as exc:
        msg = f"Failed to load broker-side fill history: {exc}"
        get_logger(__name__).error(msg)
        return CommandResult(exit_code=1, stderr=msg)
    finally:
        _close_broker_adapter(adapter)


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
        _close_broker_adapter(adapter)
