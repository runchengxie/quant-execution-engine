"""Schema-v2 codec for immutable execution domain models."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import cast

from ._serialization_common import (
    SCHEMA_VERSION,
    DomainModel,
    WireFormatError,
    WirePayload,
    WireValue,
    datetime_from_wire,
    datetime_to_wire,
    decimal_from_wire,
    decimal_to_wire,
    enum_value,
    instrument_from_wire,
    instrument_to_wire,
    metadata_from_wire,
    metadata_to_wire,
    optional_bool,
    optional_datetime_from_wire,
    optional_decimal_from_wire,
    optional_string,
    required_string,
    required_value,
    wire_mapping,
)
from .domain import (
    ApprovedTarget,
    ExecutionEventType,
    Fill,
    Money,
    OrderEvent,
    OrderIntent,
    OrderSide,
    OrderStatus,
    OrderType,
    PortfolioTarget,
    TimeInForce,
)


def _money_to_wire(value: Money | None) -> WireValue:
    if value is None:
        return None
    return {"amount": decimal_to_wire(value.amount), "currency": value.currency}


def _money_from_wire(value: object) -> Money | None:
    if value is None:
        return None
    payload = wire_mapping(value, "money")
    return Money(
        amount=decimal_from_wire(required_value(payload, "amount"), "money.amount"),
        currency=required_string(payload, "currency"),
    )


def _validated_v2_payload(value: object, expected_kind: str) -> Mapping[str, object]:
    payload = wire_mapping(value, expected_kind)
    version = payload.get("schema_version")
    if version != SCHEMA_VERSION:
        raise WireFormatError(f"schema_version must be {SCHEMA_VERSION}")
    kind = payload.get("kind")
    if kind != expected_kind:
        raise WireFormatError(f"expected kind {expected_kind!r}, got {kind!r}")
    return payload


def portfolio_target_to_v2(target: PortfolioTarget) -> WirePayload:
    """Map a portfolio target to its deterministic schema-v2 shape."""

    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "portfolio_target",
        "instrument": instrument_to_wire(target.instrument),
        "portfolio_id": target.portfolio_id,
        "as_of": datetime_to_wire(target.as_of),
        "target_weight": (
            decimal_to_wire(target.target_weight) if target.target_weight is not None else None
        ),
        "target_quantity": (
            decimal_to_wire(target.target_quantity) if target.target_quantity is not None else None
        ),
        "valid_from": datetime_to_wire(target.valid_from) if target.valid_from else None,
        "expires_at": datetime_to_wire(target.expires_at) if target.expires_at else None,
        "source": target.source,
        "notes": target.notes,
        "metadata": metadata_to_wire(target.metadata),
    }


def portfolio_target_from_v2(value: object) -> PortfolioTarget:
    """Decode a schema-v2 portfolio target."""

    payload = _validated_v2_payload(value, "portfolio_target")
    return PortfolioTarget(
        instrument=instrument_from_wire(required_value(payload, "instrument")),
        portfolio_id=required_string(payload, "portfolio_id"),
        as_of=datetime_from_wire(required_value(payload, "as_of"), "as_of"),
        target_weight=optional_decimal_from_wire(payload, "target_weight"),
        target_quantity=optional_decimal_from_wire(payload, "target_quantity"),
        valid_from=optional_datetime_from_wire(payload, "valid_from"),
        expires_at=optional_datetime_from_wire(payload, "expires_at"),
        source=optional_string(payload, "source"),
        notes=optional_string(payload, "notes"),
        metadata=metadata_from_wire(payload),
    )


def approved_target_to_v2(target: ApprovedTarget) -> WirePayload:
    """Map an approved target to its deterministic schema-v2 shape."""

    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "approved_target",
        "approval_id": target.approval_id,
        "target": portfolio_target_to_v2(target.target),
        "approved_at": datetime_to_wire(target.approved_at),
        "policy_reference": target.policy_reference,
        "account_label": target.account_label,
        "valid_until": datetime_to_wire(target.valid_until) if target.valid_until else None,
        "max_notional": _money_to_wire(target.max_notional),
        "metadata": metadata_to_wire(target.metadata),
    }


def approved_target_from_v2(value: object) -> ApprovedTarget:
    """Decode a schema-v2 approved target."""

    payload = _validated_v2_payload(value, "approved_target")
    return ApprovedTarget(
        approval_id=required_string(payload, "approval_id"),
        target=portfolio_target_from_v2(required_value(payload, "target")),
        approved_at=datetime_from_wire(required_value(payload, "approved_at"), "approved_at"),
        policy_reference=required_string(payload, "policy_reference"),
        account_label=required_string(payload, "account_label"),
        valid_until=optional_datetime_from_wire(payload, "valid_until"),
        max_notional=_money_from_wire(payload.get("max_notional")),
        metadata=metadata_from_wire(payload),
    )


def order_intent_to_v2(intent: OrderIntent) -> WirePayload:
    """Map an order intent to its deterministic schema-v2 shape."""

    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "order_intent",
        "intent_id": intent.intent_id,
        "instrument": instrument_to_wire(intent.instrument),
        "side": intent.side.value,
        "quantity": decimal_to_wire(intent.quantity),
        "order_type": intent.order_type.value,
        "created_at": datetime_to_wire(intent.created_at),
        "limit_price": decimal_to_wire(intent.limit_price) if intent.limit_price else None,
        "stop_price": decimal_to_wire(intent.stop_price) if intent.stop_price else None,
        "time_in_force": intent.time_in_force.value,
        "opens_short": intent.opens_short,
        "approval_id": intent.approval_id,
        "broker_name": intent.broker_name,
        "account_label": intent.account_label,
        "run_id": intent.run_id,
        "target_source": intent.target_source,
        "target_as_of": datetime_to_wire(intent.target_as_of) if intent.target_as_of else None,
        "target_input_path": intent.target_input_path,
        "metadata": metadata_to_wire(intent.metadata),
    }


def order_intent_from_v2(value: object) -> OrderIntent:
    """Decode a schema-v2 order intent."""

    payload = _validated_v2_payload(value, "order_intent")
    return OrderIntent(
        intent_id=required_string(payload, "intent_id"),
        instrument=instrument_from_wire(required_value(payload, "instrument")),
        side=enum_value(OrderSide, required_value(payload, "side"), "side"),
        quantity=decimal_from_wire(required_value(payload, "quantity"), "quantity"),
        order_type=enum_value(OrderType, required_value(payload, "order_type"), "order_type"),
        created_at=datetime_from_wire(required_value(payload, "created_at"), "created_at"),
        limit_price=optional_decimal_from_wire(payload, "limit_price"),
        stop_price=optional_decimal_from_wire(payload, "stop_price"),
        time_in_force=enum_value(
            TimeInForce,
            payload.get("time_in_force", TimeInForce.DAY.value),
            "time_in_force",
        ),
        opens_short=optional_bool(payload, "opens_short"),
        approval_id=optional_string(payload, "approval_id"),
        broker_name=optional_string(payload, "broker_name"),
        account_label=required_string(payload, "account_label"),
        run_id=optional_string(payload, "run_id"),
        target_source=optional_string(payload, "target_source"),
        target_as_of=optional_datetime_from_wire(payload, "target_as_of"),
        target_input_path=optional_string(payload, "target_input_path"),
        metadata=metadata_from_wire(payload),
    )


def order_event_to_v2(event: OrderEvent) -> WirePayload:
    """Map a broker order event to its deterministic schema-v2 shape."""

    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "order_event",
        "event_id": event.event_id,
        "event_type": event.event_type.value,
        "occurred_at": datetime_to_wire(event.occurred_at),
        "instrument": instrument_to_wire(event.instrument),
        "status": event.status.value,
        "broker_name": event.broker_name,
        "account_label": event.account_label,
        "broker_order_id": event.broker_order_id,
        "intent_id": event.intent_id,
        "client_order_id": event.client_order_id,
        "side": event.side.value if event.side else None,
        "quantity": decimal_to_wire(event.quantity) if event.quantity is not None else None,
        "filled_quantity": (
            decimal_to_wire(event.filled_quantity) if event.filled_quantity is not None else None
        ),
        "remaining_quantity": (
            decimal_to_wire(event.remaining_quantity)
            if event.remaining_quantity is not None
            else None
        ),
        "average_fill_price": (
            decimal_to_wire(event.average_fill_price)
            if event.average_fill_price is not None
            else None
        ),
        "message": event.message,
        "metadata": metadata_to_wire(event.metadata),
    }


def order_event_from_v2(value: object) -> OrderEvent:
    """Decode a schema-v2 broker order event."""

    payload = _validated_v2_payload(value, "order_event")
    side_value = payload.get("side")
    return OrderEvent(
        event_id=required_string(payload, "event_id"),
        event_type=enum_value(
            ExecutionEventType,
            required_value(payload, "event_type"),
            "event_type",
        ),
        occurred_at=datetime_from_wire(required_value(payload, "occurred_at"), "occurred_at"),
        instrument=instrument_from_wire(required_value(payload, "instrument")),
        status=enum_value(OrderStatus, required_value(payload, "status"), "status"),
        broker_name=required_string(payload, "broker_name"),
        account_label=required_string(payload, "account_label"),
        broker_order_id=required_string(payload, "broker_order_id"),
        intent_id=optional_string(payload, "intent_id"),
        client_order_id=optional_string(payload, "client_order_id"),
        side=enum_value(OrderSide, side_value, "side") if side_value is not None else None,
        quantity=optional_decimal_from_wire(payload, "quantity"),
        filled_quantity=optional_decimal_from_wire(payload, "filled_quantity"),
        remaining_quantity=optional_decimal_from_wire(payload, "remaining_quantity"),
        average_fill_price=optional_decimal_from_wire(payload, "average_fill_price"),
        message=optional_string(payload, "message"),
        metadata=metadata_from_wire(payload),
    )


def fill_to_v2(fill: Fill) -> WirePayload:
    """Map a fill to its deterministic schema-v2 shape."""

    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "fill",
        "fill_id": fill.fill_id,
        "broker_order_id": fill.broker_order_id,
        "instrument": instrument_to_wire(fill.instrument),
        "quantity": decimal_to_wire(fill.quantity),
        "price": decimal_to_wire(fill.price),
        "filled_at": datetime_to_wire(fill.filled_at),
        "broker_name": fill.broker_name,
        "account_label": fill.account_label,
        "intent_id": fill.intent_id,
        "side": fill.side.value if fill.side else None,
        "commission": _money_to_wire(fill.commission),
        "metadata": metadata_to_wire(fill.metadata),
    }


def fill_from_v2(value: object) -> Fill:
    """Decode a schema-v2 fill."""

    payload = _validated_v2_payload(value, "fill")
    side_value = payload.get("side")
    return Fill(
        fill_id=required_string(payload, "fill_id"),
        broker_order_id=required_string(payload, "broker_order_id"),
        instrument=instrument_from_wire(required_value(payload, "instrument")),
        quantity=decimal_from_wire(required_value(payload, "quantity"), "quantity"),
        price=decimal_from_wire(required_value(payload, "price"), "price"),
        filled_at=datetime_from_wire(required_value(payload, "filled_at"), "filled_at"),
        broker_name=required_string(payload, "broker_name"),
        account_label=required_string(payload, "account_label"),
        intent_id=optional_string(payload, "intent_id"),
        side=enum_value(OrderSide, side_value, "side") if side_value is not None else None,
        commission=_money_from_wire(payload.get("commission")),
        metadata=metadata_from_wire(payload),
    )


def to_v2_payload(value: object) -> WirePayload:
    """Encode any supported domain model as a schema-v2 mapping."""

    if isinstance(value, PortfolioTarget):
        return portfolio_target_to_v2(value)
    if isinstance(value, ApprovedTarget):
        return approved_target_to_v2(value)
    if isinstance(value, OrderIntent):
        return order_intent_to_v2(value)
    if isinstance(value, OrderEvent):
        return order_event_to_v2(value)
    if isinstance(value, Fill):
        return fill_to_v2(value)
    raise TypeError(f"unsupported execution domain model: {type(value).__name__}")


def from_v2_payload(value: object) -> DomainModel:
    """Decode any supported schema-v2 domain mapping."""

    payload = wire_mapping(value, "payload")
    kind = payload.get("kind")
    if kind == "portfolio_target":
        return portfolio_target_from_v2(payload)
    if kind == "approved_target":
        return approved_target_from_v2(payload)
    if kind == "order_intent":
        return order_intent_from_v2(payload)
    if kind == "order_event":
        return order_event_from_v2(payload)
    if kind == "fill":
        return fill_from_v2(payload)
    raise WireFormatError(f"unsupported schema-v2 kind: {kind!r}")


def dumps_v2(value: DomainModel) -> str:
    """Return byte-stable canonical JSON for a supported domain model."""

    return (
        json.dumps(
            to_v2_payload(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )


def loads_v2(value: str | bytes) -> DomainModel:
    """Load canonical or pretty-printed schema-v2 JSON."""

    try:
        decoded = cast(object, json.loads(value))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise WireFormatError("invalid schema-v2 JSON") from exc
    return from_v2_payload(decoded)
