# pyright: strict
"""Pure, deterministic reduction of durable execution journal records."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from ._journal_codec import (
    evidence_from_payload,
    fill_from_payload,
    intent_from_payload,
    order_event_from_payload,
    submission_from_payload,
)
from ._journal_domain import (
    ExecutionJournalState,
    IntentLifecycle,
    JournalEntry,
    JournalEventKind,
    JournalInvariantError,
    ReconciliationEvidence,
    SubmissionState,
)
from .domain import Fill, OrderEvent, OrderStatus

_ACCEPTED_STATUSES = frozenset(
    {
        OrderStatus.PENDING,
        OrderStatus.NEW,
        OrderStatus.ACCEPTED,
        OrderStatus.PENDING_NEW,
        OrderStatus.PENDING_REPLACE,
        OrderStatus.WAIT_TO_NEW,
        OrderStatus.WAIT_TO_CANCEL,
        OrderStatus.PENDING_CANCEL,
    }
)
_FAILED_STATUSES = frozenset({OrderStatus.BLOCKED, OrderStatus.FAILED})


def _candidate_state(status: OrderStatus) -> SubmissionState | None:
    if status in _ACCEPTED_STATUSES:
        return SubmissionState.ACCEPTED
    if status is OrderStatus.PARTIALLY_FILLED:
        return SubmissionState.PARTIALLY_FILLED
    if status in {OrderStatus.FILLED, OrderStatus.SUCCESS}:
        return SubmissionState.FILLED
    if status is OrderStatus.CANCELLED:
        return SubmissionState.CANCELLED
    if status is OrderStatus.REJECTED:
        return SubmissionState.REJECTED
    if status is OrderStatus.EXPIRED:
        return SubmissionState.EXPIRED
    if status in _FAILED_STATUSES:
        return SubmissionState.FAILED
    return None


def _merge_broker_order_id(current: str | None, observed: str | None) -> str | None:
    if observed is None:
        return current
    if current is not None and current != observed:
        raise JournalInvariantError(
            f"one intent resolved to multiple broker order IDs: {current!r}, {observed!r}"
        )
    return observed


def _merge_status(
    lifecycle: IntentLifecycle,
    status: OrderStatus,
    observed_filled: Decimal | None,
    average_fill_price: Decimal | None,
    broker_order_id: str | None,
) -> IntentLifecycle:
    requested = lifecycle.intent.quantity
    filled = lifecycle.filled_quantity
    if observed_filled is not None:
        filled = max(filled, observed_filled)
    candidate = _candidate_state(status)
    if candidate is SubmissionState.FILLED:
        filled = max(filled, requested)

    previous = lifecycle.submission_state
    next_state: SubmissionState
    next_status: OrderStatus | None
    if filled >= requested:
        next_state = SubmissionState.FILLED
        next_status = OrderStatus.FILLED
        filled = max(filled, requested)
    elif previous is SubmissionState.FILLED:
        next_state = previous
        next_status = OrderStatus.FILLED
    elif lifecycle.is_terminal:
        # A terminal broker fact cannot be regressed by a stale open callback.
        next_state = previous
        next_status = lifecycle.order_status
    elif candidate is None:
        next_state = previous
        next_status = lifecycle.order_status
    elif previous is SubmissionState.PARTIALLY_FILLED and candidate is SubmissionState.ACCEPTED:
        next_state = previous
        next_status = OrderStatus.PARTIALLY_FILLED
    else:
        next_state = candidate
        next_status = status

    if filled > 0 and next_state in {
        SubmissionState.RECORDED,
        SubmissionState.SUBMISSION_UNCERTAIN,
        SubmissionState.ACCEPTED,
    }:
        next_state = SubmissionState.PARTIALLY_FILLED
        next_status = OrderStatus.PARTIALLY_FILLED

    remaining = max(requested - filled, Decimal("0"))
    price = lifecycle.average_fill_price
    if (
        average_fill_price is not None
        and observed_filled is not None
        and observed_filled >= lifecycle.filled_quantity
    ):
        price = average_fill_price
    return replace(
        lifecycle,
        submission_state=next_state,
        order_status=next_status,
        broker_order_id=_merge_broker_order_id(
            lifecycle.broker_order_id,
            broker_order_id,
        ),
        filled_quantity=filled,
        remaining_quantity=remaining,
        average_fill_price=price,
    )


def _apply_order_event(lifecycle: IntentLifecycle, event: OrderEvent) -> IntentLifecycle:
    if event.intent_id != lifecycle.intent.intent_id:
        raise JournalInvariantError("order event intent_id does not match its journal stream")
    updated = _merge_status(
        lifecycle,
        event.status,
        event.filled_quantity,
        event.average_fill_price,
        event.broker_order_id,
    )
    return replace(updated, order_event_ids=(*updated.order_event_ids, event.event_id))


def _weighted_fill_price(fills: tuple[Fill, ...]) -> Decimal | None:
    total_quantity = sum((fill.quantity for fill in fills), Decimal("0"))
    if total_quantity == 0:
        return None
    total_notional = sum((fill.quantity * fill.price for fill in fills), Decimal("0"))
    return total_notional / total_quantity


def _apply_fill(lifecycle: IntentLifecycle, fill: Fill) -> IntentLifecycle:
    if fill.intent_id != lifecycle.intent.intent_id:
        raise JournalInvariantError("fill intent_id does not match its journal stream")
    broker_order_id = _merge_broker_order_id(
        lifecycle.broker_order_id,
        fill.broker_order_id,
    )
    fills = (*lifecycle.fills, fill)
    cumulative_fills = sum((item.quantity for item in fills), Decimal("0"))
    updated = _merge_status(
        lifecycle,
        OrderStatus.FILLED
        if cumulative_fills >= lifecycle.intent.quantity
        else OrderStatus.PARTIALLY_FILLED,
        cumulative_fills,
        _weighted_fill_price(fills),
        broker_order_id,
    )
    return replace(updated, fills=fills)


def _apply_reconciliation(
    lifecycle: IntentLifecycle,
    evidence: ReconciliationEvidence,
) -> IntentLifecycle:
    if evidence.intent_id != lifecycle.intent.intent_id:
        raise JournalInvariantError("reconciliation intent_id does not match its journal stream")
    updated = _merge_status(
        lifecycle,
        evidence.observed_status,
        evidence.observed_filled_quantity,
        None,
        evidence.broker_order_id,
    )
    return replace(
        updated,
        reconciliation_evidence=(*updated.reconciliation_evidence, evidence),
    )


def reduce_entry(state: ExecutionJournalState, entry: JournalEntry) -> ExecutionJournalState:
    """Apply one verified entry without mutating the prior state."""

    if entry.sequence != state.through_sequence + 1:
        raise JournalInvariantError(
            f"journal sequence gap: expected {state.through_sequence + 1}, got {entry.sequence}"
        )
    intents = dict(state.intents)
    lifecycle = intents.get(entry.intent_id)

    if entry.kind is JournalEventKind.INTENT_RECORDED:
        if lifecycle is not None:
            raise JournalInvariantError(f"intent {entry.intent_id!r} was recorded twice")
        intent, idempotency_key = intent_from_payload(entry.payload_json)
        if intent.intent_id != entry.intent_id:
            raise JournalInvariantError("intent payload ID does not match its journal stream")
        lifecycle = IntentLifecycle(
            intent=intent,
            idempotency_key=idempotency_key,
            remaining_quantity=intent.quantity,
            last_sequence=entry.sequence,
        )
    else:
        if lifecycle is None:
            raise JournalInvariantError(
                f"journal record {entry.record_id!r} references an unknown intent"
            )
        if entry.kind is JournalEventKind.SUBMISSION_STARTED:
            attempt_id, _ = submission_from_payload(entry.payload_json)
            if lifecycle.submission_attempt_ids:
                raise JournalInvariantError("an intent has more than one submission attempt")
            lifecycle = replace(
                lifecycle,
                submission_state=SubmissionState.SUBMISSION_UNCERTAIN,
                submission_attempt_ids=(attempt_id,),
            )
        elif entry.kind is JournalEventKind.SUBMISSION_UNCERTAIN:
            attempt_id, message = submission_from_payload(entry.payload_json)
            if attempt_id not in lifecycle.submission_attempt_ids:
                raise JournalInvariantError("uncertainty references an unknown submission attempt")
            messages = lifecycle.uncertainty_messages
            if message is not None:
                messages = (*messages, message)
            lifecycle = replace(lifecycle, uncertainty_messages=messages)
        elif entry.kind is JournalEventKind.ORDER_EVENT_RECORDED:
            lifecycle = _apply_order_event(
                lifecycle,
                order_event_from_payload(entry.payload_json),
            )
        elif entry.kind is JournalEventKind.FILL_RECORDED:
            lifecycle = _apply_fill(lifecycle, fill_from_payload(entry.payload_json))
        elif entry.kind is JournalEventKind.RECONCILIATION_RECORDED:
            lifecycle = _apply_reconciliation(
                lifecycle,
                evidence_from_payload(entry.payload_json),
            )
        lifecycle = replace(lifecycle, last_sequence=entry.sequence)

    intents[entry.intent_id] = lifecycle
    return ExecutionJournalState(through_sequence=entry.sequence, intents=intents)


def replay_entries(
    entries: tuple[JournalEntry, ...],
    initial_state: ExecutionJournalState | None = None,
) -> ExecutionJournalState:
    """Replay verified records from an optional materialized checkpoint."""

    state = initial_state or ExecutionJournalState()
    for entry in entries:
        state = reduce_entry(state, entry)
    return state
