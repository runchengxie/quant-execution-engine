# pyright: strict
"""Framework-neutral execution transport contracts.

Transport implementations only translate and move approved :class:`OrderIntent`
objects.  They do not run approval, policy, preflight, or risk decisions.  A
submit request can only be constructed from the one-shot durable permission
returned by :meth:`DurableExecutionJournal.prepare_submission`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Protocol, cast, runtime_checkable

from .domain import ExecutionCapabilities, Fill, InstrumentId, OrderEvent, OrderIntent, OrderSide
from .execution_journal import SubmissionPreparation


class ExecutionTransportError(RuntimeError):
    """Base error raised at the mechanical execution boundary."""


class UnsupportedTransportCapabilityError(ExecutionTransportError):
    """Raised when a transport operation is not declared as supported."""


class TransportMappingError(ExecutionTransportError):
    """Raised when a framework or broker record cannot be mapped safely."""


class TransportOrderNotFoundError(ExecutionTransportError):
    """Raised when an order reference cannot be resolved by a transport."""


class SubmissionOutcomeUnknownError(ExecutionTransportError):
    """Raised after a submit call whose broker-side outcome is unknown."""

    def __init__(self, intent_id: str, attempt_id: str, reason: str) -> None:
        self.intent_id = intent_id
        self.attempt_id = attempt_id
        self.reason = reason
        super().__init__(
            f"submission outcome is unknown for intent {intent_id!r} "
            f"(attempt {attempt_id!r}): {reason}"
        )


@dataclass(frozen=True, slots=True)
class TransportCapabilities:
    """Discoverable operations and value capabilities for one transport."""

    backend_name: str
    execution: ExecutionCapabilities
    supports_submit: bool = False
    supports_cancel: bool = False
    supports_query: bool = False
    supports_event_poll: bool = False
    supports_fill_poll: bool = False
    supports_client_order_lookup: bool = False
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.backend_name.strip():
            raise ValueError("backend_name cannot be empty")
        if not isinstance(cast(object, self.execution), ExecutionCapabilities):
            raise TypeError("execution must be ExecutionCapabilities")


@dataclass(frozen=True, slots=True)
class TransportSubmitRequest:
    """One mechanically executable intent carrying its durable permit."""

    intent: OrderIntent
    preparation: SubmissionPreparation
    client_order_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(cast(object, self.intent), OrderIntent):
            raise TypeError("intent must be OrderIntent")
        if not isinstance(cast(object, self.preparation), SubmissionPreparation):
            raise TypeError("preparation must be SubmissionPreparation")
        if not self.preparation.should_submit:
            raise ValueError("transport submit requires a one-shot should_submit permission")
        if self.preparation.intent_id != self.intent.intent_id:
            raise ValueError("submission permission does not belong to this intent")
        client_order_id = self.client_order_id or self.intent.intent_id
        if not client_order_id.strip():
            raise ValueError("client_order_id cannot be empty")
        object.__setattr__(self, "client_order_id", client_order_id.strip())


@dataclass(frozen=True, slots=True)
class TransportOrderReference:
    """Stable context needed to query or cancel an order without SDK types."""

    intent_id: str
    instrument: InstrumentId
    account_label: str
    broker_order_id: str | None = None
    client_order_id: str | None = None
    side: OrderSide | None = None
    quantity: Decimal | None = None

    def __post_init__(self) -> None:
        if not self.intent_id.strip():
            raise ValueError("intent_id cannot be empty")
        if not isinstance(cast(object, self.instrument), InstrumentId):
            raise TypeError("instrument must be InstrumentId")
        if not self.account_label.strip():
            raise ValueError("account_label cannot be empty")
        broker_order_id = self.broker_order_id.strip() if self.broker_order_id else None
        client_order_id = self.client_order_id.strip() if self.client_order_id else None
        if broker_order_id is None and client_order_id is None:
            raise ValueError("broker_order_id or client_order_id is required")
        if self.side is not None and not isinstance(cast(object, self.side), OrderSide):
            raise TypeError("side must be OrderSide or None")
        if self.quantity is not None:
            if not isinstance(cast(object, self.quantity), Decimal):
                raise TypeError("quantity must be Decimal or None")
            if not self.quantity.is_finite() or self.quantity <= 0:
                raise ValueError("quantity must be finite and positive")
        object.__setattr__(self, "intent_id", self.intent_id.strip())
        object.__setattr__(self, "account_label", self.account_label.strip())
        object.__setattr__(self, "broker_order_id", broker_order_id)
        object.__setattr__(self, "client_order_id", client_order_id)

    @classmethod
    def from_intent(cls, intent: OrderIntent) -> TransportOrderReference:
        """Build the reference available even when a submit response was lost."""

        return cls(
            intent_id=intent.intent_id,
            instrument=intent.instrument,
            account_label=intent.account_label,
            client_order_id=intent.intent_id,
            side=intent.side,
            quantity=intent.quantity,
        )


@dataclass(frozen=True, slots=True)
class TransportSubmission:
    """Normalized synchronous facts returned by a submit operation."""

    reference: TransportOrderReference
    order_event: OrderEvent
    fills: tuple[Fill, ...] = ()

    def __post_init__(self) -> None:
        if self.order_event.intent_id != self.reference.intent_id:
            raise ValueError("submission event intent_id must match its reference")
        for fill in self.fills:
            if fill.intent_id != self.reference.intent_id:
                raise ValueError("submission fill intent_id must match its reference")


@dataclass(frozen=True, slots=True)
class TransportCancellation:
    """Mechanical cancellation acknowledgement and optional observed event."""

    reference: TransportOrderReference
    accepted: bool
    requested_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    order_event: OrderEvent | None = None

    def __post_init__(self) -> None:
        if self.requested_at.tzinfo is None or self.requested_at.utcoffset() is None:
            raise ValueError("requested_at must be timezone-aware")
        object.__setattr__(self, "requested_at", self.requested_at.astimezone(timezone.utc))
        if self.order_event is not None and self.order_event.intent_id != self.reference.intent_id:
            raise ValueError("cancellation event intent_id must match its reference")


@dataclass(frozen=True, slots=True)
class TransportEventBatch:
    """Idempotent order and fill facts returned by query or polling."""

    reference: TransportOrderReference
    order_events: tuple[OrderEvent, ...] = ()
    fills: tuple[Fill, ...] = ()

    def __post_init__(self) -> None:
        for event in self.order_events:
            if event.intent_id != self.reference.intent_id:
                raise ValueError("polled event intent_id must match its reference")
        for fill in self.fills:
            if fill.intent_id != self.reference.intent_id:
                raise ValueError("polled fill intent_id must match its reference")


def validate_transport_route(
    intent: OrderIntent,
    capabilities: TransportCapabilities,
) -> None:
    """Fail before submission when an intent targets another backend."""

    if intent.broker_name != capabilities.backend_name:
        raise TransportMappingError(
            f"intent broker {intent.broker_name!r} does not match transport "
            f"{capabilities.backend_name!r}"
        )


@runtime_checkable
class ExecutionTransport(Protocol):
    """Mechanical submit/cancel/query/poll port implemented by runtimes."""

    def discover_capabilities(self) -> TransportCapabilities:
        """Return capabilities without performing a broker operation."""
        ...

    def submit(self, request: TransportSubmitRequest) -> TransportSubmission:
        """Submit exactly one durably permitted order intent."""
        ...

    def cancel(self, reference: TransportOrderReference) -> TransportCancellation:
        """Request cancellation or fail explicitly when unsupported."""
        ...

    def query(self, reference: TransportOrderReference) -> TransportEventBatch:
        """Fetch the current broker facts for one order."""
        ...

    def poll(self, reference: TransportOrderReference) -> TransportEventBatch:
        """Poll normalized callback/fill facts for one order."""
        ...

    def close(self) -> None:
        """Release runtime resources."""


__all__ = [
    "ExecutionTransport",
    "ExecutionTransportError",
    "SubmissionOutcomeUnknownError",
    "TransportCancellation",
    "TransportCapabilities",
    "TransportEventBatch",
    "TransportMappingError",
    "TransportOrderNotFoundError",
    "TransportOrderReference",
    "TransportSubmission",
    "TransportSubmitRequest",
    "UnsupportedTransportCapabilityError",
    "validate_transport_route",
]
