# pyright: strict
"""Shared offline transport, fixtures, and assertions for recovery scenarios."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from .domain import (
    ExecutionEventType,
    Fill,
    InstrumentId,
    OrderEvent,
    OrderIntent,
    OrderSide,
    OrderStatus,
    OrderType,
)
from .execution_journal import (
    DurableExecutionJournal,
    IntentLifecycle,
    ReconciliationEvidence,
    SubmissionState,
)
from .paper_transport import InMemoryPaperExecutionTransport
from .recovery_matrix import (
    RecoveryMatrixInvariantError,
    RecoveryMatrixMode,
    RecoveryScenarioResult,
)
from .transport import (
    TransportOrderReference,
    TransportSubmission,
    TransportSubmitRequest,
)
from .transport_service import JournaledExecutionTransport

FAULT_NOW = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)
FAULT_PRICE = Decimal("100")
FAULT_QUANTITY = Decimal("10")

_STATE_RANK = {
    SubmissionState.RECORDED: 0,
    SubmissionState.SUBMISSION_UNCERTAIN: 1,
    SubmissionState.ACCEPTED: 2,
    SubmissionState.PARTIALLY_FILLED: 3,
    SubmissionState.CANCELLED: 4,
    SubmissionState.REJECTED: 4,
    SubmissionState.EXPIRED: 4,
    SubmissionState.FAILED: 4,
    SubmissionState.FILLED: 5,
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RecoveryMatrixInvariantError(message)


class FaultPaperTransport(InMemoryPaperExecutionTransport):
    """Count submits and optionally lose the response after local acceptance."""

    def __init__(self, *, backend_name: str, timeout_after_accept: bool = False) -> None:
        super().__init__(backend_name=backend_name)
        self.submit_calls = 0
        self._timeout_after_accept = timeout_after_accept

    def submit(self, request: TransportSubmitRequest) -> TransportSubmission:
        self.submit_calls += 1
        submission = super().submit(request)
        if self._timeout_after_accept and self.submit_calls == 1:
            raise TimeoutError(
                f"response lost after accepting {submission.reference.broker_order_id}"
            )
        return submission


@dataclass(slots=True)
class ScenarioContext:
    scenario_id: str
    transport: FaultPaperTransport
    journal: DurableExecutionJournal
    service: JournaledExecutionTransport
    intent: OrderIntent
    reference: TransportOrderReference
    state_history: list[SubmissionState]


def backend_name(mode: RecoveryMatrixMode) -> str:
    return f"recovery-{mode.value}-memory"


def make_intent(scenario_id: str, mode: RecoveryMatrixMode) -> OrderIntent:
    return OrderIntent(
        intent_id=f"recovery-{scenario_id}",
        instrument=InstrumentId(
            symbol="FAULT",
            market="TEST",
            exchange="SIM",
            currency="USD",
        ),
        side=OrderSide.BUY,
        quantity=FAULT_QUANTITY,
        order_type=OrderType.MARKET,
        created_at=FAULT_NOW,
        broker_name=backend_name(mode),
        account_label="recovery-matrix",
        run_id="execution-recovery-matrix-v1",
    )


def idempotency_key(scenario_id: str) -> str:
    return f"recovery-matrix/v1/{scenario_id}"


def journal_path(root: Path, scenario_id: str) -> Path:
    path = root / f"{scenario_id}.sqlite3"
    if path.exists():
        raise RecoveryMatrixInvariantError(f"scenario journal already exists: {path}")
    return path


def start_scenario(
    root: Path,
    scenario_id: str,
    mode: RecoveryMatrixMode,
) -> ScenarioContext:
    transport = FaultPaperTransport(backend_name=backend_name(mode))
    journal = DurableExecutionJournal(journal_path(root, scenario_id))
    service = JournaledExecutionTransport(transport, journal)
    intent = make_intent(scenario_id, mode)
    outcome = service.submit(
        intent,
        idempotency_key=idempotency_key(scenario_id),
        attempt_id=f"attempt-{scenario_id}",
        occurred_at=FAULT_NOW,
    )
    require(outcome.submitted, f"{scenario_id}: first submit was not executed")
    submission = outcome.submission
    if submission is None:
        raise RecoveryMatrixInvariantError(f"{scenario_id}: submission reference is missing")
    return ScenarioContext(
        scenario_id=scenario_id,
        transport=transport,
        journal=journal,
        service=service,
        intent=intent,
        reference=submission.reference,
        state_history=[outcome.lifecycle.submission_state],
    )


def block_duplicate(
    service: JournaledExecutionTransport,
    intent: OrderIntent,
    scenario_id: str,
) -> bool:
    duplicate = service.submit(
        intent,
        idempotency_key=idempotency_key(scenario_id),
        attempt_id=f"attempt-{scenario_id}-duplicate",
        occurred_at=FAULT_NOW + timedelta(minutes=30),
    )
    require(not duplicate.submitted, f"{scenario_id}: duplicate submit reached transport")
    require(
        not duplicate.preparation.should_submit,
        f"{scenario_id}: journal granted a second submit permit",
    )
    return True


def make_event(
    context: ScenarioContext,
    event_id: str,
    status: OrderStatus,
    *,
    seconds: int,
    filled: Decimal,
) -> OrderEvent:
    event_type = {
        OrderStatus.ACCEPTED: ExecutionEventType.ORDER_ACKNOWLEDGED,
        OrderStatus.PARTIALLY_FILLED: ExecutionEventType.PARTIALLY_FILLED,
        OrderStatus.FILLED: ExecutionEventType.FILLED,
        OrderStatus.CANCELLED: ExecutionEventType.CANCELLED,
    }.get(status, ExecutionEventType.ORDER_UPDATED)
    return OrderEvent(
        event_id=f"{context.scenario_id}-{event_id}",
        event_type=event_type,
        occurred_at=FAULT_NOW + timedelta(seconds=seconds),
        instrument=context.intent.instrument,
        status=status,
        broker_name=context.intent.broker_name or "unresolved",
        account_label=context.intent.account_label,
        broker_order_id=context.reference.broker_order_id or "unresolved",
        intent_id=context.intent.intent_id,
        client_order_id=context.reference.client_order_id,
        side=context.intent.side,
        quantity=context.intent.quantity,
        filled_quantity=filled,
        remaining_quantity=max(Decimal("0"), context.intent.quantity - filled),
        average_fill_price=FAULT_PRICE if filled > 0 else None,
        metadata={"source": "offline-recovery-fault-harness"},
    )


def make_fill(
    context: ScenarioContext,
    fill_id: str,
    *,
    seconds: int,
    quantity: Decimal,
) -> Fill:
    return Fill(
        fill_id=f"{context.scenario_id}-{fill_id}",
        broker_order_id=context.reference.broker_order_id or "unresolved",
        instrument=context.intent.instrument,
        quantity=quantity,
        price=FAULT_PRICE,
        filled_at=FAULT_NOW + timedelta(seconds=seconds),
        broker_name=context.intent.broker_name or "unresolved",
        account_label=context.intent.account_label,
        intent_id=context.intent.intent_id,
        side=context.intent.side,
        metadata={"source": "offline-recovery-fault-harness"},
    )


def make_evidence(
    context: ScenarioContext,
    evidence_id: str,
    status: OrderStatus,
    *,
    seconds: int,
    filled: Decimal,
    message: str,
    metadata: dict[str, object] | None = None,
) -> ReconciliationEvidence:
    return ReconciliationEvidence(
        evidence_id=f"{context.scenario_id}-{evidence_id}",
        intent_id=context.intent.intent_id,
        observed_at=FAULT_NOW + timedelta(seconds=seconds),
        source="offline-recovery-fault-harness",
        observed_status=status,
        broker_order_id=context.reference.broker_order_id,
        observed_filled_quantity=filled,
        observed_remaining_quantity=max(Decimal("0"), context.intent.quantity - filled),
        message=message,
        metadata=metadata or {},
    )


def _is_monotonic(states: list[SubmissionState]) -> bool:
    ranks = [_STATE_RANK[state] for state in states]
    return all(current <= following for current, following in zip(ranks, ranks[1:], strict=False))


def scenario_result(
    context: ScenarioContext,
    *,
    lifecycle: IntentLifecycle,
    idempotent_retry_blocked: bool,
    transport_submit_calls: int,
    reconciliation_status: str,
    reconciliation_result: str,
    action: str,
    kill_switch: bool = False,
    position_drift: Decimal | None = None,
) -> RecoveryScenarioResult:
    monotonic = _is_monotonic(context.state_history)
    require(monotonic, f"{context.scenario_id}: lifecycle regressed")
    require(
        lifecycle.submission_attempt_ids == (f"attempt-{context.scenario_id}",),
        f"{context.scenario_id}: submission attempt identity changed",
    )
    require(transport_submit_calls == 1, f"{context.scenario_id}: submit count is not one")
    require(idempotent_retry_blocked, f"{context.scenario_id}: retry was not blocked")
    state = context.journal.replay().intents[context.intent.intent_id]
    require(state == lifecycle, f"{context.scenario_id}: reported lifecycle is stale")
    return RecoveryScenarioResult(
        id=context.scenario_id,
        expected_state={
            "submission_state": lifecycle.submission_state.value,
            "order_status": lifecycle.order_status.value if lifecycle.order_status else None,
            "broker_order_id": lifecycle.broker_order_id,
            "filled_quantity": str(lifecycle.filled_quantity),
            "remaining_quantity": str(lifecycle.remaining_quantity),
            "submission_attempt_count": len(lifecycle.submission_attempt_ids),
            "order_event_count": len(lifecycle.order_event_ids),
            "fill_count": len(lifecycle.fills),
            "journal_sequence": context.journal.replay().through_sequence,
            "transport_submit_calls": transport_submit_calls,
            "idempotent_retry_blocked": idempotent_retry_blocked,
            "state_monotonic": monotonic,
        },
        reconciliation={
            "status": reconciliation_status,
            "result": reconciliation_result,
            "action": action,
            "evidence_count": len(lifecycle.reconciliation_evidence),
            "kill_switch": kill_switch,
            "position_drift": str(position_drift) if position_drift is not None else None,
        },
    )


__all__ = [
    "FAULT_NOW",
    "FAULT_PRICE",
    "FAULT_QUANTITY",
    "FaultPaperTransport",
    "ScenarioContext",
    "backend_name",
    "block_duplicate",
    "idempotency_key",
    "journal_path",
    "make_evidence",
    "make_event",
    "make_fill",
    "make_intent",
    "require",
    "scenario_result",
    "start_scenario",
]
