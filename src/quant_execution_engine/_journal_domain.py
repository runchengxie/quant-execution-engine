# pyright: strict
"""Immutable domain types for the durable execution journal."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from types import MappingProxyType
from typing import cast

from .domain import Fill, OrderIntent, OrderStatus


class JournalError(RuntimeError):
    """Base class for durable journal failures."""


class JournalCorruptionError(JournalError):
    """Raised when database integrity, a hash chain, or a snapshot is invalid."""


class IdempotencyConflictError(JournalError):
    """Raised when an idempotency key or stable ID is reused for new content."""


class JournalInvariantError(JournalError):
    """Raised when valid records cannot form a coherent lifecycle."""


class _StringEnum(str, Enum):
    def __str__(self) -> str:
        return cast(str, self.value)


class JournalEventKind(_StringEnum):
    """Kinds persisted by the append-only journal."""

    INTENT_RECORDED = "INTENT_RECORDED"
    SUBMISSION_STARTED = "SUBMISSION_STARTED"
    SUBMISSION_UNCERTAIN = "SUBMISSION_UNCERTAIN"
    ORDER_EVENT_RECORDED = "ORDER_EVENT_RECORDED"
    FILL_RECORDED = "FILL_RECORDED"
    RECONCILIATION_RECORDED = "RECONCILIATION_RECORDED"


class SubmissionState(_StringEnum):
    """Conservative state derived from immutable lifecycle facts."""

    RECORDED = "RECORDED"
    SUBMISSION_UNCERTAIN = "SUBMISSION_UNCERTAIN"
    ACCEPTED = "ACCEPTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    FAILED = "FAILED"


TERMINAL_SUBMISSION_STATES = frozenset(
    {
        SubmissionState.FILLED,
        SubmissionState.CANCELLED,
        SubmissionState.REJECTED,
        SubmissionState.EXPIRED,
        SubmissionState.FAILED,
    }
)


def _aware_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _non_empty(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    return normalized


def _freeze_json_value(value: object, path: str) -> object:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} must be finite")
        return value
    if isinstance(value, Mapping):
        source = cast(Mapping[object, object], value)
        frozen: dict[str, object] = {}
        for key, item in source.items():
            if not isinstance(key, str):
                raise TypeError(f"{path} keys must be strings")
            frozen[key] = _freeze_json_value(item, f"{path}.{key}")
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        sequence = cast(list[object] | tuple[object, ...], value)
        return tuple(
            _freeze_json_value(item, f"{path}[{index}]") for index, item in enumerate(sequence)
        )
    raise TypeError(f"{path} contains a non-JSON value: {type(value).__name__}")


def _freeze_metadata(value: Mapping[str, object]) -> Mapping[str, object]:
    frozen = _freeze_json_value(value, "metadata")
    if not isinstance(frozen, Mapping):  # pragma: no cover - input type guarantees this
        raise TypeError("metadata must be a mapping")
    return cast(Mapping[str, object], frozen)


def _empty_metadata() -> Mapping[str, object]:
    return {}


@dataclass(frozen=True, slots=True)
class ReconciliationEvidence:
    """Immutable broker observation retained for later audit and replay."""

    evidence_id: str
    intent_id: str
    observed_at: datetime
    source: str
    observed_status: OrderStatus
    broker_order_id: str | None = None
    observed_filled_quantity: Decimal | None = None
    observed_remaining_quantity: Decimal | None = None
    message: str | None = None
    metadata: Mapping[str, object] = field(default_factory=_empty_metadata)

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_id", _non_empty(self.evidence_id, "evidence_id"))
        object.__setattr__(self, "intent_id", _non_empty(self.intent_id, "intent_id"))
        object.__setattr__(self, "source", _non_empty(self.source, "source"))
        object.__setattr__(self, "observed_at", _aware_utc(self.observed_at, "observed_at"))
        observed_status = cast(object, self.observed_status)
        if not isinstance(observed_status, OrderStatus):
            raise TypeError("observed_status must be OrderStatus")
        for field_name in ("observed_filled_quantity", "observed_remaining_quantity"):
            quantity = getattr(self, field_name)
            if quantity is not None:
                if not isinstance(quantity, Decimal):
                    raise TypeError(f"{field_name} must be Decimal")
                if not quantity.is_finite() or quantity < 0:
                    raise ValueError(f"{field_name} must be finite and non-negative")
        if self.broker_order_id is not None:
            object.__setattr__(
                self,
                "broker_order_id",
                _non_empty(self.broker_order_id, "broker_order_id"),
            )
        if self.message is not None:
            object.__setattr__(self, "message", self.message.strip() or None)
        object.__setattr__(self, "metadata", _freeze_metadata(self.metadata))


@dataclass(frozen=True, slots=True)
class JournalEntry:
    """One verified row in the global append-only hash chain."""

    sequence: int
    record_id: str
    intent_id: str
    kind: JournalEventKind
    occurred_at: datetime
    payload_json: str
    previous_hash: str
    record_hash: str

    def __post_init__(self) -> None:
        if self.sequence <= 0:
            raise ValueError("sequence must be positive")
        object.__setattr__(self, "record_id", _non_empty(self.record_id, "record_id"))
        object.__setattr__(self, "intent_id", _non_empty(self.intent_id, "intent_id"))
        object.__setattr__(self, "occurred_at", _aware_utc(self.occurred_at, "occurred_at"))


@dataclass(frozen=True, slots=True)
class AppendResult:
    """Result of an idempotent append operation."""

    sequence: int
    record_hash: str
    appended: bool


@dataclass(frozen=True, slots=True)
class SubmissionPreparation:
    """Durable permission for exactly one caller to invoke a broker transport."""

    intent_id: str
    idempotency_key: str
    attempt_id: str
    intent_created: bool
    should_submit: bool
    through_sequence: int


@dataclass(frozen=True, slots=True)
class IntentLifecycle:
    """Current lifecycle for one intent, derived only from journal records."""

    intent: OrderIntent
    idempotency_key: str
    submission_state: SubmissionState = SubmissionState.RECORDED
    order_status: OrderStatus | None = None
    broker_order_id: str | None = None
    filled_quantity: Decimal = Decimal("0")
    remaining_quantity: Decimal = Decimal("0")
    average_fill_price: Decimal | None = None
    last_sequence: int = 0
    submission_attempt_ids: tuple[str, ...] = ()
    order_event_ids: tuple[str, ...] = ()
    fills: tuple[Fill, ...] = ()
    reconciliation_evidence: tuple[ReconciliationEvidence, ...] = ()
    uncertainty_messages: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        intent = cast(object, self.intent)
        if not isinstance(intent, OrderIntent):
            raise TypeError("intent must be OrderIntent")
        object.__setattr__(
            self,
            "idempotency_key",
            _non_empty(self.idempotency_key, "idempotency_key"),
        )
        state = cast(object, self.submission_state)
        if not isinstance(state, SubmissionState):
            raise TypeError("submission_state must be SubmissionState")
        status = cast(object, self.order_status)
        if status is not None and not isinstance(status, OrderStatus):
            raise TypeError("order_status must be OrderStatus or None")
        for field_name in ("filled_quantity", "remaining_quantity"):
            quantity = cast(object, getattr(self, field_name))
            if not isinstance(quantity, Decimal):
                raise TypeError(f"{field_name} must be Decimal")
            if not quantity.is_finite() or quantity < 0:
                raise ValueError(f"{field_name} must be finite and non-negative")
        if self.average_fill_price is not None:
            average_fill_price = cast(object, self.average_fill_price)
            if not isinstance(average_fill_price, Decimal):
                raise TypeError("average_fill_price must be Decimal or None")
            if not average_fill_price.is_finite() or average_fill_price <= 0:
                raise ValueError("average_fill_price must be finite and positive")
        if self.last_sequence < 0:
            raise ValueError("last_sequence cannot be negative")
        if self.broker_order_id is not None:
            object.__setattr__(
                self,
                "broker_order_id",
                _non_empty(self.broker_order_id, "broker_order_id"),
            )
        fill_ids: set[str] = set()
        for fill in self.fills:
            fill_value = cast(object, fill)
            if not isinstance(fill_value, Fill):
                raise TypeError("fills entries must be Fill")
            if fill_value.intent_id != self.intent.intent_id:
                raise ValueError("fill intent_id must match lifecycle intent_id")
            if fill_value.fill_id in fill_ids:
                raise ValueError("fill IDs must be unique within a lifecycle")
            fill_ids.add(fill_value.fill_id)
        evidence_ids: set[str] = set()
        for evidence in self.reconciliation_evidence:
            evidence_value = cast(object, evidence)
            if not isinstance(evidence_value, ReconciliationEvidence):
                raise TypeError("reconciliation_evidence entries must be ReconciliationEvidence")
            if evidence_value.intent_id != self.intent.intent_id:
                raise ValueError("evidence intent_id must match lifecycle intent_id")
            if evidence_value.evidence_id in evidence_ids:
                raise ValueError("evidence IDs must be unique within a lifecycle")
            evidence_ids.add(evidence_value.evidence_id)

    @property
    def is_terminal(self) -> bool:
        return self.submission_state in TERMINAL_SUBMISSION_STATES

    @property
    def requires_reconciliation(self) -> bool:
        return self.submission_state is SubmissionState.SUBMISSION_UNCERTAIN


def _empty_intents() -> Mapping[str, IntentLifecycle]:
    return {}


@dataclass(frozen=True, slots=True)
class ExecutionJournalState:
    """Frozen global state reconstructed from a snapshot plus later records."""

    through_sequence: int = 0
    intents: Mapping[str, IntentLifecycle] = field(default_factory=_empty_intents)

    def __post_init__(self) -> None:
        if self.through_sequence < 0:
            raise ValueError("through_sequence cannot be negative")
        for intent_id, lifecycle in self.intents.items():
            if intent_id != lifecycle.intent.intent_id:
                raise ValueError("journal state key must match lifecycle intent_id")
            if lifecycle.last_sequence > self.through_sequence:
                raise ValueError("lifecycle sequence cannot exceed journal state sequence")
        object.__setattr__(self, "intents", MappingProxyType(dict(self.intents)))


@dataclass(frozen=True, slots=True)
class SnapshotInfo:
    """Metadata for an immutable materialized replay checkpoint."""

    snapshot_id: str
    through_sequence: int
    state_hash: str
    created_at: datetime
