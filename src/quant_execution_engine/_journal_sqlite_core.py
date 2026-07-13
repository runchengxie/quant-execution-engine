# pyright: strict
"""Crash-safe SQLite persistence for the append-only execution journal."""

from __future__ import annotations

import hashlib
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import cast

from ._journal_codec import (
    datetime_from_json,
    datetime_to_json,
    intent_from_payload,
    intent_payload,
)
from ._journal_domain import (
    AppendResult,
    ExecutionJournalState,
    IdempotencyConflictError,
    JournalCorruptionError,
    JournalEntry,
    JournalEventKind,
)
from ._journal_reducer import replay_entries
from .domain import OrderIntent

_DATABASE_SCHEMA_VERSION = "1"
_GENESIS_HASH = "0" * 64

_SCHEMA = """
CREATE TABLE IF NOT EXISTS journal_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS journal_events (
    sequence INTEGER PRIMARY KEY,
    record_id TEXT NOT NULL UNIQUE,
    intent_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    previous_hash TEXT NOT NULL,
    record_hash TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS journal_intents (
    intent_id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    payload_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    recorded_sequence INTEGER NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS journal_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    through_sequence INTEGER NOT NULL UNIQUE,
    state_json TEXT NOT NULL,
    state_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TRIGGER IF NOT EXISTS journal_events_no_update
BEFORE UPDATE ON journal_events
BEGIN
    SELECT RAISE(ABORT, 'journal_events is append-only');
END;

CREATE TRIGGER IF NOT EXISTS journal_events_no_delete
BEFORE DELETE ON journal_events
BEGIN
    SELECT RAISE(ABORT, 'journal_events is append-only');
END;

CREATE TRIGGER IF NOT EXISTS journal_intents_no_update
BEFORE UPDATE ON journal_intents
BEGIN
    SELECT RAISE(ABORT, 'journal_intents is append-only');
END;

CREATE TRIGGER IF NOT EXISTS journal_intents_no_delete
BEFORE DELETE ON journal_intents
BEGIN
    SELECT RAISE(ABORT, 'journal_intents is append-only');
END;

CREATE TRIGGER IF NOT EXISTS journal_snapshots_no_update
BEFORE UPDATE ON journal_snapshots
BEGIN
    SELECT RAISE(ABORT, 'journal_snapshots is append-only');
END;

CREATE TRIGGER IF NOT EXISTS journal_snapshots_no_delete
BEFORE DELETE ON journal_snapshots
BEGIN
    SELECT RAISE(ABORT, 'journal_snapshots is append-only');
END;
"""


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _record_hash(
    previous_hash: str,
    sequence: int,
    record_id: str,
    intent_id: str,
    kind: JournalEventKind,
    occurred_at: str,
    payload_json: str,
) -> str:
    material = "\x1f".join(
        (
            previous_hash,
            str(sequence),
            record_id,
            intent_id,
            kind.value,
            occurred_at,
            payload_json,
        )
    )
    return sha256_text(material)


def non_empty(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    return normalized


class JournalDatabaseCore:
    """Append-only execution facts with transactional idempotency and replay."""

    def __init__(self, path: str | Path, *, timeout_seconds: float = 5.0) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.path = Path(path)
        self.timeout_seconds = timeout_seconds
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.path,
            timeout=self.timeout_seconds,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute(f"PRAGMA busy_timeout = {int(self.timeout_seconds * 1000)}")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA synchronous = FULL")
        return connection

    def _initialize(self) -> None:
        try:
            with closing(self._connect()) as connection:
                connection.execute("PRAGMA journal_mode = WAL")
                connection.executescript(_SCHEMA)
                row = connection.execute(
                    "SELECT value FROM journal_meta WHERE key = 'schema_version'"
                ).fetchone()
                if row is None:
                    connection.execute(
                        "INSERT INTO journal_meta(key, value) VALUES ('schema_version', ?)",
                        (_DATABASE_SCHEMA_VERSION,),
                    )
                elif cast(str, row["value"]) != _DATABASE_SCHEMA_VERSION:
                    raise JournalCorruptionError("unsupported execution journal schema version")
        except JournalCorruptionError:
            raise
        except sqlite3.DatabaseError as exc:
            raise JournalCorruptionError("cannot initialize execution journal database") from exc

    @staticmethod
    def _begin(connection: sqlite3.Connection) -> None:
        connection.execute("BEGIN IMMEDIATE")

    @staticmethod
    def _commit(connection: sqlite3.Connection) -> None:
        connection.execute("COMMIT")

    @staticmethod
    def _rollback(connection: sqlite3.Connection) -> None:
        if connection.in_transaction:
            connection.execute("ROLLBACK")

    @staticmethod
    def _check_sqlite_integrity(connection: sqlite3.Connection) -> None:
        rows = connection.execute("PRAGMA quick_check").fetchall()
        results = tuple(cast(str, row[0]) for row in rows)
        if results != ("ok",):
            raise JournalCorruptionError("SQLite quick_check failed: " + "; ".join(results))

    @staticmethod
    def _row_to_entry(row: sqlite3.Row) -> JournalEntry:
        try:
            kind = JournalEventKind(cast(str, row["kind"]))
        except ValueError as exc:
            raise JournalCorruptionError(f"unknown journal event kind {row['kind']!r}") from exc
        return JournalEntry(
            sequence=cast(int, row["sequence"]),
            record_id=cast(str, row["record_id"]),
            intent_id=cast(str, row["intent_id"]),
            kind=kind,
            occurred_at=datetime_from_json(row["occurred_at"], "occurred_at"),
            payload_json=cast(str, row["payload_json"]),
            previous_hash=cast(str, row["previous_hash"]),
            record_hash=cast(str, row["record_hash"]),
        )

    @classmethod
    def _entries_in_connection(cls, connection: sqlite3.Connection) -> tuple[JournalEntry, ...]:
        rows = connection.execute(
            "SELECT sequence, record_id, intent_id, kind, occurred_at, payload_json, "
            "previous_hash, record_hash FROM journal_events ORDER BY sequence"
        ).fetchall()
        entries = tuple(cls._row_to_entry(row) for row in rows)
        previous_hash = _GENESIS_HASH
        expected_sequence = 1
        for entry in entries:
            if entry.sequence != expected_sequence:
                raise JournalCorruptionError(
                    f"journal sequence gap: expected {expected_sequence}, got {entry.sequence}"
                )
            if entry.previous_hash != previous_hash:
                raise JournalCorruptionError(
                    f"journal hash-chain mismatch at sequence {entry.sequence}"
                )
            timestamp = datetime_to_json(entry.occurred_at)
            expected_hash = _record_hash(
                previous_hash,
                entry.sequence,
                entry.record_id,
                entry.intent_id,
                entry.kind,
                timestamp,
                entry.payload_json,
            )
            if entry.record_hash != expected_hash:
                raise JournalCorruptionError(
                    f"journal record hash mismatch at sequence {entry.sequence}"
                )
            previous_hash = entry.record_hash
            expected_sequence += 1
        cls._validate_intent_index(connection, entries)
        return entries

    @staticmethod
    def _validate_intent_index(
        connection: sqlite3.Connection,
        entries: tuple[JournalEntry, ...],
    ) -> None:
        intent_entries = {
            entry.intent_id: entry
            for entry in entries
            if entry.kind is JournalEventKind.INTENT_RECORDED
        }
        rows = connection.execute(
            "SELECT intent_id, idempotency_key, payload_hash, payload_json, recorded_sequence "
            "FROM journal_intents"
        ).fetchall()
        if len(rows) != len(intent_entries):
            raise JournalCorruptionError("intent index does not match journal intent records")
        for row in rows:
            intent_id = cast(str, row["intent_id"])
            entry = intent_entries.get(intent_id)
            payload = cast(str, row["payload_json"])
            if (
                entry is None
                or entry.sequence != cast(int, row["recorded_sequence"])
                or entry.payload_json != payload
                or cast(str, row["payload_hash"]) != sha256_text(payload)
            ):
                raise JournalCorruptionError(
                    f"intent index is inconsistent for intent {intent_id!r}"
                )
            indexed_intent, indexed_key = intent_from_payload(payload)
            if indexed_intent.intent_id != intent_id or indexed_key != cast(
                str, row["idempotency_key"]
            ):
                raise JournalCorruptionError(
                    f"intent index identity is inconsistent for intent {intent_id!r}"
                )

    @classmethod
    def _append_in_connection(
        cls,
        connection: sqlite3.Connection,
        *,
        record_id: str,
        intent_id: str,
        kind: JournalEventKind,
        occurred_at: datetime,
        payload_json: str,
    ) -> AppendResult:
        timestamp = datetime_to_json(occurred_at)
        existing = connection.execute(
            "SELECT sequence, record_id, intent_id, kind, occurred_at, payload_json, "
            "previous_hash, record_hash FROM journal_events WHERE record_id = ?",
            (record_id,),
        ).fetchone()
        if existing is not None:
            entry = cls._row_to_entry(existing)
            if (
                entry.intent_id != intent_id
                or entry.kind is not kind
                or datetime_to_json(entry.occurred_at) != timestamp
                or entry.payload_json != payload_json
            ):
                raise IdempotencyConflictError(
                    f"journal record ID {record_id!r} was reused for different content"
                )
            return AppendResult(
                sequence=entry.sequence,
                record_hash=entry.record_hash,
                appended=False,
            )

        tail = connection.execute(
            "SELECT sequence, record_hash FROM journal_events ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        sequence = 1 if tail is None else cast(int, tail["sequence"]) + 1
        previous_hash = _GENESIS_HASH if tail is None else cast(str, tail["record_hash"])
        digest = _record_hash(
            previous_hash,
            sequence,
            record_id,
            intent_id,
            kind,
            timestamp,
            payload_json,
        )
        connection.execute(
            "INSERT INTO journal_events(sequence, record_id, intent_id, kind, occurred_at, "
            "payload_json, previous_hash, record_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                sequence,
                record_id,
                intent_id,
                kind.value,
                timestamp,
                payload_json,
                previous_hash,
                digest,
            ),
        )
        return AppendResult(sequence=sequence, record_hash=digest, appended=True)

    @classmethod
    def _state_in_connection(cls, connection: sqlite3.Connection) -> ExecutionJournalState:
        return replay_entries(cls._entries_in_connection(connection))

    def entries(self) -> tuple[JournalEntry, ...]:
        """Return all records after SQLite and hash-chain verification."""

        try:
            with closing(self._connect()) as connection:
                self._check_sqlite_integrity(connection)
                return self._entries_in_connection(connection)
        except (JournalCorruptionError, IdempotencyConflictError):
            raise
        except sqlite3.DatabaseError as exc:
            raise JournalCorruptionError("cannot read execution journal") from exc

    @classmethod
    def _reserve_intent_in_connection(
        cls,
        connection: sqlite3.Connection,
        intent: OrderIntent,
        idempotency_key: str,
    ) -> tuple[bool, AppendResult]:
        payload = intent_payload(intent, idempotency_key)
        payload_hash = sha256_text(payload)
        by_key = connection.execute(
            "SELECT intent_id, idempotency_key, payload_hash, payload_json, recorded_sequence "
            "FROM journal_intents WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        by_intent = connection.execute(
            "SELECT intent_id, idempotency_key, payload_hash, payload_json, recorded_sequence "
            "FROM journal_intents WHERE intent_id = ?",
            (intent.intent_id,),
        ).fetchone()
        existing = by_key if by_key is not None else by_intent
        if existing is not None:
            if (
                cast(str, existing["intent_id"]) != intent.intent_id
                or cast(str, existing["idempotency_key"]) != idempotency_key
                or cast(str, existing["payload_hash"]) != payload_hash
                or cast(str, existing["payload_json"]) != payload
            ):
                raise IdempotencyConflictError(
                    "intent ID or idempotency key was reused for different content"
                )
            sequence = cast(int, existing["recorded_sequence"])
            row = connection.execute(
                "SELECT record_hash FROM journal_events WHERE sequence = ?",
                (sequence,),
            ).fetchone()
            if row is None:
                raise JournalCorruptionError("intent index references a missing journal record")
            return False, AppendResult(sequence, cast(str, row["record_hash"]), False)

        append = cls._append_in_connection(
            connection,
            record_id=f"intent:{intent.intent_id}",
            intent_id=intent.intent_id,
            kind=JournalEventKind.INTENT_RECORDED,
            occurred_at=intent.created_at,
            payload_json=payload,
        )
        connection.execute(
            "INSERT INTO journal_intents(intent_id, idempotency_key, payload_hash, payload_json, "
            "recorded_sequence) VALUES (?, ?, ?, ?, ?)",
            (intent.intent_id, idempotency_key, payload_hash, payload, append.sequence),
        )
        return True, append
