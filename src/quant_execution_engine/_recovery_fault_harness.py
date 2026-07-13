# pyright: strict
"""Offline, deterministic fault scenarios for execution recovery evidence."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from ._recovery_fault_support import (
    FAULT_NOW,
    FAULT_PRICE,
    FAULT_QUANTITY,
    FaultPaperTransport,
    ScenarioContext,
    backend_name,
    block_duplicate,
    idempotency_key,
    journal_path,
    make_event,
    make_evidence,
    make_fill,
    make_intent,
    require,
    scenario_result,
    start_scenario,
)
from .domain import OrderStatus
from .execution_journal import DurableExecutionJournal, SubmissionState
from .recovery_matrix import (
    RECOVERY_SCENARIO_IDS,
    RecoveryMatrixInvariantError,
    RecoveryMatrixMode,
    RecoveryScenarioResult,
)
from .transport import (
    SubmissionOutcomeUnknownError,
    TransportOrderReference,
)
from .transport_service import JournaledExecutionTransport


def _accepted_but_timeout(root: Path, mode: RecoveryMatrixMode) -> RecoveryScenarioResult:
    scenario_id = "accepted_but_timeout"
    transport = FaultPaperTransport(
        backend_name=backend_name(mode),
        timeout_after_accept=True,
    )
    journal = DurableExecutionJournal(journal_path(root, scenario_id))
    service = JournaledExecutionTransport(transport, journal)
    intent = make_intent(scenario_id, mode)
    try:
        service.submit(
            intent,
            idempotency_key=idempotency_key(scenario_id),
            attempt_id=f"attempt-{scenario_id}",
            occurred_at=FAULT_NOW,
        )
    except SubmissionOutcomeUnknownError:
        pass
    else:  # pragma: no cover - an invariant guard, exercised by fault configuration
        raise RecoveryMatrixInvariantError("accepted_but_timeout: timeout was not injected")
    uncertain = journal.replay().intents[intent.intent_id]
    require(uncertain.requires_reconciliation, "accepted_but_timeout: state is not uncertain")
    retry_blocked = block_duplicate(service, intent, scenario_id)
    reference = TransportOrderReference.from_intent(intent)
    resolved = service.query_and_record(reference)
    actual_reference = TransportOrderReference(
        intent_id=intent.intent_id,
        instrument=intent.instrument,
        account_label=intent.account_label,
        broker_order_id=resolved.broker_order_id,
        client_order_id=intent.intent_id,
        side=intent.side,
        quantity=intent.quantity,
    )
    context = ScenarioContext(
        scenario_id=scenario_id,
        transport=transport,
        journal=journal,
        service=service,
        intent=intent,
        reference=actual_reference,
        state_history=[uncertain.submission_state, resolved.submission_state],
    )
    journal.append_reconciliation_evidence(
        make_evidence(
            context,
            "broker-order-found",
            OrderStatus.ACCEPTED,
            seconds=5,
            filled=Decimal("0"),
            message="broker query found the order accepted before response timeout",
        )
    )
    lifecycle = journal.replay().intents[intent.intent_id]
    context.state_history.append(lifecycle.submission_state)
    return scenario_result(
        context,
        lifecycle=lifecycle,
        idempotent_retry_blocked=retry_blocked,
        transport_submit_calls=transport.submit_calls,
        reconciliation_status="resolved",
        reconciliation_result="broker_order_found_after_timeout",
        action="continue_callback_polling",
    )


def _duplicate_submission(root: Path, mode: RecoveryMatrixMode) -> RecoveryScenarioResult:
    context = start_scenario(root, "duplicate_submission", mode)
    retry_blocked = block_duplicate(context.service, context.intent, context.scenario_id)
    lifecycle = context.journal.replay().intents[context.intent.intent_id]
    context.state_history.append(lifecycle.submission_state)
    return scenario_result(
        context,
        lifecycle=lifecycle,
        idempotent_retry_blocked=retry_blocked,
        transport_submit_calls=context.transport.submit_calls,
        reconciliation_status="resolved",
        reconciliation_result="durable_idempotency_reused",
        action="continue_callback_polling",
    )


def _duplicate_callback(root: Path, mode: RecoveryMatrixMode) -> RecoveryScenarioResult:
    context = start_scenario(root, "duplicate_callback", mode)
    event = make_event(
        context,
        "partial",
        OrderStatus.PARTIALLY_FILLED,
        seconds=4,
        filled=Decimal("4"),
    )
    fill = make_fill(context, "fill-001", seconds=4, quantity=Decimal("4"))
    first_event = context.journal.append_order_event(event)
    duplicate_event = context.journal.append_order_event(event)
    context.state_history.append(
        context.journal.replay().intents[context.intent.intent_id].submission_state
    )
    first_fill = context.journal.append_fill(fill)
    duplicate_fill = context.journal.append_fill(fill)
    lifecycle = context.journal.replay().intents[context.intent.intent_id]
    context.state_history.append(lifecycle.submission_state)
    require(first_event.appended and first_fill.appended, "duplicate_callback: first facts lost")
    require(
        not duplicate_event.appended and not duplicate_fill.appended,
        "duplicate_callback: duplicate facts were appended",
    )
    retry_blocked = block_duplicate(context.service, context.intent, context.scenario_id)
    return scenario_result(
        context,
        lifecycle=lifecycle,
        idempotent_retry_blocked=retry_blocked,
        transport_submit_calls=context.transport.submit_calls,
        reconciliation_status="resolved",
        reconciliation_result="duplicate_facts_deduplicated",
        action="continue_callback_polling",
    )


def _out_of_order_callback(root: Path, mode: RecoveryMatrixMode) -> RecoveryScenarioResult:
    context = start_scenario(root, "out_of_order_callback", mode)
    facts = (
        make_event(
            context,
            "partial",
            OrderStatus.PARTIALLY_FILLED,
            seconds=4,
            filled=Decimal("4"),
        ),
        make_event(context, "stale-accepted", OrderStatus.ACCEPTED, seconds=1, filled=Decimal("0")),
        make_event(context, "filled", OrderStatus.FILLED, seconds=5, filled=FAULT_QUANTITY),
        make_event(context, "late-cancel", OrderStatus.CANCELLED, seconds=2, filled=Decimal("4")),
    )
    for fact in facts:
        context.journal.append_order_event(fact)
        context.state_history.append(
            context.journal.replay().intents[context.intent.intent_id].submission_state
        )
    lifecycle = context.journal.replay().intents[context.intent.intent_id]
    require(lifecycle.submission_state is SubmissionState.FILLED, "out-of-order: not filled")
    retry_blocked = block_duplicate(context.service, context.intent, context.scenario_id)
    return scenario_result(
        context,
        lifecycle=lifecycle,
        idempotent_retry_blocked=retry_blocked,
        transport_submit_calls=context.transport.submit_calls,
        reconciliation_status="resolved",
        reconciliation_result="stale_callbacks_cannot_regress_state",
        action="retain_all_callback_evidence",
    )


def _partial_fill_restart(root: Path, mode: RecoveryMatrixMode) -> RecoveryScenarioResult:
    context = start_scenario(root, "partial_fill_restart", mode)
    context.transport.record_fill(
        context.reference,
        fill_id="partial_fill_restart-fill-001",
        quantity=Decimal("4"),
        price=FAULT_PRICE,
        filled_at=FAULT_NOW + timedelta(seconds=4),
    )
    partial = context.service.poll_and_record(context.reference)
    context.state_history.append(partial.submission_state)
    context.journal.create_snapshot(created_at=FAULT_NOW + timedelta(seconds=5))
    restarted_journal = DurableExecutionJournal(context.journal.path)
    restarted_transport = FaultPaperTransport(backend_name=backend_name(mode))
    restarted_service = JournaledExecutionTransport(restarted_transport, restarted_journal)
    retry_blocked = block_duplicate(restarted_service, context.intent, context.scenario_id)
    restarted = restarted_journal.replay().intents[context.intent.intent_id]
    context.state_history.append(restarted.submission_state)
    context.journal = restarted_journal
    context.service = restarted_service
    context.journal.append_reconciliation_evidence(
        make_evidence(
            context,
            "restart-partial",
            OrderStatus.PARTIALLY_FILLED,
            seconds=6,
            filled=Decimal("4"),
            message="restart recovered an open remainder without resubmission",
        )
    )
    lifecycle = context.journal.replay().intents[context.intent.intent_id]
    context.state_history.append(lifecycle.submission_state)
    require(
        context.journal.replay(use_snapshot=True) == context.journal.replay(use_snapshot=False),
        "partial_fill_restart: snapshot replay differs from raw replay",
    )
    return scenario_result(
        context,
        lifecycle=lifecycle,
        idempotent_retry_blocked=retry_blocked,
        transport_submit_calls=context.transport.submit_calls + restarted_transport.submit_calls,
        reconciliation_status="manual_intervention_required",
        reconciliation_result="open_remainder_recovered_after_restart",
        action="operator_choose_cancel_or_resume_remaining",
    )


def _cancel_fill_race(root: Path, mode: RecoveryMatrixMode) -> RecoveryScenarioResult:
    context = start_scenario(root, "cancel_fill_race", mode)
    context.journal.append_fill(
        make_fill(context, "fill-before-cancel", seconds=2, quantity=Decimal("2"))
    )
    context.state_history.append(
        context.journal.replay().intents[context.intent.intent_id].submission_state
    )
    context.journal.append_order_event(
        make_event(
            context,
            "cancel-ack",
            OrderStatus.CANCELLED,
            seconds=3,
            filled=Decimal("2"),
        )
    )
    context.state_history.append(
        context.journal.replay().intents[context.intent.intent_id].submission_state
    )
    context.journal.append_fill(make_fill(context, "late-fill", seconds=4, quantity=Decimal("8")))
    lifecycle = context.journal.replay().intents[context.intent.intent_id]
    context.state_history.append(lifecycle.submission_state)
    require(lifecycle.submission_state is SubmissionState.FILLED, "cancel_fill_race: not filled")
    retry_blocked = block_duplicate(context.service, context.intent, context.scenario_id)
    return scenario_result(
        context,
        lifecycle=lifecycle,
        idempotent_retry_blocked=retry_blocked,
        transport_submit_calls=context.transport.submit_calls,
        reconciliation_status="resolved",
        reconciliation_result="late_fill_wins_over_cancel_ack",
        action="retain_cancel_and_fill_evidence",
    )


def _reconnect_replay(root: Path, mode: RecoveryMatrixMode) -> RecoveryScenarioResult:
    context = start_scenario(root, "reconnect_replay", mode)
    context.transport.record_fill(
        context.reference,
        fill_id="reconnect_replay-fill-001",
        quantity=Decimal("4"),
        price=FAULT_PRICE,
        filled_at=FAULT_NOW + timedelta(seconds=4),
    )
    callback_batch = context.transport.query(context.reference)
    partial = context.service.record_batch(callback_batch)
    context.state_history.append(partial.submission_state)
    context.journal.create_snapshot(created_at=FAULT_NOW + timedelta(seconds=5))
    before_reconnect = context.journal.replay()
    restarted_journal = DurableExecutionJournal(context.journal.path)
    restarted_service = JournaledExecutionTransport(context.transport, restarted_journal)
    replayed = restarted_service.record_batch(callback_batch)
    context.journal = restarted_journal
    context.service = restarted_service
    context.state_history.append(replayed.submission_state)
    retry_blocked = block_duplicate(restarted_service, context.intent, context.scenario_id)
    after_reconnect = restarted_journal.replay()
    require(before_reconnect == after_reconnect, "reconnect_replay: duplicate replay changed state")
    require(
        restarted_journal.replay(use_snapshot=True) == restarted_journal.replay(use_snapshot=False),
        "reconnect_replay: snapshot and raw replay differ",
    )
    return scenario_result(
        context,
        lifecycle=after_reconnect.intents[context.intent.intent_id],
        idempotent_retry_blocked=retry_blocked,
        transport_submit_calls=context.transport.submit_calls,
        reconciliation_status="resolved",
        reconciliation_result="reconnect_replay_is_idempotent",
        action="resume_callback_polling",
    )


def _position_drift(root: Path, mode: RecoveryMatrixMode) -> RecoveryScenarioResult:
    context = start_scenario(root, "position_drift", mode)
    expected_position = Decimal("10")
    broker_position = Decimal("7")
    drift = broker_position - expected_position
    require(drift != 0, "position_drift: fixture contains no drift")
    context.journal.append_reconciliation_evidence(
        make_evidence(
            context,
            "position-observation",
            OrderStatus.ACCEPTED,
            seconds=5,
            filled=Decimal("0"),
            message="broker position differs from the journal-derived expectation",
            metadata={
                "expected_position": str(expected_position),
                "broker_position": str(broker_position),
                "position_drift": str(drift),
                "kill_switch_required": True,
            },
        )
    )
    lifecycle = context.journal.replay().intents[context.intent.intent_id]
    context.state_history.append(lifecycle.submission_state)
    retry_blocked = block_duplicate(context.service, context.intent, context.scenario_id)
    return scenario_result(
        context,
        lifecycle=lifecycle,
        idempotent_retry_blocked=retry_blocked,
        transport_submit_calls=context.transport.submit_calls,
        reconciliation_status="manual_intervention_required",
        reconciliation_result="broker_position_drift_detected",
        action="activate_kill_switch_and_reconcile_positions",
        kill_switch=True,
        position_drift=drift,
    )


def _run_all(root: Path, mode: RecoveryMatrixMode) -> tuple[RecoveryScenarioResult, ...]:
    root.mkdir(parents=True, exist_ok=True)
    runners = (
        _accepted_but_timeout,
        _duplicate_submission,
        _duplicate_callback,
        _out_of_order_callback,
        _partial_fill_restart,
        _cancel_fill_race,
        _reconnect_replay,
        _position_drift,
    )
    results = tuple(runner(root, mode) for runner in runners)
    require(
        tuple(result.id for result in results) == RECOVERY_SCENARIO_IDS,
        "fault runners do not match the canonical scenario order",
    )
    return results


def run_fault_scenarios(
    *,
    mode: RecoveryMatrixMode,
    workspace: Path | None,
) -> tuple[RecoveryScenarioResult, ...]:
    """Run the complete matrix without importing a broker or network SDK."""

    if workspace is not None:
        return _run_all(workspace, mode)
    with TemporaryDirectory(prefix="qexec-recovery-matrix-") as temporary:
        return _run_all(Path(temporary), mode)


__all__ = ["run_fault_scenarios"]
