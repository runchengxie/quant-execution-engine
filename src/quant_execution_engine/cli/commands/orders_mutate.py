from __future__ import annotations

from ...broker import get_broker_adapter
from ...execution import OrderLifecycleService
from ...logging import get_logger
from ...renderers.jsonout import render_json
from ...renderers.table import (
    render_accept_partial_summary,
    render_bulk_cancel_summary,
    render_cancel_summary,
    render_order_trace,
    render_reprice_summary,
    render_resume_remaining_summary,
    render_retry_summary,
    render_stale_retry_summary,
    render_tracked_order_detail,
)
from .. import CommandResult
from ._common import _close_broker_adapter


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
        _close_broker_adapter(adapter)


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
        _close_broker_adapter(adapter)


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
        _close_broker_adapter(adapter)


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
        _close_broker_adapter(adapter)


def run_trace_order(
    *,
    order_ref: str,
    account: str = "main",
    broker: str | None = None,
    fmt: str = "table",
) -> CommandResult:
    adapter = None
    try:
        adapter = get_broker_adapter(broker_name=broker)
        service = OrderLifecycleService(adapter)
        trace = service.get_order_trace(account_label=account, order_ref=order_ref)
        if fmt == "json":
            return CommandResult(exit_code=0, stdout=render_json(trace))
        return CommandResult(exit_code=0, stdout=render_order_trace(trace))
    except Exception as exc:
        msg = f"Order trace failed: {exc}"
        get_logger(__name__).error(msg)
        return CommandResult(exit_code=1, stderr=msg)
    finally:
        _close_broker_adapter(adapter)


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
        _close_broker_adapter(adapter)


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
        _close_broker_adapter(adapter)


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
        _close_broker_adapter(adapter)


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
        _close_broker_adapter(adapter)


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
        _close_broker_adapter(adapter)
