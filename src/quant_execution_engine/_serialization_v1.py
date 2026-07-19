"""Explicit readers and compatibility writers for legacy execution payloads."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import timezone, tzinfo
from decimal import Decimal

from ._serialization_common import (
    WireFormatError,
    datetime_to_wire,
    enum_value,
    instrument_from_legacy,
    legacy_decimal,
    metadata_to_wire,
    migrate_legacy_datetime,
    optional_bool,
    optional_legacy_decimal,
    optional_string,
    required_string,
    required_value,
    wire_mapping,
)
from .domain import (
    ExecutionEventType,
    Fill,
    OrderEvent,
    OrderIntent,
    OrderSide,
    OrderStatus,
    OrderType,
    PortfolioTarget,
    TimeInForce,
)

_STATUS_ALIASES = {
    "CANCELED": OrderStatus.CANCELLED,
    "CANCELLED": OrderStatus.CANCELLED,
}


def portfolio_target_from_v1(
    value: object,
    *,
    as_of: object | None = None,
    portfolio_id: str = "default",
    source: str | None = None,
    default_market: str = "US",
    naive_timezone: tzinfo = timezone.utc,
) -> PortfolioTarget:
    """Migrate one legacy ``TargetEntry`` mapping into a portfolio target."""

    payload = wire_mapping(value, "legacy portfolio target")
    timestamp = as_of if as_of is not None else payload.get("asof")
    if timestamp is None:
        raise WireFormatError("legacy portfolio target requires an as_of value")
    target_weight = optional_legacy_decimal(payload, "target_weight")
    target_quantity = optional_legacy_decimal(payload, "target_quantity")
    return PortfolioTarget(
        instrument=instrument_from_legacy(
            required_value(payload, "symbol"),
            payload.get("market"),
            currency=payload.get("currency"),
            default_market=default_market,
        ),
        portfolio_id=portfolio_id,
        as_of=migrate_legacy_datetime(
            timestamp,
            "as_of",
            naive_timezone=naive_timezone,
        ),
        target_weight=target_weight,
        target_quantity=target_quantity,
        source=source or optional_string(payload, "source"),
        notes=optional_string(payload, "notes"),
        metadata=wire_mapping(payload.get("metadata", {}), "legacy metadata"),
    )


def portfolio_target_to_v1(target: PortfolioTarget) -> dict[str, object]:
    """Return the current ``TargetEntry``-compatible shape."""

    symbol = target.instrument.symbol
    if target.instrument.exchange:
        symbol = f"{symbol}.{target.instrument.exchange}"
    payload: dict[str, object] = {
        "symbol": symbol,
        "market": target.instrument.market,
    }
    if target.target_weight is not None:
        payload["target_weight"] = float(target.target_weight)
    if target.target_quantity is not None:
        payload["target_quantity"] = float(target.target_quantity)
    if target.notes:
        payload["notes"] = target.notes
    if target.metadata:
        payload["metadata"] = metadata_to_wire(target.metadata)
    return payload


def order_intent_from_v1(
    value: object,
    *,
    naive_timezone: tzinfo = timezone.utc,
) -> OrderIntent:
    """Migrate a persisted v1 ``execution_state.OrderIntent`` mapping."""

    payload = wire_mapping(value, "legacy order intent")
    target_as_of_value = payload.get("target_asof")
    target_as_of = (
        migrate_legacy_datetime(
            target_as_of_value,
            "target_asof",
            naive_timezone=naive_timezone,
        )
        if target_as_of_value is not None
        else None
    )
    return OrderIntent(
        intent_id=required_string(payload, "intent_id"),
        instrument=instrument_from_legacy(
            required_value(payload, "symbol"),
            payload.get("market"),
            currency=payload.get("currency"),
        ),
        side=enum_value(OrderSide, required_value(payload, "side"), "side"),
        quantity=legacy_decimal(required_value(payload, "quantity"), "quantity"),
        order_type=enum_value(OrderType, required_value(payload, "order_type"), "order_type"),
        created_at=migrate_legacy_datetime(
            required_value(payload, "created_at"),
            "created_at",
            naive_timezone=naive_timezone,
        ),
        limit_price=optional_legacy_decimal(payload, "limit_price"),
        time_in_force=enum_value(
            TimeInForce,
            payload.get("time_in_force", TimeInForce.DAY.value),
            "time_in_force",
        ),
        opens_short=optional_bool(payload, "opens_short"),
        approval_id=optional_string(payload, "approval_id"),
        broker_name=optional_string(payload, "broker_name"),
        account_label=str(payload.get("account_label") or "main"),
        run_id=optional_string(payload, "run_id"),
        target_source=optional_string(payload, "target_source"),
        target_as_of=target_as_of,
        target_input_path=optional_string(payload, "target_input_path"),
        metadata=wire_mapping(payload.get("metadata", {}), "legacy metadata"),
    )


def order_intent_to_v1(intent: OrderIntent) -> dict[str, object]:
    """Return the persisted v1 order-intent shape for compatibility tests/tools."""

    return {
        "intent_id": intent.intent_id,
        "symbol": intent.instrument.legacy_symbol,
        "side": intent.side.value,
        "quantity": float(intent.quantity),
        "order_type": intent.order_type.value,
        "limit_price": float(intent.limit_price) if intent.limit_price is not None else None,
        "broker_name": intent.broker_name or "",
        "account_label": intent.account_label,
        "target_source": intent.target_source,
        "target_asof": datetime_to_wire(intent.target_as_of) if intent.target_as_of else None,
        "target_input_path": intent.target_input_path,
        "run_id": intent.run_id,
        "created_at": datetime_to_wire(intent.created_at),
        "metadata": metadata_to_wire(intent.metadata),
    }


def _legacy_status(value: object) -> tuple[OrderStatus, str | None]:
    if not isinstance(value, str):
        raise WireFormatError("legacy status must be a string")
    raw = value.strip().upper()
    alias = _STATUS_ALIASES.get(raw)
    if alias is not None:
        return alias, None
    try:
        return OrderStatus(raw), None
    except ValueError:
        return OrderStatus.UNKNOWN, raw


def _event_type_for_status(status: OrderStatus) -> ExecutionEventType:
    return {
        OrderStatus.ACCEPTED: ExecutionEventType.ORDER_ACKNOWLEDGED,
        OrderStatus.PARTIALLY_FILLED: ExecutionEventType.PARTIALLY_FILLED,
        OrderStatus.FILLED: ExecutionEventType.FILLED,
        OrderStatus.CANCELLED: ExecutionEventType.CANCELLED,
        OrderStatus.REJECTED: ExecutionEventType.REJECTED,
        OrderStatus.EXPIRED: ExecutionEventType.EXPIRED,
        OrderStatus.FAILED: ExecutionEventType.FAILED,
    }.get(status, ExecutionEventType.ORDER_UPDATED)


def _stable_legacy_id(prefix: str, payload: Mapping[str, object]) -> str:
    wire = metadata_to_wire(payload)
    encoded = json.dumps(wire, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24]
    return f"legacy-{prefix}-{digest}"


def order_event_from_v1(
    value: object,
    *,
    event_id: str | None = None,
    intent_id: str | None = None,
    naive_timezone: tzinfo = timezone.utc,
) -> OrderEvent:
    """Migrate a legacy ``BrokerOrderRecord`` mapping into an order event."""

    payload = wire_mapping(value, "legacy broker order")
    status, unmapped_status = _legacy_status(payload.get("status", "UNKNOWN"))
    metadata: dict[str, object] = dict(
        wire_mapping(payload.get("raw", {}), "legacy broker order raw")
    )
    if unmapped_status is not None:
        metadata["legacy_status"] = unmapped_status
    return OrderEvent(
        event_id=event_id or _stable_legacy_id("order-event", payload),
        event_type=_event_type_for_status(status),
        occurred_at=migrate_legacy_datetime(
            payload.get("updated_at") or payload.get("submitted_at"),
            "updated_at",
            naive_timezone=naive_timezone,
        ),
        instrument=instrument_from_legacy(
            required_value(payload, "symbol"),
            payload.get("market"),
            currency=payload.get("currency"),
        ),
        status=status,
        broker_name=required_string(payload, "broker_name"),
        account_label=required_string(payload, "account_label"),
        broker_order_id=required_string(payload, "broker_order_id"),
        intent_id=intent_id or optional_string(payload, "intent_id"),
        client_order_id=optional_string(payload, "client_order_id"),
        side=(
            enum_value(OrderSide, payload["side"], "side")
            if payload.get("side") is not None
            else None
        ),
        quantity=optional_legacy_decimal(payload, "quantity"),
        filled_quantity=optional_legacy_decimal(payload, "filled_quantity"),
        remaining_quantity=optional_legacy_decimal(payload, "remaining_quantity"),
        average_fill_price=optional_legacy_decimal(payload, "avg_fill_price"),
        message=optional_string(payload, "message"),
        metadata=metadata,
    )


def order_event_to_v1(event: OrderEvent) -> dict[str, object]:
    """Return the current ``BrokerOrderRecord``-compatible shape."""

    status = "CANCELED" if event.status is OrderStatus.CANCELLED else event.status.value
    return {
        "broker_order_id": event.broker_order_id,
        "symbol": event.instrument.legacy_symbol,
        "side": event.side.value if event.side else "",
        "quantity": float(event.quantity or Decimal("0")),
        "broker_name": event.broker_name,
        "account_label": event.account_label,
        "filled_quantity": float(event.filled_quantity or Decimal("0")),
        "remaining_quantity": (
            float(event.remaining_quantity) if event.remaining_quantity is not None else None
        ),
        "status": status,
        "client_order_id": event.client_order_id,
        "avg_fill_price": (
            float(event.average_fill_price) if event.average_fill_price is not None else None
        ),
        "submitted_at": datetime_to_wire(event.occurred_at),
        "updated_at": datetime_to_wire(event.occurred_at),
        "message": event.message,
        "raw": metadata_to_wire(event.metadata),
    }


def fill_from_v1(
    value: object,
    *,
    naive_timezone: tzinfo = timezone.utc,
) -> Fill:
    """Migrate a legacy broker/state fill mapping into a typed fill."""

    payload = wire_mapping(value, "legacy fill")
    metadata: dict[str, object] = dict(wire_mapping(payload.get("raw", {}), "legacy fill raw"))
    parent_order_id = optional_string(payload, "parent_order_id")
    if parent_order_id:
        metadata["parent_order_id"] = parent_order_id
    side_value = payload.get("side")
    return Fill(
        fill_id=required_string(payload, "fill_id"),
        broker_order_id=required_string(payload, "broker_order_id"),
        instrument=instrument_from_legacy(
            required_value(payload, "symbol"),
            payload.get("market"),
            currency=payload.get("currency"),
        ),
        quantity=legacy_decimal(required_value(payload, "quantity"), "quantity"),
        price=legacy_decimal(required_value(payload, "price"), "price"),
        filled_at=migrate_legacy_datetime(
            required_value(payload, "filled_at"),
            "filled_at",
            naive_timezone=naive_timezone,
        ),
        broker_name=required_string(payload, "broker_name"),
        account_label=required_string(payload, "account_label"),
        intent_id=optional_string(payload, "intent_id"),
        side=enum_value(OrderSide, side_value, "side") if side_value is not None else None,
        metadata=metadata,
    )


def fill_to_v1(fill: Fill) -> dict[str, object]:
    """Return the current ``BrokerFillRecord``-compatible shape."""

    return {
        "fill_id": fill.fill_id,
        "broker_order_id": fill.broker_order_id,
        "symbol": fill.instrument.legacy_symbol,
        "quantity": float(fill.quantity),
        "price": float(fill.price),
        "broker_name": fill.broker_name,
        "account_label": fill.account_label,
        "filled_at": datetime_to_wire(fill.filled_at),
        "raw": metadata_to_wire(fill.metadata),
    }
