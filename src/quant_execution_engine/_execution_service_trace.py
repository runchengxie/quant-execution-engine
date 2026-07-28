"""Order trace and exception-record queries for :class:`OrderLifecycleService`.

These functions are the implementation behind ``OrderLifecycleService``'s
trace / exception-reader methods. They receive the service instance so the
public method signatures and behaviour stay identical to the original
in-class implementations.
"""

from __future__ import annotations

from .broker.base import (
    BrokerFillRecord,
    BrokerOrderRecord,
    ResolvedBrokerAccount,
    UnsupportedBrokerOperationError,
)
from .execution_helpers import resolve_tracked_order_context
from .execution_state import (
    DEFAULT_EXCEPTION_STATUSES,
    ExecutionExceptionRecord,
    ExecutionOrderTrace,
)
from .logging import get_logger

logger = get_logger(__name__)


def get_order_trace(
    service,
    *,
    account_label: str,
    order_ref: str,
) -> ExecutionOrderTrace:
    """Return a merged local and broker-side trace for one tracked order."""

    context = resolve_tracked_order_context(
        service.adapter,
        service.state_store,
        account_label,
        order_ref,
    )
    account = context.account
    state = context.state
    child = context.child
    parent = context.parent
    intent = context.intent
    broker_order = context.broker_order

    if parent is not None:
        child_orders = sorted(
            [
                candidate
                for candidate in state.child_orders
                if candidate.parent_order_id == parent.parent_order_id
            ],
            key=lambda candidate: (
                candidate.attempt,
                candidate.created_at,
                candidate.updated_at,
                candidate.child_order_id,
            ),
        )
    elif child is not None:
        child_orders = [child]
    else:
        child_orders = []

    broker_order_ids: list[str] = []
    for candidate in child_orders:
        if candidate.broker_order_id and candidate.broker_order_id not in broker_order_ids:
            broker_order_ids.append(candidate.broker_order_id)
    if (
        broker_order is not None
        and broker_order.broker_order_id
        and broker_order.broker_order_id not in broker_order_ids
    ):
        broker_order_ids.append(broker_order.broker_order_id)

    tracked_broker_orders = sorted(
        [record for record in state.broker_orders if record.broker_order_id in broker_order_ids],
        key=lambda record: (
            record.submitted_at,
            record.updated_at,
            record.broker_order_id,
        ),
    )

    if parent is not None:
        fill_events = sorted(
            [fill for fill in state.fill_events if fill.parent_order_id == parent.parent_order_id],
            key=lambda fill: (fill.filled_at, fill.fill_id),
        )
    else:
        fill_events = sorted(
            [fill for fill in state.fill_events if fill.broker_order_id in broker_order_ids],
            key=lambda fill: (fill.filled_at, fill.fill_id),
        )

    broker_history_orders, broker_history_fills, warnings = _load_broker_history_trace(
        service,
        account=account,
        broker_order_ids=broker_order_ids,
    )

    state_path = service.state_store.path_for(service.adapter.backend_name, account.label)
    return ExecutionOrderTrace(
        broker_name=service.adapter.backend_name,
        account_label=account.label,
        order_ref=order_ref,
        state_path=state_path,
        intent=intent,
        parent=parent,
        child=child,
        broker_order=broker_order,
        child_orders=child_orders,
        tracked_broker_orders=tracked_broker_orders,
        fill_events=fill_events,
        broker_history_orders=broker_history_orders,
        broker_history_fills=broker_history_fills,
        warnings=warnings,
    )


def list_exception_orders(
    service,
    *,
    account_label: str,
    statuses: set[str] | None = None,
) -> list[ExecutionExceptionRecord]:
    """Return local exception records for tracked orders."""

    account = service.adapter.resolve_account(account_label)
    state = service.state_store.load(service.adapter.backend_name, account.label)
    normalized_statuses = {
        str(status).strip().upper()
        for status in (statuses or DEFAULT_EXCEPTION_STATUSES)
        if str(status).strip()
    }
    broker_orders_by_id = {
        broker_order.broker_order_id: broker_order
        for broker_order in state.broker_orders
        if broker_order.broker_order_id
    }
    results: list[ExecutionExceptionRecord] = []

    for parent in state.parent_orders:
        children = [
            child for child in state.child_orders if child.parent_order_id == parent.parent_order_id
        ]
        if not children:
            continue
        latest_child = sorted(children, key=lambda child: child.attempt)[-1]
        broker_order = (
            broker_orders_by_id.get(latest_child.broker_order_id)
            if latest_child.broker_order_id
            else None
        )
        status = broker_order.status if broker_order is not None else latest_child.status
        if status not in normalized_statuses:
            continue
        results.append(
            ExecutionExceptionRecord(
                broker_name=service.adapter.backend_name,
                account_label=account.label,
                symbol=parent.symbol,
                side=parent.side,
                status=status,
                parent_order_id=parent.parent_order_id,
                child_order_id=latest_child.child_order_id,
                broker_order_id=broker_order.broker_order_id if broker_order is not None else None,
                client_order_id=broker_order.client_order_id
                if broker_order is not None
                else latest_child.client_order_id,
                source="broker" if broker_order is not None else "local",
                message=broker_order.message if broker_order is not None else latest_child.message,
                filled_quantity=(
                    float(broker_order.filled_quantity or 0.0)
                    if broker_order is not None
                    else float(parent.filled_quantity or 0.0)
                ),
                remaining_quantity=(
                    broker_order.remaining_quantity
                    if broker_order is not None
                    else float(parent.remaining_quantity or 0.0)
                ),
                updated_at=(
                    broker_order.updated_at if broker_order is not None else latest_child.updated_at
                ),
            )
        )

    return sorted(
        results,
        key=lambda item: (item.updated_at or "", item.parent_order_id),
        reverse=True,
    )


def _load_broker_history_trace(
    service,
    *,
    account: ResolvedBrokerAccount,
    broker_order_ids: list[str],
) -> tuple[list[BrokerOrderRecord], list[BrokerFillRecord], list[str]]:
    warnings: list[str] = []
    broker_history_orders: list[BrokerOrderRecord] = []
    broker_history_fills: list[BrokerFillRecord] = []
    if not broker_order_ids:
        return broker_history_orders, broker_history_fills, warnings

    if service.adapter.capabilities.supports_order_history:
        for broker_order_id in broker_order_ids:
            try:
                broker_history_orders.extend(
                    service.adapter.list_order_history(account, broker_order_id=broker_order_id)
                )
            except UnsupportedBrokerOperationError as exc:
                warnings.append(f"broker-side order history unavailable: {exc}")
                break
            except Exception as exc:
                warnings.append(
                    f"failed to load broker-side order history for {broker_order_id}: {exc}"
                )
    else:
        warnings.append(
            f"{service.adapter.backend_name} does not support broker-side order history"
        )

    if service.adapter.capabilities.supports_fill_history:
        for broker_order_id in broker_order_ids:
            try:
                broker_history_fills.extend(
                    service.adapter.list_fill_history(account, broker_order_id=broker_order_id)
                )
            except UnsupportedBrokerOperationError as exc:
                warnings.append(f"broker-side fill history unavailable: {exc}")
                break
            except Exception as exc:
                warnings.append(
                    f"failed to load broker-side fill history for {broker_order_id}: {exc}"
                )
    else:
        warnings.append(f"{service.adapter.backend_name} does not support broker-side fill history")

    unique_orders: dict[str, BrokerOrderRecord] = {}
    for order_record in broker_history_orders:
        unique_orders[order_record.broker_order_id] = order_record
    unique_fills: dict[str, BrokerFillRecord] = {}
    for fill_record in broker_history_fills:
        unique_fills[fill_record.fill_id] = fill_record

    return (
        sorted(
            unique_orders.values(),
            key=lambda record: (
                record.submitted_at,
                record.updated_at,
                record.broker_order_id,
            ),
        ),
        sorted(
            unique_fills.values(),
            key=lambda record: (
                record.filled_at,
                record.broker_order_id,
                record.fill_id,
            ),
        ),
        warnings,
    )
