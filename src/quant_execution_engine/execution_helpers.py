"""Pure-ish helper functions shared by the execution lifecycle service."""

from __future__ import annotations

from collections import Counter
from typing import Any

from .broker.base import BrokerOrderRecord
from .execution_state import (
    ChildOrder,
    ExecutionFillEvent,
    ExecutionReconcileDelta,
    ExecutionState,
    OrderIntent,
    ParentOrder,
)

TrackedOrderResolution = tuple[
    ChildOrder | None,
    ParentOrder | None,
    OrderIntent | None,
    BrokerOrderRecord | None,
]


def build_reconcile_deltas(
    *,
    before_orders: dict[str, BrokerOrderRecord],
    after_orders: list[BrokerOrderRecord],
    before_fill_counts: Counter[str],
    fill_events: list[ExecutionFillEvent],
) -> list[ExecutionReconcileDelta]:
    after_fill_counts = Counter(fill.broker_order_id for fill in fill_events if fill.broker_order_id)
    deltas: list[ExecutionReconcileDelta] = []
    for after in sorted(after_orders, key=lambda item: item.broker_order_id):
        before = before_orders.get(after.broker_order_id)
        new_fill_events = max(
            0,
            int(after_fill_counts.get(after.broker_order_id, 0))
            - int(before_fill_counts.get(after.broker_order_id, 0)),
        )
        before_status = before.status if before is not None else None
        before_filled = float(before.filled_quantity or 0.0) if before is not None else 0.0
        after_filled = float(after.filled_quantity or 0.0)
        if (
            before is None
            or before_status != after.status
            or abs(before_filled - after_filled) > 0.0
            or new_fill_events > 0
        ):
            deltas.append(
                ExecutionReconcileDelta(
                    broker_order_id=after.broker_order_id,
                    symbol=after.symbol,
                    before_status=before_status,
                    after_status=after.status,
                    before_filled_quantity=before_filled,
                    after_filled_quantity=after_filled,
                    new_fill_events=new_fill_events,
                )
            )
    return deltas


def find_parent_for_child(
    state: ExecutionState,
    child: ChildOrder | None,
) -> ParentOrder | None:
    if child is None:
        return None
    return next(
        (
            parent
            for parent in state.parent_orders
            if parent.parent_order_id == child.parent_order_id
        ),
        None,
    )


def find_intent_for_parent(
    state: ExecutionState,
    parent: ParentOrder | None,
) -> OrderIntent | None:
    if parent is None:
        return None
    return next(
        (
            intent
            for intent in state.intents
            if intent.intent_id == parent.intent_id
        ),
        None,
    )


def resolve_tracked_order(
    state: ExecutionState,
    order_ref: str,
) -> TrackedOrderResolution | None:
    normalized = str(order_ref).strip()
    if not normalized:
        return None

    child = next(
        (
            candidate
            for candidate in state.child_orders
            if candidate.child_order_id == normalized
        ),
        None,
    )
    for broker_order in state.broker_orders:
        if broker_order.broker_order_id == normalized:
            child = child or next(
                (
                    candidate
                    for candidate in state.child_orders
                    if candidate.broker_order_id == broker_order.broker_order_id
                ),
                None,
            )
            parent = find_parent_for_child(state, child)
            intent = find_intent_for_parent(state, parent)
            return child, parent, intent, broker_order
        if broker_order.client_order_id == normalized:
            child = child or next(
                (
                    candidate
                    for candidate in state.child_orders
                    if candidate.broker_order_id == broker_order.broker_order_id
                    or candidate.child_order_id == broker_order.client_order_id
                ),
                None,
            )
            parent = find_parent_for_child(state, child)
            intent = find_intent_for_parent(state, parent)
            return child, parent, intent, broker_order

    if child is None:
        return None
    parent = find_parent_for_child(state, child)
    intent = find_intent_for_parent(state, parent)
    broker_order = None
    if child.broker_order_id:
        broker_order = next(
            (
                existing
                for existing in state.broker_orders
                if existing.broker_order_id == child.broker_order_id
            ),
            None,
        )
    return child, parent, intent, broker_order


def find_tracked_broker_order(
    state: ExecutionState,
    order_ref: str,
) -> BrokerOrderRecord | None:
    resolved = resolve_tracked_order(state, order_ref)
    if resolved is None:
        return None
    return resolved[3]


def find_parent_for_fill(
    state: ExecutionState,
    fill: Any,
) -> ParentOrder | None:
    matching_child = next(
        (
            child
            for child in state.child_orders
            if child.broker_order_id == fill.broker_order_id
        ),
        None,
    )
    if matching_child is not None:
        return next(
            (
                parent
                for parent in state.parent_orders
                if parent.parent_order_id == matching_child.parent_order_id
            ),
            None,
        )
    return next(
        (
            parent
            for parent in state.parent_orders
            if parent.symbol == fill.symbol and parent.status not in {"FILLED", "CANCELED"}
        ),
        None,
    )


__all__ = [
    "TrackedOrderResolution",
    "build_reconcile_deltas",
    "find_intent_for_parent",
    "find_parent_for_child",
    "find_parent_for_fill",
    "find_tracked_broker_order",
    "resolve_tracked_order",
]
