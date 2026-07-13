# pyright: strict
"""Deterministic in-memory execution transport for offline qexec runs."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from threading import RLock

from .domain import (
    ExecutionCapabilities,
    ExecutionEventType,
    Fill,
    OrderEvent,
    OrderStatus,
    OrderType,
    TimeInForce,
    validate_order_intent_capabilities,
)
from .transport import (
    TransportCancellation,
    TransportCapabilities,
    TransportEventBatch,
    TransportOrderNotFoundError,
    TransportOrderReference,
    TransportSubmission,
    TransportSubmitRequest,
    validate_transport_route,
)


@dataclass(slots=True)
class _PaperOrder:
    reference: TransportOrderReference
    submitted_event: OrderEvent
    latest_event: OrderEvent
    fills: list[Fill] = field(default_factory=list)


class InMemoryPaperExecutionTransport:
    """A no-network transport with explicit simulated fill injection.

    Submissions are acknowledged but never auto-filled.  Tests or an offline
    simulator can call :meth:`record_fill`; every subsequent query/poll returns
    the same stable fact IDs so the durable journal can deduplicate them.
    """

    def __init__(self, *, backend_name: str = "memory-paper") -> None:
        normalized = backend_name.strip()
        if not normalized:
            raise ValueError("backend_name cannot be empty")
        self._backend_name = normalized
        self._orders: dict[str, _PaperOrder] = {}
        self._client_index: dict[str, str] = {}
        self._lock = RLock()
        self._capabilities = TransportCapabilities(
            backend_name=normalized,
            execution=ExecutionCapabilities(
                supports_short=True,
                supports_fractional=True,
                supported_order_types=frozenset(OrderType),
                supported_time_in_force=frozenset(TimeInForce),
            ),
            supports_submit=True,
            supports_cancel=True,
            supports_query=True,
            supports_event_poll=True,
            supports_fill_poll=True,
            supports_client_order_lookup=True,
            notes=("mode=offline", "fills=explicit"),
        )

    def discover_capabilities(self) -> TransportCapabilities:
        return self._capabilities

    def _broker_order_id(self, intent_id: str) -> str:
        digest = hashlib.sha256(f"{self._backend_name}\0{intent_id}".encode()).hexdigest()[:20]
        return f"paper-{digest}"

    def submit(self, request: TransportSubmitRequest) -> TransportSubmission:
        intent = request.intent
        validate_transport_route(intent, self._capabilities)
        validate_order_intent_capabilities(intent, self._capabilities.execution)
        broker_order_id = self._broker_order_id(intent.intent_id)
        reference = TransportOrderReference(
            intent_id=intent.intent_id,
            instrument=intent.instrument,
            account_label=intent.account_label,
            broker_order_id=broker_order_id,
            client_order_id=request.client_order_id,
            side=intent.side,
            quantity=intent.quantity,
        )
        event = OrderEvent(
            event_id=f"paper-submit-{broker_order_id}",
            event_type=ExecutionEventType.ORDER_ACKNOWLEDGED,
            occurred_at=intent.created_at,
            instrument=intent.instrument,
            status=OrderStatus.ACCEPTED,
            broker_name=self._backend_name,
            account_label=intent.account_label,
            broker_order_id=broker_order_id,
            intent_id=intent.intent_id,
            client_order_id=request.client_order_id,
            side=intent.side,
            quantity=intent.quantity,
            filled_quantity=Decimal("0"),
            remaining_quantity=intent.quantity,
            metadata={"mode": "offline"},
        )
        with self._lock:
            existing = self._orders.get(broker_order_id)
            if existing is not None:
                if existing.reference != reference:
                    raise RuntimeError("paper broker order ID collision")
                return TransportSubmission(
                    reference=existing.reference,
                    order_event=existing.submitted_event,
                    fills=tuple(existing.fills),
                )
            self._orders[broker_order_id] = _PaperOrder(reference, event, event)
            if request.client_order_id is not None:
                self._client_index[request.client_order_id] = broker_order_id
        return TransportSubmission(reference=reference, order_event=event)

    def _resolve(self, reference: TransportOrderReference) -> _PaperOrder:
        broker_order_id = reference.broker_order_id
        with self._lock:
            if broker_order_id is None and reference.client_order_id is not None:
                broker_order_id = self._client_index.get(reference.client_order_id)
            order = self._orders.get(broker_order_id or "")
            if order is None:
                raise TransportOrderNotFoundError(
                    f"{self._backend_name} has no order for intent {reference.intent_id!r}"
                )
            if order.reference.intent_id != reference.intent_id:
                raise TransportOrderNotFoundError("order reference does not match intent_id")
            return order

    def query(self, reference: TransportOrderReference) -> TransportEventBatch:
        with self._lock:
            order = self._resolve(reference)
            return TransportEventBatch(
                reference=order.reference,
                order_events=(order.latest_event,),
                fills=tuple(order.fills),
            )

    def poll(self, reference: TransportOrderReference) -> TransportEventBatch:
        return self.query(reference)

    def cancel(self, reference: TransportOrderReference) -> TransportCancellation:
        with self._lock:
            order = self._resolve(reference)
            latest = order.latest_event
            if latest.status in {
                OrderStatus.FILLED,
                OrderStatus.CANCELLED,
                OrderStatus.REJECTED,
                OrderStatus.EXPIRED,
            }:
                return TransportCancellation(
                    reference=order.reference,
                    accepted=False,
                    order_event=latest,
                )
            occurred_at = datetime.now(timezone.utc)
            event = OrderEvent(
                event_id=f"paper-cancel-{order.reference.broker_order_id}",
                event_type=ExecutionEventType.CANCELLED,
                occurred_at=occurred_at,
                instrument=order.reference.instrument,
                status=OrderStatus.CANCELLED,
                broker_name=self._backend_name,
                account_label=order.reference.account_label,
                broker_order_id=order.reference.broker_order_id or "unresolved",
                intent_id=order.reference.intent_id,
                client_order_id=order.reference.client_order_id,
                side=order.reference.side,
                quantity=order.reference.quantity,
                filled_quantity=sum((item.quantity for item in order.fills), Decimal("0")),
                remaining_quantity=self._remaining(order),
                metadata={"mode": "offline"},
            )
            order.latest_event = event
            return TransportCancellation(
                reference=order.reference,
                accepted=True,
                requested_at=occurred_at,
                order_event=event,
            )

    @staticmethod
    def _remaining(order: _PaperOrder) -> Decimal | None:
        quantity = order.reference.quantity
        if quantity is None:
            return None
        filled = sum((item.quantity for item in order.fills), Decimal("0"))
        return max(Decimal("0"), quantity - filled)

    def record_fill(
        self,
        reference: TransportOrderReference,
        *,
        fill_id: str,
        quantity: Decimal,
        price: Decimal,
        filled_at: datetime,
    ) -> Fill:
        """Inject a deterministic paper fill for an offline simulator."""

        with self._lock:
            order = self._resolve(reference)
            if quantity <= 0 or price <= 0:
                raise ValueError("paper fill quantity and price must be positive")
            fill = Fill(
                fill_id=fill_id,
                broker_order_id=order.reference.broker_order_id or "unresolved",
                instrument=order.reference.instrument,
                quantity=quantity,
                price=price,
                filled_at=filled_at,
                broker_name=self._backend_name,
                account_label=order.reference.account_label,
                intent_id=order.reference.intent_id,
                side=order.reference.side,
                metadata={"mode": "offline"},
            )
            duplicate = next((item for item in order.fills if item.fill_id == fill_id), None)
            if duplicate is not None:
                if duplicate != fill:
                    raise ValueError("paper fill_id was reused for different content")
                return duplicate
            remaining = self._remaining(order)
            if remaining is not None and quantity > remaining:
                raise ValueError("paper fill exceeds remaining quantity")
            order.fills.append(fill)
            total_filled = sum((item.quantity for item in order.fills), Decimal("0"))
            remaining_after = self._remaining(order)
            is_filled = remaining_after == 0
            weighted_notional = sum(
                (item.quantity * item.price for item in order.fills), Decimal("0")
            )
            average = weighted_notional / total_filled
            order.latest_event = OrderEvent(
                event_id=f"paper-fill-event-{fill_id}",
                event_type=(
                    ExecutionEventType.FILLED if is_filled else ExecutionEventType.PARTIALLY_FILLED
                ),
                occurred_at=fill.filled_at,
                instrument=order.reference.instrument,
                status=OrderStatus.FILLED if is_filled else OrderStatus.PARTIALLY_FILLED,
                broker_name=self._backend_name,
                account_label=order.reference.account_label,
                broker_order_id=order.reference.broker_order_id or "unresolved",
                intent_id=order.reference.intent_id,
                client_order_id=order.reference.client_order_id,
                side=order.reference.side,
                quantity=order.reference.quantity,
                filled_quantity=total_filled,
                remaining_quantity=remaining_after,
                average_fill_price=average,
                metadata={"mode": "offline", "latest_fill_id": fill_id},
            )
            return fill

    def close(self) -> None:
        """The in-memory transport has no external resource to release."""


__all__ = ["InMemoryPaperExecutionTransport"]
