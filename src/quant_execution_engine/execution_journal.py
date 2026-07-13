# pyright: strict
"""Public framework-neutral API for durable execution lifecycle facts.

This module is additive.  The current CLI and its version-1 JSON state store
remain unchanged until a later compatibility adapter has broker parity and
recovery evidence.
"""

from __future__ import annotations

from ._journal_domain import (
    TERMINAL_SUBMISSION_STATES,
    AppendResult,
    ExecutionJournalState,
    IdempotencyConflictError,
    IntentLifecycle,
    JournalCorruptionError,
    JournalEntry,
    JournalError,
    JournalEventKind,
    JournalInvariantError,
    ReconciliationEvidence,
    SnapshotInfo,
    SubmissionPreparation,
    SubmissionState,
)
from ._journal_reducer import reduce_entry, replay_entries
from ._journal_sqlite import DurableExecutionJournal

__all__ = [
    "AppendResult",
    "DurableExecutionJournal",
    "ExecutionJournalState",
    "IdempotencyConflictError",
    "IntentLifecycle",
    "JournalCorruptionError",
    "JournalEntry",
    "JournalError",
    "JournalEventKind",
    "JournalInvariantError",
    "ReconciliationEvidence",
    "SnapshotInfo",
    "SubmissionPreparation",
    "SubmissionState",
    "TERMINAL_SUBMISSION_STATES",
    "reduce_entry",
    "replay_entries",
]
