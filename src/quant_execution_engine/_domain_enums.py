"""Framework-neutral execution enums and shared value-object helpers.

This is the lowest layer of the typed execution domain: it depends only on the
standard library and is imported by the model and capability submodules.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum, StrEnum
from typing import TypeVar

_EnumMember = TypeVar("_EnumMember", bound=Enum)
_Instance = TypeVar("_Instance")


class _StringEnum(StrEnum):
    """Shared string enum base for execution-domain values."""


class OrderSide(_StringEnum):
    """Direction of an order request."""

    BUY = "BUY"
    SELL = "SELL"


class OrderType(_StringEnum):
    """Framework-neutral order types understood by the domain boundary."""

    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    STOP_LIMIT = "STOP_LIMIT"
    TRAILING_STOP = "TRAILING_STOP"


class TimeInForce(_StringEnum):
    """Lifetime instruction attached to an order."""

    DAY = "DAY"
    GTC = "GTC"
    IOC = "IOC"
    FOK = "FOK"


class OrderStatus(_StringEnum):
    """Canonical order lifecycle status.

    ``CANCELED`` from legacy broker payloads is normalized to ``CANCELLED`` by
    the compatibility codec.  ``UNKNOWN`` preserves forward compatibility for
    broker statuses that have not yet been mapped.
    """

    PENDING = "PENDING"
    NEW = "NEW"
    ACCEPTED = "ACCEPTED"
    PENDING_NEW = "PENDING_NEW"
    PENDING_REPLACE = "PENDING_REPLACE"
    WAIT_TO_NEW = "WAIT_TO_NEW"
    WAIT_TO_CANCEL = "WAIT_TO_CANCEL"
    PENDING_CANCEL = "PENDING_CANCEL"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    SUCCESS = "SUCCESS"
    UNKNOWN = "UNKNOWN"


class ExecutionEventType(_StringEnum):
    """Canonical event types emitted at the broker boundary."""

    ORDER_SUBMITTED = "ORDER_SUBMITTED"
    ORDER_ACKNOWLEDGED = "ORDER_ACKNOWLEDGED"
    ORDER_UPDATED = "ORDER_UPDATED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    FAILED = "FAILED"
    RECONCILED = "RECONCILED"


def _require_instance(
    value: object,
    expected_type: type[_Instance],
    field_name: str,
) -> _Instance:
    if not isinstance(value, expected_type):
        raise TypeError(f"{field_name} must be {expected_type.__name__}")
    return value


def _require_string(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    return value


def _require_bool(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{field_name} must be a boolean")
    return value


def _optional_string(value: object | None, field_name: str) -> str | None:
    if value is None:
        return None
    normalized = _require_string(value, field_name).strip()
    return normalized or None


def _require_enum(
    value: object,
    enum_type: type[_EnumMember],
    field_name: str,
) -> _EnumMember:
    if not isinstance(value, enum_type):
        raise TypeError(f"{field_name} must be {enum_type.__name__}")
    return value


def _require_decimal(value: object, field_name: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError(f"{field_name} must be a Decimal")
    if not value.is_finite():
        raise ValueError(f"{field_name} must be finite")
    return value


def _optional_decimal(value: Decimal | None, field_name: str) -> Decimal | None:
    if value is None:
        return None
    return _require_decimal(value, field_name)


def _aware_utc(value: object, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)
