# pyright: strict
"""Mechanical adapter from existing qexec brokers to the transport port."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal

from .broker.base import (
    BrokerAdapter,
    BrokerFillRecord,
    BrokerOrderRecord,
    BrokerOrderRequest,
    ResolvedBrokerAccount,
)
from .domain import (
    ExecutionCapabilities,
    ExecutionEventType,
    Fill,
    OrderEvent,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
    validate_order_intent_capabilities,
)
from .transport import (
    TransportCancellation,
    TransportCapabilities,
    TransportEventBatch,
    TransportMappingError,
    TransportOrderNotFoundError,
    TransportOrderReference,
    TransportSubmission,
    TransportSubmitRequest,
    UnsupportedTransportCapabilityError,
    validate_transport_route,
)


def _decimal(value: float) -> Decimal:
    return Decimal(str(value))


def _optional_decimal(value: float | None) -> Decimal | None:
    return _decimal(value) if value is not None else None


def _timestamp(value: str) -> datetime:
    normalized = value.strip()
    if not normalized:
        raise TransportMappingError("broker timestamp cannot be empty")
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError as exc:
        raise TransportMappingError(f"broker timestamp is not ISO-8601: {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise TransportMappingError(f"broker timestamp is not timezone-aware: {value!r}")
    return parsed.astimezone(timezone.utc)


def _status(value: str) -> OrderStatus:
    normalized = value.strip().upper().replace("CANCELED", "CANCELLED")
    try:
        return OrderStatus(normalized)
    except ValueError:
        return OrderStatus.UNKNOWN


def _event_type(status: OrderStatus) -> ExecutionEventType:
    return {
        OrderStatus.ACCEPTED: ExecutionEventType.ORDER_ACKNOWLEDGED,
        OrderStatus.PARTIALLY_FILLED: ExecutionEventType.PARTIALLY_FILLED,
        OrderStatus.FILLED: ExecutionEventType.FILLED,
        OrderStatus.CANCELLED: ExecutionEventType.CANCELLED,
        OrderStatus.REJECTED: ExecutionEventType.REJECTED,
        OrderStatus.EXPIRED: ExecutionEventType.EXPIRED,
        OrderStatus.FAILED: ExecutionEventType.FAILED,
    }.get(status, ExecutionEventType.ORDER_UPDATED)


def _stable_id(prefix: str, values: tuple[object, ...]) -> str:
    payload = json.dumps(values, ensure_ascii=True, separators=(",", ":"), default=str)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}-{digest}"


def _side(value: str, fallback: OrderSide | None) -> OrderSide | None:
    try:
        return OrderSide(value.strip().upper())
    except ValueError:
        return fallback


def _record_to_event(
    record: BrokerOrderRecord,
    reference: TransportOrderReference,
) -> OrderEvent:
    status = _status(record.status)
    occurred_at = _timestamp(record.updated_at or record.submitted_at)
    side = _side(record.side, reference.side)
    event_id = _stable_id(
        "broker-order-event",
        (
            record.broker_name,
            record.account_label,
            record.broker_order_id,
            record.client_order_id,
            record.status,
            record.quantity,
            record.filled_quantity,
            record.remaining_quantity,
            record.avg_fill_price,
            record.updated_at,
        ),
    )
    return OrderEvent(
        event_id=event_id,
        event_type=_event_type(status),
        occurred_at=occurred_at,
        instrument=reference.instrument,
        status=status,
        broker_name=record.broker_name,
        account_label=record.account_label,
        broker_order_id=record.broker_order_id,
        intent_id=reference.intent_id,
        client_order_id=record.client_order_id or reference.client_order_id,
        side=side,
        quantity=_decimal(record.quantity),
        filled_quantity=_decimal(record.filled_quantity),
        remaining_quantity=_optional_decimal(record.remaining_quantity),
        average_fill_price=_optional_decimal(record.avg_fill_price),
        message=record.message,
        metadata={
            "source": "qexec-broker-adapter",
            "broker_status": record.status,
            "broker_updated_at": record.updated_at,
        },
    )


def _record_to_fill(record: BrokerFillRecord, reference: TransportOrderReference) -> Fill:
    return Fill(
        fill_id=record.fill_id,
        broker_order_id=record.broker_order_id,
        instrument=reference.instrument,
        quantity=_decimal(record.quantity),
        price=_decimal(record.price),
        filled_at=_timestamp(record.filled_at),
        broker_name=record.broker_name,
        account_label=record.account_label,
        intent_id=reference.intent_id,
        side=reference.side,
        metadata={"source": "qexec-broker-adapter"},
    )


def _execution_capabilities(adapter: BrokerAdapter) -> ExecutionCapabilities:
    matrix = adapter.capabilities
    try:
        order_types = frozenset(OrderType(item) for item in matrix.supported_order_types)
        time_in_force = frozenset(TimeInForce(item) for item in matrix.supported_time_in_force)
    except ValueError as exc:
        raise TransportMappingError(
            f"{adapter.backend_name} declares an unknown order capability"
        ) from exc
    return ExecutionCapabilities(
        supports_short=matrix.supports_short,
        supports_fractional=matrix.supports_fractional,
        supported_order_types=order_types,
        supported_time_in_force=time_in_force,
    )


class BrokerAdapterExecutionTransport:
    """Expose existing paper/direct broker adapters through the typed port.

    This adapter performs no approval, policy, preflight, or risk evaluation.
    It deliberately keeps the legacy adapters intact so the v1 CLI remains the
    default path while the durable transport path accumulates parity evidence.
    """

    def __init__(self, adapter: BrokerAdapter) -> None:
        self._adapter = adapter
        self._capabilities = self._build_capabilities()

    def _build_capabilities(self) -> TransportCapabilities:
        matrix = self._adapter.capabilities
        notes = [f"{key}={value}" for key, value in sorted(matrix.notes.items())]
        if matrix.supports_order_history:
            notes.append("client_order_lookup_scope=history")
        elif matrix.supports_open_order_listing:
            notes.append("client_order_lookup_scope=open-orders-only")
        submit_mode = str(matrix.notes.get("submit_mode", "")).strip().lower()
        return TransportCapabilities(
            backend_name=self._adapter.backend_name,
            execution=_execution_capabilities(self._adapter),
            supports_submit=(matrix.supports_live_submit or submit_mode == "paper"),
            supports_cancel=matrix.supports_cancel,
            supports_query=matrix.supports_order_query,
            supports_event_poll=matrix.supports_order_query,
            supports_fill_poll=matrix.supports_order_query,
            supports_client_order_lookup=(
                matrix.supports_open_order_listing or matrix.supports_order_history
            ),
            notes=tuple(notes),
        )

    def discover_capabilities(self) -> TransportCapabilities:
        return self._capabilities

    def submit(self, request: TransportSubmitRequest) -> TransportSubmission:
        capabilities = self.discover_capabilities()
        if not capabilities.supports_submit:
            raise UnsupportedTransportCapabilityError(
                f"{capabilities.backend_name} does not support transport submission"
            )
        intent = request.intent
        validate_transport_route(intent, capabilities)
        validate_order_intent_capabilities(intent, capabilities.execution)
        account = self._adapter.resolve_account(intent.account_label)
        record = self._adapter.submit_order(
            BrokerOrderRequest(
                symbol=intent.instrument.legacy_symbol,
                quantity=float(intent.quantity),
                side=intent.side.value,
                order_type=intent.order_type.value,
                limit_price=float(intent.limit_price) if intent.limit_price is not None else None,
                time_in_force=intent.time_in_force.value,
                client_order_id=request.client_order_id,
                account=account,
            )
        )
        reference = TransportOrderReference(
            intent_id=intent.intent_id,
            instrument=intent.instrument,
            account_label=account.label,
            broker_order_id=record.broker_order_id,
            client_order_id=record.client_order_id or request.client_order_id,
            side=intent.side,
            quantity=intent.quantity,
        )
        event = _record_to_event(record, reference)
        fills = self._fills(reference, account)
        return TransportSubmission(reference=reference, order_event=event, fills=fills)

    def _resolve_record(
        self,
        reference: TransportOrderReference,
    ) -> tuple[BrokerOrderRecord, ResolvedBrokerAccount]:
        capabilities = self.discover_capabilities()
        if not capabilities.supports_query:
            raise UnsupportedTransportCapabilityError(
                f"{capabilities.backend_name} does not support order query"
            )
        account = self._adapter.resolve_account(reference.account_label)
        if reference.broker_order_id is not None:
            return self._adapter.get_order(reference.broker_order_id, account), account
        if not capabilities.supports_client_order_lookup:
            raise UnsupportedTransportCapabilityError(
                f"{capabilities.backend_name} cannot query by client_order_id"
            )
        records: list[BrokerOrderRecord] = []
        if self._adapter.capabilities.supports_open_order_listing:
            records.extend(self._adapter.list_open_orders(account))
        if self._adapter.capabilities.supports_order_history:
            records.extend(self._adapter.list_order_history(account))
        matches = [
            record for record in records if record.client_order_id == reference.client_order_id
        ]
        if not matches:
            raise TransportOrderNotFoundError(
                f"{capabilities.backend_name} has no order for client_order_id "
                f"{reference.client_order_id!r}"
            )
        matches.sort(key=lambda item: (item.updated_at, item.broker_order_id))
        return matches[-1], account

    def _fills(
        self,
        reference: TransportOrderReference,
        account: ResolvedBrokerAccount,
    ) -> tuple[Fill, ...]:
        if reference.broker_order_id is None:
            return ()
        records = self._adapter.list_fills(
            account,
            broker_order_id=reference.broker_order_id,
        )
        return tuple(_record_to_fill(record, reference) for record in records)

    def query(self, reference: TransportOrderReference) -> TransportEventBatch:
        record, account = self._resolve_record(reference)
        resolved_reference = TransportOrderReference(
            intent_id=reference.intent_id,
            instrument=reference.instrument,
            account_label=account.label,
            broker_order_id=record.broker_order_id,
            client_order_id=record.client_order_id or reference.client_order_id,
            side=reference.side,
            quantity=reference.quantity,
        )
        return TransportEventBatch(
            reference=resolved_reference,
            order_events=(_record_to_event(record, resolved_reference),),
            fills=self._fills(resolved_reference, account),
        )

    def poll(self, reference: TransportOrderReference) -> TransportEventBatch:
        if not self.discover_capabilities().supports_event_poll:
            raise UnsupportedTransportCapabilityError(
                f"{self._adapter.backend_name} does not support event polling"
            )
        return self.query(reference)

    def cancel(self, reference: TransportOrderReference) -> TransportCancellation:
        if not self.discover_capabilities().supports_cancel:
            raise UnsupportedTransportCapabilityError(
                f"{self._adapter.backend_name} does not support cancellation"
            )
        record, account = self._resolve_record(reference)
        self._adapter.cancel_order(record.broker_order_id, account)
        resolved_reference = TransportOrderReference(
            intent_id=reference.intent_id,
            instrument=reference.instrument,
            account_label=account.label,
            broker_order_id=record.broker_order_id,
            client_order_id=record.client_order_id or reference.client_order_id,
            side=reference.side,
            quantity=reference.quantity,
        )
        event: OrderEvent | None = None
        try:
            refreshed = self._adapter.get_order(record.broker_order_id, account)
            event = _record_to_event(refreshed, resolved_reference)
        except Exception:
            # A broker accepting cancel does not imply it already exposes the
            # resulting state.  The caller must poll/reconcile rather than
            # fabricate a cancellation fact.
            event = None
        return TransportCancellation(
            reference=resolved_reference,
            accepted=True,
            order_event=event,
        )

    def close(self) -> None:
        self._adapter.close()


def transport_for_broker(adapter: BrokerAdapter) -> BrokerAdapterExecutionTransport:
    """Return the additive typed transport wrapper for an existing adapter."""

    return BrokerAdapterExecutionTransport(adapter)


__all__ = ["BrokerAdapterExecutionTransport", "transport_for_broker"]
