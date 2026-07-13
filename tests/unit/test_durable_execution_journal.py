from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from quant_execution_engine.domain import (
    ExecutionEventType,
    Fill,
    InstrumentId,
    OrderEvent,
    OrderIntent,
    OrderSide,
    OrderStatus,
    OrderType,
)
from quant_execution_engine.execution_journal import (
    DurableExecutionJournal,
    IdempotencyConflictError,
    JournalCorruptionError,
    JournalInvariantError,
    ReconciliationEvidence,
    SubmissionState,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 7, 13, 9, 0, tzinfo=timezone.utc)


def _instrument() -> InstrumentId:
    return InstrumentId(symbol="AAPL", market="US", currency="USD")


def _intent(intent_id: str = "intent-001", *, quantity: str = "10") -> OrderIntent:
    return OrderIntent(
        intent_id=intent_id,
        instrument=_instrument(),
        side=OrderSide.BUY,
        quantity=Decimal(quantity),
        order_type=OrderType.MARKET,
        created_at=NOW,
        broker_name="paper",
        account_label="main",
        run_id="run-001",
    )


def _event(
    event_id: str,
    status: OrderStatus,
    *,
    occurred_at: datetime = NOW,
    filled: str | None = None,
    broker_order_id: str = "broker-001",
    average_fill_price: str = "190",
) -> OrderEvent:
    event_type = {
        OrderStatus.ACCEPTED: ExecutionEventType.ORDER_ACKNOWLEDGED,
        OrderStatus.PARTIALLY_FILLED: ExecutionEventType.PARTIALLY_FILLED,
        OrderStatus.FILLED: ExecutionEventType.FILLED,
        OrderStatus.CANCELLED: ExecutionEventType.CANCELLED,
    }.get(status, ExecutionEventType.ORDER_UPDATED)
    filled_quantity = Decimal(filled) if filled is not None else None
    return OrderEvent(
        event_id=event_id,
        event_type=event_type,
        occurred_at=occurred_at,
        instrument=_instrument(),
        status=status,
        broker_name="paper",
        account_label="main",
        broker_order_id=broker_order_id,
        intent_id="intent-001",
        side=OrderSide.BUY,
        quantity=Decimal("10"),
        filled_quantity=filled_quantity,
        remaining_quantity=(
            Decimal("10") - filled_quantity if filled_quantity is not None else None
        ),
        average_fill_price=Decimal(average_fill_price) if filled_quantity else None,
    )


def _prepared(path: Path) -> DurableExecutionJournal:
    journal = DurableExecutionJournal(path)
    prepared = journal.prepare_submission(
        _intent(),
        idempotency_key="portfolio/main/run-001/row-1",
        attempt_id="attempt-001",
        occurred_at=NOW,
    )
    assert prepared.should_submit is True
    return journal


def test_journal_rejects_non_positive_lock_timeout(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="timeout_seconds must be positive"):
        DurableExecutionJournal(tmp_path / "journal.sqlite3", timeout_seconds=0)


def test_prepare_submission_is_durable_and_one_shot_across_restart(tmp_path: Path) -> None:
    path = tmp_path / "journal.sqlite3"
    journal = _prepared(path)

    before_restart = journal.replay()
    lifecycle = before_restart.intents["intent-001"]
    assert lifecycle.submission_state is SubmissionState.SUBMISSION_UNCERTAIN
    assert lifecycle.requires_reconciliation is True
    assert lifecycle.submission_attempt_ids == ("attempt-001",)

    restarted = DurableExecutionJournal(path)
    duplicate = restarted.prepare_submission(
        _intent(),
        idempotency_key="portfolio/main/run-001/row-1",
        attempt_id="attempt-after-restart",
        occurred_at=NOW + timedelta(seconds=1),
    )

    assert duplicate.should_submit is False
    assert duplicate.intent_created is False
    assert duplicate.attempt_id == "attempt-001"
    assert restarted.replay() == before_restart


def test_accepted_but_timeout_stays_uncertain_until_broker_fact_arrives(tmp_path: Path) -> None:
    path = tmp_path / "journal.sqlite3"
    journal = _prepared(path)
    uncertainty = journal.record_submission_uncertainty(
        "intent-001",
        attempt_id="attempt-001",
        reason="broker request timed out after socket write",
        occurred_at=NOW + timedelta(seconds=2),
    )
    duplicate = journal.record_submission_uncertainty(
        "intent-001",
        attempt_id="attempt-001",
        reason="broker request timed out after socket write",
        occurred_at=NOW + timedelta(seconds=2),
    )

    assert uncertainty.appended is True
    assert duplicate.appended is False
    restarted = DurableExecutionJournal(path)
    uncertain = restarted.replay().intents["intent-001"]
    assert uncertain.submission_state is SubmissionState.SUBMISSION_UNCERTAIN
    assert uncertain.uncertainty_messages == ("broker request timed out after socket write",)

    restarted.append_order_event(
        _event("event-accepted", OrderStatus.ACCEPTED, occurred_at=NOW + timedelta(seconds=3))
    )
    resolved = restarted.replay().intents["intent-001"]
    assert resolved.submission_state is SubmissionState.ACCEPTED
    assert resolved.requires_reconciliation is False


def test_idempotency_key_and_intent_id_reject_different_content(tmp_path: Path) -> None:
    journal = _prepared(tmp_path / "journal.sqlite3")

    with pytest.raises(IdempotencyConflictError):
        journal.prepare_submission(
            _intent("intent-other"),
            idempotency_key="portfolio/main/run-001/row-1",
            attempt_id="attempt-other",
            occurred_at=NOW,
        )
    with pytest.raises(IdempotencyConflictError):
        journal.prepare_submission(
            _intent(),
            idempotency_key="different-key",
            attempt_id="attempt-other",
            occurred_at=NOW,
        )

    assert len(journal.entries()) == 2


def test_duplicate_callbacks_and_fills_are_harmless(tmp_path: Path) -> None:
    journal = _prepared(tmp_path / "journal.sqlite3")
    event = _event("event-partial", OrderStatus.PARTIALLY_FILLED, filled="4")
    first_event = journal.append_order_event(event)
    duplicate_event = journal.append_order_event(event)
    fill = Fill(
        fill_id="fill-001",
        broker_order_id="broker-001",
        instrument=_instrument(),
        quantity=Decimal("4"),
        price=Decimal("190"),
        filled_at=NOW,
        broker_name="paper",
        account_label="main",
        intent_id="intent-001",
        side=OrderSide.BUY,
    )
    first_fill = journal.append_fill(fill)
    duplicate_fill = journal.append_fill(fill)

    assert first_event.appended is True
    assert duplicate_event.appended is False
    assert first_fill.appended is True
    assert duplicate_fill.appended is False
    lifecycle = journal.replay().intents["intent-001"]
    assert lifecycle.order_event_ids == ("event-partial",)
    assert tuple(item.fill_id for item in lifecycle.fills) == ("fill-001",)
    assert lifecycle.filled_quantity == Decimal("4")


def test_invalid_follow_up_fact_rolls_back_the_whole_append(tmp_path: Path) -> None:
    journal = _prepared(tmp_path / "journal.sqlite3")
    journal.append_order_event(_event("event-accepted", OrderStatus.ACCEPTED))
    sequence_before = journal.replay().through_sequence

    with pytest.raises(JournalInvariantError, match="multiple broker order IDs"):
        journal.append_order_event(
            _event(
                "event-conflicting-order",
                OrderStatus.ACCEPTED,
                broker_order_id="broker-002",
            )
        )
    with pytest.raises(JournalInvariantError, match="unknown submission attempt"):
        journal.record_submission_uncertainty(
            "intent-001",
            attempt_id="never-started",
            reason="must not commit",
            occurred_at=NOW,
        )

    assert journal.replay().through_sequence == sequence_before


def test_out_of_order_callbacks_cannot_regress_partial_or_filled_state(tmp_path: Path) -> None:
    journal = _prepared(tmp_path / "journal.sqlite3")
    journal.append_order_event(
        _event(
            "event-partial",
            OrderStatus.PARTIALLY_FILLED,
            occurred_at=NOW + timedelta(seconds=4),
            filled="4",
        )
    )
    journal.append_order_event(
        _event(
            "event-stale-accepted",
            OrderStatus.ACCEPTED,
            occurred_at=NOW + timedelta(seconds=1),
        )
    )
    partial = journal.replay().intents["intent-001"]
    assert partial.submission_state is SubmissionState.PARTIALLY_FILLED
    assert partial.filled_quantity == Decimal("4")

    journal.append_order_event(
        _event(
            "event-filled",
            OrderStatus.FILLED,
            occurred_at=NOW + timedelta(seconds=5),
            filled="10",
            average_fill_price="195",
        )
    )
    journal.append_order_event(
        _event(
            "event-late-cancel",
            OrderStatus.CANCELLED,
            occurred_at=NOW + timedelta(seconds=2),
            filled="4",
            average_fill_price="180",
        )
    )
    terminal = journal.replay().intents["intent-001"]
    assert terminal.submission_state is SubmissionState.FILLED
    assert terminal.order_status is OrderStatus.FILLED
    assert terminal.filled_quantity == Decimal("10")
    assert terminal.remaining_quantity == Decimal("0")
    assert terminal.average_fill_price == Decimal("195")


def test_late_full_fill_can_upgrade_cancelled_order_without_losing_audit(tmp_path: Path) -> None:
    journal = _prepared(tmp_path / "journal.sqlite3")
    journal.append_order_event(_event("event-cancel", OrderStatus.CANCELLED, filled="2"))
    cancelled = journal.replay().intents["intent-001"]
    assert cancelled.submission_state is SubmissionState.CANCELLED
    assert cancelled.filled_quantity == Decimal("2")

    journal.append_order_event(_event("event-late-fill", OrderStatus.FILLED, filled="10"))
    filled = journal.replay().intents["intent-001"]
    assert filled.submission_state is SubmissionState.FILLED
    assert filled.order_event_ids == ("event-cancel", "event-late-fill")


def test_reconciliation_evidence_is_immutable_and_idempotent(tmp_path: Path) -> None:
    journal = _prepared(tmp_path / "journal.sqlite3")
    evidence = ReconciliationEvidence(
        evidence_id="reconcile-001",
        intent_id="intent-001",
        observed_at=NOW + timedelta(minutes=1),
        source="paper.get_order",
        observed_status=OrderStatus.CANCELLED,
        broker_order_id="broker-001",
        observed_filled_quantity=Decimal("3"),
        observed_remaining_quantity=Decimal("7"),
        message="observed after timeout",
        metadata={"request_id": "request-001"},
    )

    first = journal.append_reconciliation_evidence(evidence)
    duplicate = journal.append_reconciliation_evidence(evidence)
    lifecycle = journal.replay().intents["intent-001"]

    assert first.appended is True
    assert duplicate.appended is False
    assert lifecycle.submission_state is SubmissionState.CANCELLED
    assert lifecycle.filled_quantity == Decimal("3")
    assert lifecycle.reconciliation_evidence == (evidence,)

    with sqlite3.connect(journal.path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "UPDATE journal_events SET payload_json = '{}' WHERE record_id = ?",
                ("reconciliation:reconcile-001",),
            )


def test_snapshot_plus_tail_replay_matches_full_replay(tmp_path: Path) -> None:
    path = tmp_path / "journal.sqlite3"
    journal = _prepared(path)
    journal.append_order_event(_event("event-accepted", OrderStatus.ACCEPTED))
    journal.append_reconciliation_evidence(
        ReconciliationEvidence(
            evidence_id="snapshot-evidence",
            intent_id="intent-001",
            observed_at=NOW,
            source="paper.get_order",
            observed_status=OrderStatus.ACCEPTED,
            broker_order_id="broker-001",
            metadata={"nested": {"request_ids": ["request-001"]}},
        )
    )
    snapshot = journal.create_snapshot(created_at=NOW + timedelta(minutes=1))
    repeated_snapshot = journal.create_snapshot(created_at=NOW + timedelta(minutes=2))
    journal.append_order_event(_event("event-partial", OrderStatus.PARTIALLY_FILLED, filled="5"))

    assert snapshot == repeated_snapshot
    with_snapshot = DurableExecutionJournal(path).replay(use_snapshot=True)
    without_snapshot = DurableExecutionJournal(path).replay(use_snapshot=False)
    assert with_snapshot == without_snapshot
    assert with_snapshot.through_sequence == 5
    assert with_snapshot.intents["intent-001"].filled_quantity == Decimal("5")


def test_hash_chain_detects_corrupted_record(tmp_path: Path) -> None:
    journal = _prepared(tmp_path / "journal.sqlite3")
    with sqlite3.connect(journal.path) as connection:
        connection.execute("DROP TRIGGER journal_events_no_update")
        connection.execute("UPDATE journal_events SET payload_json = '{}' WHERE sequence = 1")

    with pytest.raises(JournalCorruptionError, match="record hash mismatch"):
        journal.replay()


def test_intent_idempotency_index_corruption_fails_closed(tmp_path: Path) -> None:
    journal = _prepared(tmp_path / "journal.sqlite3")
    with sqlite3.connect(journal.path) as connection:
        connection.execute("DROP TRIGGER journal_intents_no_update")
        connection.execute("UPDATE journal_intents SET idempotency_key = 'tampered-key'")

    with pytest.raises(JournalCorruptionError, match="index identity is inconsistent"):
        journal.replay()


def test_snapshot_corruption_fails_closed_but_raw_replay_remains_recoverable(
    tmp_path: Path,
) -> None:
    journal = _prepared(tmp_path / "journal.sqlite3")
    journal.create_snapshot(created_at=NOW)
    with sqlite3.connect(journal.path) as connection:
        connection.execute("DROP TRIGGER journal_snapshots_no_update")
        connection.execute("UPDATE journal_snapshots SET state_json = '{}'")

    with pytest.raises(JournalCorruptionError, match="snapshot hash mismatch"):
        journal.replay(use_snapshot=True)
    assert journal.replay(use_snapshot=False).through_sequence == 2


def test_invalid_or_torn_database_is_reported_as_corruption(tmp_path: Path) -> None:
    path = tmp_path / "torn.sqlite3"
    path.write_bytes(b"not a sqlite database\x00partial-record")

    with pytest.raises(JournalCorruptionError, match="cannot initialize"):
        DurableExecutionJournal(path)


def test_concurrent_prepare_grants_exactly_one_submission(tmp_path: Path) -> None:
    path = tmp_path / "journal.sqlite3"
    DurableExecutionJournal(path)

    def prepare(attempt_id: str) -> tuple[bool, str]:
        result = DurableExecutionJournal(path).prepare_submission(
            _intent(),
            idempotency_key="portfolio/main/run-001/row-1",
            attempt_id=attempt_id,
            occurred_at=NOW,
        )
        return result.should_submit, result.attempt_id

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = tuple(executor.map(prepare, (f"attempt-{index}" for index in range(8))))

    assert sum(should_submit for should_submit, _ in results) == 1
    assert len({actual_attempt for _, actual_attempt in results}) == 1
    state = DurableExecutionJournal(path).replay()
    assert len(state.intents) == 1
    assert state.through_sequence == 2
