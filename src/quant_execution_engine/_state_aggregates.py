"""Parent-aggregate derivation and state indexing helpers.

Shared by ``doctor`` and ``repair``: building indexes over an
:class:`ExecutionState` and deriving the expected parent aggregate (filled /
remaining / status) from the underlying child and fill state.
"""

from __future__ import annotations

from dataclasses import dataclass

from .broker.base import BrokerOrderRecord, utc_now_iso
from .execution import OPEN_BROKER_STATUSES, ExecutionState
from .execution_state import ChildOrder, OrderIntent, ParentOrder


@dataclass(slots=True)
class _ExpectedParentAggregate:
    filled_quantity: float
    remaining_quantity: float
    status: str


def _latest_child_status(
    *,
    parent: ParentOrder,
    child_orders: list[ChildOrder],
    broker_orders_by_id: dict[str, BrokerOrderRecord],
) -> str:
    latest_child = max(
        child_orders,
        key=lambda child: (
            child.attempt,
            child.updated_at or "",
            child.created_at or "",
            child.child_order_id,
        ),
        default=None,
    )
    if latest_child is None:
        return parent.status
    if latest_child.broker_order_id and latest_child.broker_order_id in broker_orders_by_id:
        return str(broker_orders_by_id[latest_child.broker_order_id].status)
    return str(latest_child.status)


def _derive_parent_aggregate(
    *,
    state: ExecutionState,
    parent: ParentOrder,
    child_orders: list[ChildOrder],
    broker_orders_by_id: dict[str, BrokerOrderRecord],
) -> _ExpectedParentAggregate:
    child_broker_order_ids = {
        child.broker_order_id for child in child_orders if child.broker_order_id
    }
    fill_quantity_by_broker_order: dict[str, float] = {}
    unmatched_parent_fill_quantity = 0.0
    for fill in state.fill_events:
        if fill.parent_order_id != parent.parent_order_id:
            continue
        if fill.broker_order_id in child_broker_order_ids:
            fill_quantity_by_broker_order[fill.broker_order_id] = fill_quantity_by_broker_order.get(
                fill.broker_order_id, 0.0
            ) + float(fill.quantity or 0.0)
        else:
            unmatched_parent_fill_quantity += float(fill.quantity or 0.0)

    total_filled_quantity = float(unmatched_parent_fill_quantity)
    has_open_child = False
    for child in child_orders:
        broker_order = (
            broker_orders_by_id.get(child.broker_order_id) if child.broker_order_id else None
        )
        child_status = (
            str(broker_order.status) if broker_order is not None else str(child.status or "")
        ).upper()
        if child_status in OPEN_BROKER_STATUSES:
            has_open_child = True
        broker_filled_quantity = (
            float(broker_order.filled_quantity or 0.0) if broker_order is not None else 0.0
        )
        fill_filled_quantity = (
            float(fill_quantity_by_broker_order.get(child.broker_order_id, 0.0))
            if child.broker_order_id
            else 0.0
        )
        total_filled_quantity += max(broker_filled_quantity, fill_filled_quantity)

    requested_quantity = float(parent.requested_quantity or 0.0)
    remaining_quantity = max(0.0, requested_quantity - total_filled_quantity)
    manual_resolution = str(parent.metadata.get("manual_resolution") or "").strip().lower()
    latest_status = _latest_child_status(
        parent=parent,
        child_orders=child_orders,
        broker_orders_by_id=broker_orders_by_id,
    )
    if manual_resolution == "accepted_partial":
        status = "ACCEPTED_PARTIAL"
    elif requested_quantity > 0 and total_filled_quantity >= requested_quantity:
        status = "FILLED"
    elif total_filled_quantity > 0:
        status = "PARTIALLY_FILLED"
    elif has_open_child:
        status = "PENDING"
    else:
        status = latest_status or parent.status
    return _ExpectedParentAggregate(
        filled_quantity=float(total_filled_quantity),
        remaining_quantity=float(remaining_quantity),
        status=str(status),
    )


def _parent_aggregate_mismatch(
    parent: ParentOrder,
    expected: _ExpectedParentAggregate,
) -> bool:
    return (
        abs(float(parent.filled_quantity or 0.0) - expected.filled_quantity) > 1e-9
        or abs(float(parent.remaining_quantity or 0.0) - expected.remaining_quantity) > 1e-9
        or str(parent.status) != expected.status
    )


@dataclass(slots=True)
class _StateIndexes:
    parents_by_id: dict[str, ParentOrder]
    intents_by_id: dict[str, OrderIntent]
    child_records_by_parent: dict[str, list[ChildOrder]]
    referenced_broker_order_ids: set[str]
    broker_orders_by_id: dict[str, BrokerOrderRecord]


def _build_state_indexes(state: ExecutionState) -> _StateIndexes:
    child_records_by_parent: dict[str, list[ChildOrder]] = {}
    referenced_broker_order_ids: set[str] = set()
    for child in state.child_orders:
        child_records_by_parent.setdefault(child.parent_order_id, []).append(child)
        if child.broker_order_id:
            referenced_broker_order_ids.add(child.broker_order_id)
    return _StateIndexes(
        parents_by_id={parent.parent_order_id: parent for parent in state.parent_orders},
        intents_by_id={intent.intent_id: intent for intent in state.intents},
        child_records_by_parent=child_records_by_parent,
        referenced_broker_order_ids=referenced_broker_order_ids,
        broker_orders_by_id={
            broker_order.broker_order_id: broker_order for broker_order in state.broker_orders
        },
    )


def _recompute_parent_aggregates(state: ExecutionState) -> int:
    indexes = _build_state_indexes(state)
    repaired = 0
    for parent in state.parent_orders:
        expected = _derive_parent_aggregate(
            state=state,
            parent=parent,
            child_orders=indexes.child_records_by_parent.get(parent.parent_order_id, []),
            broker_orders_by_id=indexes.broker_orders_by_id,
        )
        if not _parent_aggregate_mismatch(parent, expected):
            continue
        parent.filled_quantity = expected.filled_quantity
        parent.remaining_quantity = expected.remaining_quantity
        parent.status = expected.status
        parent.updated_at = utc_now_iso()
        repaired += 1
    return repaired
