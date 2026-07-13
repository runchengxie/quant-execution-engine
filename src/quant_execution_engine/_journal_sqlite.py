# pyright: strict
"""Public SQLite-backed implementation of the durable execution journal."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from typing import cast

from ._journal_codec import (
    datetime_from_json,
    datetime_to_json,
    evidence_payload,
    fill_payload,
    order_event_payload,
    state_from_json,
    state_to_json,
    submission_payload,
)
from ._journal_domain import (
    AppendResult,
    ExecutionJournalState,
    IdempotencyConflictError,
    JournalCorruptionError,
    JournalEntry,
    JournalEventKind,
    JournalInvariantError,
    ReconciliationEvidence,
    SnapshotInfo,
    SubmissionPreparation,
)
from ._journal_reducer import replay_entries
from ._journal_sqlite_core import JournalDatabaseCore, non_empty, sha256_text
from .domain import Fill, OrderEvent, OrderIntent


class DurableExecutionJournal(JournalDatabaseCore):
    def prepare_submission(
        self,
        intent: OrderIntent,
        *,
        idempotency_key: str,
        attempt_id: str,
        occurred_at: datetime | None = None,
    ) -> SubmissionPreparation:
        """Atomically reserve an intent and grant at most one broker submit call.

        A returned ``should_submit=True`` is a one-shot permission for this
        caller.  The committed state is already ``SUBMISSION_UNCERTAIN`` before
        the caller can contact a broker, so a restart never retries blindly.
        """

        key = non_empty(idempotency_key, "idempotency_key")
        requested_attempt = non_empty(attempt_id, "attempt_id")
        event_time = occurred_at or datetime.now(timezone.utc)
        try:
            with closing(self._connect()) as connection:
                self._begin(connection)
                try:
                    intent_created, _ = self._reserve_intent_in_connection(
                        connection,
                        intent,
                        key,
                    )
                    state = self._state_in_connection(connection)
                    lifecycle = state.intents[intent.intent_id]
                    if lifecycle.submission_attempt_ids:
                        actual_attempt = lifecycle.submission_attempt_ids[0]
                        self._commit(connection)
                        return SubmissionPreparation(
                            intent_id=intent.intent_id,
                            idempotency_key=key,
                            attempt_id=actual_attempt,
                            intent_created=intent_created,
                            should_submit=False,
                            through_sequence=state.through_sequence,
                        )
                    append = self._append_in_connection(
                        connection,
                        record_id=f"submission-started:{requested_attempt}",
                        intent_id=intent.intent_id,
                        kind=JournalEventKind.SUBMISSION_STARTED,
                        occurred_at=event_time,
                        payload_json=submission_payload(requested_attempt),
                    )
                    self._state_in_connection(connection)
                    self._commit(connection)
                    return SubmissionPreparation(
                        intent_id=intent.intent_id,
                        idempotency_key=key,
                        attempt_id=requested_attempt,
                        intent_created=intent_created,
                        should_submit=True,
                        through_sequence=append.sequence,
                    )
                except Exception:
                    self._rollback(connection)
                    raise
        except (JournalCorruptionError, JournalInvariantError, IdempotencyConflictError):
            raise
        except sqlite3.DatabaseError as exc:
            raise JournalCorruptionError("cannot prepare durable order submission") from exc

    def _append_existing_intent(
        self,
        *,
        record_id: str,
        intent_id: str,
        kind: JournalEventKind,
        occurred_at: datetime,
        payload_json: str,
    ) -> AppendResult:
        try:
            with closing(self._connect()) as connection:
                self._begin(connection)
                try:
                    exists = connection.execute(
                        "SELECT 1 FROM journal_intents WHERE intent_id = ?",
                        (intent_id,),
                    ).fetchone()
                    if exists is None:
                        raise JournalInvariantError(f"unknown intent {intent_id!r}")
                    result = self._append_in_connection(
                        connection,
                        record_id=record_id,
                        intent_id=intent_id,
                        kind=kind,
                        occurred_at=occurred_at,
                        payload_json=payload_json,
                    )
                    if result.appended:
                        self._state_in_connection(connection)
                    self._commit(connection)
                    return result
                except Exception:
                    self._rollback(connection)
                    raise
        except (JournalCorruptionError, JournalInvariantError, IdempotencyConflictError):
            raise
        except sqlite3.DatabaseError as exc:
            raise JournalCorruptionError("cannot append execution journal record") from exc

    def record_submission_uncertainty(
        self,
        intent_id: str,
        *,
        attempt_id: str,
        reason: str,
        occurred_at: datetime | None = None,
    ) -> AppendResult:
        """Retain why an attempted submission requires broker reconciliation."""

        normalized_intent = non_empty(intent_id, "intent_id")
        normalized_attempt = non_empty(attempt_id, "attempt_id")
        normalized_reason = non_empty(reason, "reason")
        return self._append_existing_intent(
            record_id=f"submission-uncertain:{normalized_attempt}",
            intent_id=normalized_intent,
            kind=JournalEventKind.SUBMISSION_UNCERTAIN,
            occurred_at=occurred_at or datetime.now(timezone.utc),
            payload_json=submission_payload(normalized_attempt, normalized_reason),
        )

    def append_order_event(self, event: OrderEvent) -> AppendResult:
        """Append an idempotent normalized broker callback."""

        if event.intent_id is None:
            raise ValueError("journaled order events require intent_id")
        return self._append_existing_intent(
            record_id=f"order-event:{event.event_id}",
            intent_id=event.intent_id,
            kind=JournalEventKind.ORDER_EVENT_RECORDED,
            occurred_at=event.occurred_at,
            payload_json=order_event_payload(event),
        )

    def append_fill(self, fill: Fill) -> AppendResult:
        """Append an idempotent normalized fill callback."""

        if fill.intent_id is None:
            raise ValueError("journaled fills require intent_id")
        return self._append_existing_intent(
            record_id=f"fill:{fill.fill_id}",
            intent_id=fill.intent_id,
            kind=JournalEventKind.FILL_RECORDED,
            occurred_at=fill.filled_at,
            payload_json=fill_payload(fill),
        )

    def append_reconciliation_evidence(
        self,
        evidence: ReconciliationEvidence,
    ) -> AppendResult:
        """Append an immutable broker observation used to resolve uncertainty."""

        return self._append_existing_intent(
            record_id=f"reconciliation:{evidence.evidence_id}",
            intent_id=evidence.intent_id,
            kind=JournalEventKind.RECONCILIATION_RECORDED,
            occurred_at=evidence.observed_at,
            payload_json=evidence_payload(evidence),
        )

    @staticmethod
    def _validate_all_snapshots(
        connection: sqlite3.Connection,
        entries: tuple[JournalEntry, ...],
    ) -> None:
        rows = connection.execute(
            "SELECT through_sequence, state_json, state_hash FROM journal_snapshots "
            "ORDER BY through_sequence"
        ).fetchall()
        maximum = entries[-1].sequence if entries else 0
        for row in rows:
            through_sequence = cast(int, row["through_sequence"])
            state_json = cast(str, row["state_json"])
            state_hash = cast(str, row["state_hash"])
            if through_sequence > maximum:
                raise JournalCorruptionError("snapshot extends beyond the durable journal")
            if sha256_text(state_json) != state_hash:
                raise JournalCorruptionError("journal snapshot hash mismatch")
            state = state_from_json(state_json)
            if state.through_sequence != through_sequence:
                raise JournalCorruptionError("snapshot sequence does not match its state payload")

    @staticmethod
    def _snapshot_in_connection(
        connection: sqlite3.Connection,
        max_sequence: int,
    ) -> tuple[ExecutionJournalState, SnapshotInfo] | None:
        row = connection.execute(
            "SELECT snapshot_id, through_sequence, state_json, state_hash, created_at "
            "FROM journal_snapshots WHERE through_sequence <= ? "
            "ORDER BY through_sequence DESC LIMIT 1",
            (max_sequence,),
        ).fetchone()
        if row is None:
            return None
        state_json = cast(str, row["state_json"])
        state_hash = cast(str, row["state_hash"])
        if sha256_text(state_json) != state_hash:
            raise JournalCorruptionError("journal snapshot hash mismatch")
        state = state_from_json(state_json)
        through_sequence = cast(int, row["through_sequence"])
        if state.through_sequence != through_sequence:
            raise JournalCorruptionError("snapshot sequence does not match its state payload")
        info = SnapshotInfo(
            snapshot_id=cast(str, row["snapshot_id"]),
            through_sequence=through_sequence,
            state_hash=state_hash,
            created_at=datetime_from_json(row["created_at"], "snapshot.created_at"),
        )
        return state, info

    def replay(self, *, use_snapshot: bool = True) -> ExecutionJournalState:
        """Reconstruct current state, optionally replaying after the latest snapshot."""

        try:
            with closing(self._connect()) as connection:
                self._check_sqlite_integrity(connection)
                entries = self._entries_in_connection(connection)
                if not use_snapshot:
                    return replay_entries(entries)
                self._validate_all_snapshots(connection, entries)
                max_sequence = entries[-1].sequence if entries else 0
                materialized = self._snapshot_in_connection(connection, max_sequence)
                if materialized is None:
                    return replay_entries(entries)
                state, _ = materialized
                tail = tuple(entry for entry in entries if entry.sequence > state.through_sequence)
                return replay_entries(tail, state)
        except (JournalCorruptionError, JournalInvariantError):
            raise
        except sqlite3.DatabaseError as exc:
            raise JournalCorruptionError("cannot replay execution journal") from exc

    def create_snapshot(self, *, created_at: datetime | None = None) -> SnapshotInfo:
        """Append an immutable checkpoint of fully reduced current state."""

        timestamp = created_at or datetime.now(timezone.utc)
        try:
            with closing(self._connect()) as connection:
                self._begin(connection)
                try:
                    entries = self._entries_in_connection(connection)
                    self._validate_all_snapshots(connection, entries)
                    state = replay_entries(entries)
                    state_json = state_to_json(state)
                    state_hash = sha256_text(state_json)
                    snapshot_id = f"snapshot:{state.through_sequence}:{state_hash[:16]}"
                    existing = connection.execute(
                        "SELECT snapshot_id, through_sequence, state_hash, created_at "
                        "FROM journal_snapshots WHERE through_sequence = ?",
                        (state.through_sequence,),
                    ).fetchone()
                    if existing is not None:
                        if (
                            cast(str, existing["snapshot_id"]) != snapshot_id
                            or cast(str, existing["state_hash"]) != state_hash
                        ):
                            raise JournalCorruptionError(
                                "conflicting snapshot exists for the same journal sequence"
                            )
                        self._commit(connection)
                        return SnapshotInfo(
                            snapshot_id=snapshot_id,
                            through_sequence=state.through_sequence,
                            state_hash=state_hash,
                            created_at=datetime_from_json(
                                existing["created_at"], "snapshot.created_at"
                            ),
                        )
                    connection.execute(
                        "INSERT INTO journal_snapshots(snapshot_id, through_sequence, state_json, "
                        "state_hash, created_at) VALUES (?, ?, ?, ?, ?)",
                        (
                            snapshot_id,
                            state.through_sequence,
                            state_json,
                            state_hash,
                            datetime_to_json(timestamp),
                        ),
                    )
                    self._commit(connection)
                    return SnapshotInfo(
                        snapshot_id=snapshot_id,
                        through_sequence=state.through_sequence,
                        state_hash=state_hash,
                        created_at=timestamp.astimezone(timezone.utc),
                    )
                except Exception:
                    self._rollback(connection)
                    raise
        except (JournalCorruptionError, JournalInvariantError):
            raise
        except sqlite3.DatabaseError as exc:
            raise JournalCorruptionError("cannot create execution journal snapshot") from exc

    def check_integrity(self) -> None:
        """Fail closed on SQLite, hash-chain, snapshot, or reducer corruption."""

        self.replay(use_snapshot=True)
