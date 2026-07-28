"""Prune-plan building and orphan/dedupe mutations used by repair."""

from __future__ import annotations

from dataclasses import dataclass

from ._state_models import TERMINAL_PARENT_STATUSES, _parse_timestamp
from .execution import TERMINAL_BROKER_STATUSES, ExecutionState


@dataclass(slots=True)
class _PrunePlan:
    parent_order_ids: set[str]
    child_order_ids: set[str]
    broker_order_ids: set[str]
    fill_ids: set[str]
    intent_ids: set[str]
    child_count: int


def _build_prune_plan(state: ExecutionState, cutoff) -> _PrunePlan:
    from datetime import datetime, timezone

    prunable_parent_ids = {
        parent.parent_order_id
        for parent in state.parent_orders
        if parent.status in TERMINAL_PARENT_STATUSES
        and (_parse_timestamp(parent.updated_at) or datetime.min.replace(tzinfo=timezone.utc))
        <= cutoff
    }
    prunable_children = [
        child for child in state.child_orders if child.parent_order_id in prunable_parent_ids
    ]
    prunable_broker_order_ids = {
        child.broker_order_id for child in prunable_children if child.broker_order_id
    }
    remaining_parent_intents = {
        parent.intent_id
        for parent in state.parent_orders
        if parent.parent_order_id not in prunable_parent_ids
    }
    return _PrunePlan(
        parent_order_ids=prunable_parent_ids,
        child_order_ids={child.child_order_id for child in prunable_children},
        broker_order_ids=prunable_broker_order_ids,
        fill_ids={
            fill.fill_id
            for fill in state.fill_events
            if fill.parent_order_id in prunable_parent_ids
            or fill.broker_order_id in prunable_broker_order_ids
        },
        intent_ids={
            parent.intent_id
            for parent in state.parent_orders
            if parent.parent_order_id in prunable_parent_ids
            and parent.intent_id not in remaining_parent_intents
        },
        child_count=len(prunable_children),
    )


def _dedupe_fill_events(state: ExecutionState) -> int:
    seen: set[str] = set()
    deduped = []
    removed = 0
    for fill in state.fill_events:
        if fill.fill_id in seen:
            removed += 1
            continue
        seen.add(fill.fill_id)
        deduped.append(fill)
    state.fill_events = deduped
    return removed


def _drop_orphan_fill_events(state: ExecutionState) -> int:
    parent_order_ids = {parent.parent_order_id for parent in state.parent_orders}
    broker_order_ids = {
        child.broker_order_id for child in state.child_orders if child.broker_order_id
    }
    kept = []
    removed = 0
    for fill in state.fill_events:
        if fill.parent_order_id in parent_order_ids or fill.broker_order_id in broker_order_ids:
            kept.append(fill)
            continue
        removed += 1
    state.fill_events = kept
    return removed


def _drop_orphan_terminal_broker_orders(state: ExecutionState) -> int:
    referenced = {child.broker_order_id for child in state.child_orders if child.broker_order_id}
    kept = []
    removed = 0
    for broker_order in state.broker_orders:
        if (
            broker_order.broker_order_id not in referenced
            and broker_order.status in TERMINAL_BROKER_STATUSES
        ):
            removed += 1
            continue
        kept.append(broker_order)
    state.broker_orders = kept
    return removed
