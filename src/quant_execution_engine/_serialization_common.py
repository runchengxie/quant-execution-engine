# pyright: strict
"""Shared primitives for the typed execution serialization boundary."""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import datetime, time, timezone, tzinfo
from decimal import Decimal, InvalidOperation
from typing import TypeAlias, TypeVar, cast

from .domain import (
    ApprovedTarget,
    ExecutionEventType,
    Fill,
    InstrumentId,
    OrderEvent,
    OrderIntent,
    OrderSide,
    OrderStatus,
    OrderType,
    PortfolioTarget,
    TimeInForce,
)

SCHEMA_VERSION = 2

WireScalar: TypeAlias = str | int | float | bool | None
WireValue: TypeAlias = WireScalar | list["WireValue"] | dict[str, "WireValue"]
WirePayload: TypeAlias = dict[str, WireValue]
DomainModel: TypeAlias = PortfolioTarget | ApprovedTarget | OrderIntent | OrderEvent | Fill

_KNOWN_MARKETS = {"US", "HK", "CN", "SG"}
_CN_EXCHANGES = {"SH", "SZ", "BJ", "XSHG", "XSHE"}


class WireFormatError(ValueError):
    """Raised when a v1 or v2 wire payload cannot be decoded safely."""


def decimal_to_wire(value: Decimal) -> str:
    if not value.is_finite():
        raise WireFormatError("Decimal values must be finite")
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    if rendered in {"", "-0"}:
        return "0"
    return rendered


def decimal_from_wire(value: object, field_name: str) -> Decimal:
    if not isinstance(value, str):
        raise WireFormatError(f"{field_name} must be a decimal string in schema v2")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise WireFormatError(f"{field_name} is not a valid decimal string") from exc
    if not parsed.is_finite():
        raise WireFormatError(f"{field_name} must be finite")
    return parsed


def legacy_decimal(value: object, field_name: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise WireFormatError(f"legacy {field_name} must be numeric")
    if not isinstance(value, (str, int, float, Decimal)):
        raise WireFormatError(f"legacy {field_name} must be numeric")
    try:
        parsed = Decimal(str(value))
    except InvalidOperation as exc:
        raise WireFormatError(f"legacy {field_name} must be numeric") from exc
    if not parsed.is_finite():
        raise WireFormatError(f"legacy {field_name} must be finite")
    return parsed


def datetime_to_wire(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise WireFormatError("schema v2 timestamps must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_iso_datetime(value: object, field_name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise WireFormatError(f"{field_name} must be a non-empty ISO-8601 string")
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise WireFormatError(f"{field_name} is not a valid ISO-8601 timestamp") from exc
    return parsed


def datetime_from_wire(value: object, field_name: str) -> datetime:
    parsed = _parse_iso_datetime(value, field_name)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise WireFormatError(f"{field_name} must be timezone-aware in schema v2")
    return parsed.astimezone(timezone.utc)


def migrate_legacy_datetime(
    value: object,
    field_name: str,
    *,
    naive_timezone: tzinfo = timezone.utc,
) -> datetime:
    """Parse a legacy timestamp, explicitly assigning a zone when it is naive."""

    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and len(value.strip()) == 10:
        try:
            parsed_date = datetime.fromisoformat(value.strip()).date()
        except ValueError as exc:
            raise WireFormatError(f"legacy {field_name} is not a valid date") from exc
        parsed = datetime.combine(parsed_date, time.min)
    else:
        parsed = _parse_iso_datetime(value, f"legacy {field_name}")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=naive_timezone)
    if parsed.utcoffset() is None:
        raise WireFormatError(f"naive_timezone cannot localize legacy {field_name}")
    return parsed.astimezone(timezone.utc)


def wire_mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise WireFormatError(f"{field_name} must be an object")
    result: dict[str, object] = {}
    mapping = cast(Mapping[object, object], value)
    for key, item in mapping.items():
        if not isinstance(key, str):
            raise WireFormatError(f"{field_name} keys must be strings")
        result[key] = item
    return result


def required_value(payload: Mapping[str, object], field_name: str) -> object:
    if field_name not in payload:
        raise WireFormatError(f"missing required field: {field_name}")
    return payload[field_name]


def required_string(payload: Mapping[str, object], field_name: str) -> str:
    value = required_value(payload, field_name)
    if not isinstance(value, str) or not value.strip():
        raise WireFormatError(f"{field_name} must be a non-empty string")
    return value.strip()


def optional_string(payload: Mapping[str, object], field_name: str) -> str | None:
    value = payload.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise WireFormatError(f"{field_name} must be a string or null")
    return value or None


def optional_bool(payload: Mapping[str, object], field_name: str, default: bool = False) -> bool:
    value = payload.get(field_name, default)
    if not isinstance(value, bool):
        raise WireFormatError(f"{field_name} must be a boolean")
    return value


def optional_decimal_from_wire(
    payload: Mapping[str, object],
    field_name: str,
) -> Decimal | None:
    value = payload.get(field_name)
    if value is None:
        return None
    return decimal_from_wire(value, field_name)


def optional_legacy_decimal(
    payload: Mapping[str, object],
    field_name: str,
) -> Decimal | None:
    value = payload.get(field_name)
    if value is None:
        return None
    return legacy_decimal(value, field_name)


def optional_datetime_from_wire(
    payload: Mapping[str, object],
    field_name: str,
) -> datetime | None:
    value = payload.get(field_name)
    if value is None:
        return None
    return datetime_from_wire(value, field_name)


def _metadata_to_wire_value(value: object, path: str) -> WireValue:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise WireFormatError(f"{path} must be finite")
        return value
    if isinstance(value, Mapping):
        result: dict[str, WireValue] = {}
        mapping = cast(Mapping[object, object], value)
        for key, item in mapping.items():
            if not isinstance(key, str):
                raise WireFormatError(f"{path} keys must be strings")
            result[key] = _metadata_to_wire_value(item, f"{path}.{key}")
        return result
    if isinstance(value, (list, tuple)):
        sequence = cast(list[object] | tuple[object, ...], value)
        return [
            _metadata_to_wire_value(item, f"{path}[{index}]") for index, item in enumerate(sequence)
        ]
    raise WireFormatError(f"{path} contains a non-JSON value: {type(value).__name__}")


def metadata_to_wire(metadata: Mapping[str, object]) -> dict[str, WireValue]:
    converted = _metadata_to_wire_value(metadata, "metadata")
    if not isinstance(converted, dict):  # pragma: no cover - input is always a mapping
        raise WireFormatError("metadata must be an object")
    return converted


def metadata_from_wire(payload: Mapping[str, object]) -> Mapping[str, object]:
    raw = payload.get("metadata", {})
    return wire_mapping(raw, "metadata")


def instrument_to_wire(instrument: InstrumentId) -> WirePayload:
    return {
        "symbol": instrument.symbol,
        "market": instrument.market,
        "exchange": instrument.exchange,
        "currency": instrument.currency,
    }


def instrument_from_wire(value: object) -> InstrumentId:
    payload = wire_mapping(value, "instrument")
    return InstrumentId(
        symbol=required_string(payload, "symbol"),
        market=required_string(payload, "market"),
        exchange=optional_string(payload, "exchange"),
        currency=optional_string(payload, "currency"),
    )


def instrument_from_legacy(
    symbol: object,
    market: object | None = None,
    *,
    currency: object | None = None,
    default_market: str = "US",
) -> InstrumentId:
    """Migrate v1 symbol/market fields without importing target or broker code."""

    if not isinstance(symbol, str) or not symbol.strip():
        raise WireFormatError("legacy symbol must be a non-empty string")
    raw_symbol = symbol.strip().upper()
    if market is not None and not isinstance(market, str):
        raise WireFormatError("legacy market must be a string")
    raw_market = str(market or "").strip().upper()
    exchange: str | None = None

    parts = raw_symbol.split(".")
    if raw_market:
        if parts[-1] == raw_market:
            parts.pop()
    elif len(parts) > 1 and parts[-1] in _KNOWN_MARKETS:
        raw_market = parts.pop()
    else:
        raw_market = default_market.strip().upper()

    if raw_market == "CN" and len(parts) > 1 and parts[-1] in _CN_EXCHANGES:
        exchange = parts.pop()
        exchange = {"XSHG": "SH", "XSHE": "SZ"}.get(exchange, exchange)

    raw_currency: str | None = None
    if currency is not None:
        if not isinstance(currency, str):
            raise WireFormatError("legacy currency must be a string")
        raw_currency = currency

    return InstrumentId(
        symbol=".".join(parts),
        market=raw_market or default_market,
        exchange=exchange,
        currency=raw_currency,
    )


_EnumType = TypeVar("_EnumType", OrderSide, OrderType, TimeInForce, OrderStatus, ExecutionEventType)


def enum_value(enum_type: type[_EnumType], value: object, field_name: str) -> _EnumType:
    if not isinstance(value, str):
        raise WireFormatError(f"{field_name} must be a string enum value")
    try:
        return enum_type(value.strip().upper())
    except ValueError as exc:
        raise WireFormatError(f"unsupported {field_name}: {value}") from exc
