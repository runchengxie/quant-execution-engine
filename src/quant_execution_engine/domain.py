# pyright: strict
"""Framework-neutral, immutable execution domain models.

The models in this module are the typed boundary for new execution work.  The
mutable DTOs in :mod:`quant_execution_engine.models` and the version-1 state
records in :mod:`quant_execution_engine.execution_state` remain available for
the current CLI and recovery paths.  Conversion between those wire shapes and
these models belongs in :mod:`quant_execution_engine.serialization`.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from types import MappingProxyType
from typing import TypeVar, cast


class _StringEnum(str, Enum):
    """Python 3.10 compatible string enum."""

    def __str__(self) -> str:
        return cast(str, self.value)


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


_EnumMember = TypeVar("_EnumMember", bound=Enum)
_Instance = TypeVar("_Instance")


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
    return value.astimezone(timezone.utc)


def _freeze_metadata_value(value: object, path: str) -> object:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} must be finite")
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, object] = {}
        mapping = cast(Mapping[object, object], value)
        for key, item in mapping.items():
            if not isinstance(key, str):
                raise TypeError(f"{path} keys must be strings")
            frozen[key] = _freeze_metadata_value(item, f"{path}.{key}")
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        sequence = cast(list[object] | tuple[object, ...], value)
        return tuple(
            _freeze_metadata_value(item, f"{path}[{index}]") for index, item in enumerate(sequence)
        )
    raise TypeError(f"{path} contains a non-JSON value: {type(value).__name__}")


def _freeze_metadata(metadata: Mapping[str, object]) -> Mapping[str, object]:
    frozen = _freeze_metadata_value(metadata, "metadata")
    if not isinstance(frozen, Mapping):  # pragma: no cover - guarded by the input check
        raise TypeError("metadata must be a mapping")
    return cast(Mapping[str, object], frozen)


def _empty_metadata() -> Mapping[str, object]:
    return {}


@dataclass(frozen=True, slots=True)
class InstrumentId:
    """Stable, provider-independent instrument identity."""

    symbol: str
    market: str
    exchange: str | None = None
    currency: str | None = None

    def __post_init__(self) -> None:
        symbol = _require_string(self.symbol, "symbol").strip().upper()
        market = _require_string(self.market, "market").strip().upper()
        exchange = (
            _require_string(self.exchange, "exchange").strip().upper()
            if self.exchange is not None
            else None
        )
        currency = (
            _require_string(self.currency, "currency").strip().upper()
            if self.currency is not None
            else None
        )
        if not symbol:
            raise ValueError("instrument symbol cannot be empty")
        if not market:
            raise ValueError("instrument market cannot be empty")
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "market", market)
        object.__setattr__(self, "exchange", exchange)
        object.__setattr__(self, "currency", currency)

    @property
    def legacy_symbol(self) -> str:
        """Return the symbol form used by the current v1 execution state."""

        base = f"{self.symbol}.{self.exchange}" if self.exchange else self.symbol
        return f"{base}.{self.market}"


@dataclass(frozen=True, slots=True)
class Money:
    """Decimal monetary amount with an explicit currency."""

    amount: Decimal
    currency: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "amount", _require_decimal(self.amount, "amount"))
        currency = _require_string(self.currency, "currency").strip().upper()
        if not currency:
            raise ValueError("money currency cannot be empty")
        object.__setattr__(self, "currency", currency)


@dataclass(frozen=True, slots=True)
class PortfolioTarget:
    """Research-owned target, before execution policy or approval.

    Negative and fractional targets are valid domain values.  Whether a target
    is executable is decided separately against :class:`ExecutionCapabilities`.
    """

    instrument: InstrumentId
    portfolio_id: str
    as_of: datetime
    target_weight: Decimal | None = None
    target_quantity: Decimal | None = None
    valid_from: datetime | None = None
    expires_at: datetime | None = None
    source: str | None = None
    notes: str | None = None
    metadata: Mapping[str, object] = field(default_factory=_empty_metadata)

    def __post_init__(self) -> None:
        _require_instance(self.instrument, InstrumentId, "instrument")
        portfolio_id = _require_string(self.portfolio_id, "portfolio_id").strip()
        if not portfolio_id:
            raise ValueError("portfolio_id cannot be empty")
        has_weight = self.target_weight is not None
        has_quantity = self.target_quantity is not None
        if has_weight == has_quantity:
            raise ValueError("define exactly one of target_weight or target_quantity")
        object.__setattr__(self, "portfolio_id", portfolio_id)
        object.__setattr__(self, "as_of", _aware_utc(self.as_of, "as_of"))
        object.__setattr__(
            self,
            "target_weight",
            _optional_decimal(self.target_weight, "target_weight"),
        )
        object.__setattr__(
            self,
            "target_quantity",
            _optional_decimal(self.target_quantity, "target_quantity"),
        )
        if self.valid_from is not None:
            object.__setattr__(self, "valid_from", _aware_utc(self.valid_from, "valid_from"))
        if self.expires_at is not None:
            object.__setattr__(self, "expires_at", _aware_utc(self.expires_at, "expires_at"))
        if (
            self.valid_from is not None
            and self.expires_at is not None
            and self.expires_at <= self.valid_from
        ):
            raise ValueError("expires_at must be later than valid_from")
        object.__setattr__(self, "source", _optional_string(self.source, "source"))
        object.__setattr__(self, "notes", _optional_string(self.notes, "notes"))
        object.__setattr__(self, "metadata", _freeze_metadata(self.metadata))


@dataclass(frozen=True, slots=True)
class ApprovedTarget:
    """Execution-policy approval attached to a portfolio target."""

    approval_id: str
    target: PortfolioTarget
    approved_at: datetime
    policy_reference: str
    account_label: str
    valid_until: datetime | None = None
    max_notional: Money | None = None
    metadata: Mapping[str, object] = field(default_factory=_empty_metadata)

    def __post_init__(self) -> None:
        _require_instance(self.target, PortfolioTarget, "target")
        approval_id = _require_string(self.approval_id, "approval_id").strip()
        policy_reference = _require_string(self.policy_reference, "policy_reference").strip()
        account_label = _require_string(self.account_label, "account_label").strip()
        if not approval_id:
            raise ValueError("approval_id cannot be empty")
        if not policy_reference:
            raise ValueError("policy_reference cannot be empty")
        if not account_label:
            raise ValueError("account_label cannot be empty")
        approved_at = _aware_utc(self.approved_at, "approved_at")
        object.__setattr__(self, "approval_id", approval_id)
        object.__setattr__(self, "policy_reference", policy_reference)
        object.__setattr__(self, "account_label", account_label)
        object.__setattr__(self, "approved_at", approved_at)
        if self.valid_until is not None:
            valid_until = _aware_utc(self.valid_until, "valid_until")
            if valid_until <= approved_at:
                raise ValueError("valid_until must be later than approved_at")
            object.__setattr__(self, "valid_until", valid_until)
        if self.max_notional is not None:
            max_notional = _require_instance(self.max_notional, Money, "max_notional")
            if max_notional.amount <= 0:
                raise ValueError("max_notional must be greater than zero")
        object.__setattr__(self, "metadata", _freeze_metadata(self.metadata))


@dataclass(frozen=True, slots=True)
class OrderIntent:
    """Approved instruction to create one broker order.

    ``quantity`` is an absolute order magnitude; direction is represented by
    ``side``.  ``opens_short`` makes short capability validation explicit and
    avoids incorrectly treating every sell order as a short sale.
    """

    intent_id: str
    instrument: InstrumentId
    side: OrderSide
    quantity: Decimal
    order_type: OrderType
    created_at: datetime
    limit_price: Decimal | None = None
    stop_price: Decimal | None = None
    time_in_force: TimeInForce = TimeInForce.DAY
    opens_short: bool = False
    approval_id: str | None = None
    broker_name: str | None = None
    account_label: str = "main"
    run_id: str | None = None
    target_source: str | None = None
    target_as_of: datetime | None = None
    target_input_path: str | None = None
    metadata: Mapping[str, object] = field(default_factory=_empty_metadata)

    def __post_init__(self) -> None:
        _require_instance(self.instrument, InstrumentId, "instrument")
        _require_bool(self.opens_short, "opens_short")
        intent_id = _require_string(self.intent_id, "intent_id").strip()
        account_label = _require_string(self.account_label, "account_label").strip()
        if not intent_id:
            raise ValueError("intent_id cannot be empty")
        if not account_label:
            raise ValueError("account_label cannot be empty")
        quantity = _require_decimal(self.quantity, "quantity")
        if quantity <= 0:
            raise ValueError("order intent quantity must be greater than zero")
        limit_price = _optional_decimal(self.limit_price, "limit_price")
        stop_price = _optional_decimal(self.stop_price, "stop_price")
        if limit_price is not None and limit_price <= 0:
            raise ValueError("limit_price must be greater than zero")
        if stop_price is not None and stop_price <= 0:
            raise ValueError("stop_price must be greater than zero")
        side = _require_enum(self.side, OrderSide, "side")
        order_type = _require_enum(self.order_type, OrderType, "order_type")
        time_in_force = _require_enum(self.time_in_force, TimeInForce, "time_in_force")
        if self.opens_short and side is not OrderSide.SELL:
            raise ValueError("opens_short is only valid for SELL order intents")
        if order_type in {OrderType.LIMIT, OrderType.STOP_LIMIT} and limit_price is None:
            raise ValueError(f"{order_type.value} orders require limit_price")
        if order_type in {OrderType.STOP, OrderType.STOP_LIMIT} and stop_price is None:
            raise ValueError(f"{order_type.value} orders require stop_price")
        object.__setattr__(self, "intent_id", intent_id)
        object.__setattr__(self, "account_label", account_label)
        object.__setattr__(self, "side", side)
        object.__setattr__(self, "order_type", order_type)
        object.__setattr__(self, "time_in_force", time_in_force)
        object.__setattr__(self, "quantity", quantity)
        object.__setattr__(self, "limit_price", limit_price)
        object.__setattr__(self, "stop_price", stop_price)
        object.__setattr__(self, "created_at", _aware_utc(self.created_at, "created_at"))
        if self.target_as_of is not None:
            object.__setattr__(
                self,
                "target_as_of",
                _aware_utc(self.target_as_of, "target_as_of"),
            )
        object.__setattr__(self, "approval_id", _optional_string(self.approval_id, "approval_id"))
        object.__setattr__(self, "broker_name", _optional_string(self.broker_name, "broker_name"))
        object.__setattr__(self, "run_id", _optional_string(self.run_id, "run_id"))
        object.__setattr__(
            self,
            "target_source",
            _optional_string(self.target_source, "target_source"),
        )
        object.__setattr__(
            self,
            "target_input_path",
            _optional_string(self.target_input_path, "target_input_path"),
        )
        object.__setattr__(self, "metadata", _freeze_metadata(self.metadata))


@dataclass(frozen=True, slots=True)
class OrderEvent:
    """Immutable broker order event normalized into qexec semantics."""

    event_id: str
    event_type: ExecutionEventType
    occurred_at: datetime
    instrument: InstrumentId
    status: OrderStatus
    broker_name: str
    account_label: str
    broker_order_id: str
    intent_id: str | None = None
    client_order_id: str | None = None
    side: OrderSide | None = None
    quantity: Decimal | None = None
    filled_quantity: Decimal | None = None
    remaining_quantity: Decimal | None = None
    average_fill_price: Decimal | None = None
    message: str | None = None
    metadata: Mapping[str, object] = field(default_factory=_empty_metadata)

    def __post_init__(self) -> None:
        _require_instance(self.instrument, InstrumentId, "instrument")
        for field_name, field_value in (
            ("event_id", self.event_id),
            ("broker_name", self.broker_name),
            ("account_label", self.account_label),
            ("broker_order_id", self.broker_order_id),
        ):
            normalized = _require_string(field_value, field_name).strip()
            if not normalized:
                raise ValueError(f"{field_name} cannot be empty")
            object.__setattr__(self, field_name, normalized)
        object.__setattr__(
            self,
            "event_type",
            _require_enum(self.event_type, ExecutionEventType, "event_type"),
        )
        object.__setattr__(
            self,
            "status",
            _require_enum(self.status, OrderStatus, "status"),
        )
        if self.side is not None:
            object.__setattr__(self, "side", _require_enum(self.side, OrderSide, "side"))
        object.__setattr__(self, "occurred_at", _aware_utc(self.occurred_at, "occurred_at"))
        for field_name in ("quantity", "filled_quantity", "remaining_quantity"):
            value = _optional_decimal(getattr(self, field_name), field_name)
            if value is not None and value < 0:
                raise ValueError(f"{field_name} cannot be negative")
            object.__setattr__(self, field_name, value)
        average_fill_price = _optional_decimal(self.average_fill_price, "average_fill_price")
        if average_fill_price is not None and average_fill_price <= 0:
            raise ValueError("average_fill_price must be greater than zero")
        object.__setattr__(self, "average_fill_price", average_fill_price)
        object.__setattr__(self, "intent_id", _optional_string(self.intent_id, "intent_id"))
        object.__setattr__(
            self,
            "client_order_id",
            _optional_string(self.client_order_id, "client_order_id"),
        )
        object.__setattr__(self, "message", _optional_string(self.message, "message"))
        object.__setattr__(self, "metadata", _freeze_metadata(self.metadata))


@dataclass(frozen=True, slots=True)
class Fill:
    """Immutable broker fill representation."""

    fill_id: str
    broker_order_id: str
    instrument: InstrumentId
    quantity: Decimal
    price: Decimal
    filled_at: datetime
    broker_name: str
    account_label: str
    intent_id: str | None = None
    side: OrderSide | None = None
    commission: Money | None = None
    metadata: Mapping[str, object] = field(default_factory=_empty_metadata)

    def __post_init__(self) -> None:
        _require_instance(self.instrument, InstrumentId, "instrument")
        if self.commission is not None:
            _require_instance(self.commission, Money, "commission")
        for field_name, field_value in (
            ("fill_id", self.fill_id),
            ("broker_order_id", self.broker_order_id),
            ("broker_name", self.broker_name),
            ("account_label", self.account_label),
        ):
            normalized = _require_string(field_value, field_name).strip()
            if not normalized:
                raise ValueError(f"{field_name} cannot be empty")
            object.__setattr__(self, field_name, normalized)
        if self.side is not None:
            object.__setattr__(self, "side", _require_enum(self.side, OrderSide, "side"))
        quantity = _require_decimal(self.quantity, "quantity")
        price = _require_decimal(self.price, "price")
        if quantity <= 0:
            raise ValueError("fill quantity must be greater than zero")
        if price <= 0:
            raise ValueError("fill price must be greater than zero")
        object.__setattr__(self, "quantity", quantity)
        object.__setattr__(self, "price", price)
        object.__setattr__(self, "filled_at", _aware_utc(self.filled_at, "filled_at"))
        object.__setattr__(self, "intent_id", _optional_string(self.intent_id, "intent_id"))
        object.__setattr__(self, "metadata", _freeze_metadata(self.metadata))

    @property
    def notional(self) -> Money | None:
        """Return fill notional when the instrument currency is known."""

        if self.instrument.currency is None:
            return None
        return Money(self.quantity * self.price, self.instrument.currency)


@dataclass(frozen=True, slots=True)
class ExecutionCapabilities:
    """Capabilities used to validate domain values before transport mapping."""

    supports_short: bool = False
    supports_fractional: bool = False
    supported_order_types: frozenset[OrderType] = field(
        default_factory=lambda: frozenset({OrderType.MARKET})
    )
    supported_time_in_force: frozenset[TimeInForce] = field(
        default_factory=lambda: frozenset({TimeInForce.DAY})
    )
    quantity_increment: Decimal | None = None

    def __post_init__(self) -> None:
        _require_bool(self.supports_short, "supports_short")
        _require_bool(self.supports_fractional, "supports_fractional")
        for order_type in self.supported_order_types:
            _require_enum(order_type, OrderType, "supported_order_types")
        for time_in_force in self.supported_time_in_force:
            _require_enum(time_in_force, TimeInForce, "supported_time_in_force")
        if self.quantity_increment is not None:
            increment = _require_decimal(self.quantity_increment, "quantity_increment")
            if increment <= 0:
                raise ValueError("quantity_increment must be greater than zero")
            object.__setattr__(self, "quantity_increment", increment)
        if not self.supported_order_types:
            raise ValueError("supported_order_types cannot be empty")
        if not self.supported_time_in_force:
            raise ValueError("supported_time_in_force cannot be empty")


class CapabilityValidationError(ValueError):
    """Raised when a valid domain object cannot be executed by a backend."""

    def __init__(self, violations: tuple[str, ...]) -> None:
        self.violations = violations
        super().__init__("; ".join(violations))


def _is_fractional(value: Decimal) -> bool:
    return value != value.to_integral_value()


def portfolio_target_capability_violations(
    target: PortfolioTarget,
    capabilities: ExecutionCapabilities,
) -> tuple[str, ...]:
    """Return capability violations without mutating the target."""

    violations: list[str] = []
    signed_value = target.target_quantity
    if signed_value is None:
        signed_value = target.target_weight
    if signed_value is not None and signed_value < 0 and not capabilities.supports_short:
        violations.append("negative target requires short-selling capability")
    quantity = target.target_quantity
    if quantity is not None:
        magnitude = abs(quantity)
        if _is_fractional(magnitude) and not capabilities.supports_fractional:
            violations.append("fractional target quantity is not supported")
        if (
            capabilities.quantity_increment is not None
            and magnitude % capabilities.quantity_increment != 0
        ):
            violations.append(
                f"target quantity must align to increment {capabilities.quantity_increment}"
            )
    return tuple(violations)


def order_intent_capability_violations(
    intent: OrderIntent,
    capabilities: ExecutionCapabilities,
) -> tuple[str, ...]:
    """Return capability violations without mutating the order intent."""

    violations: list[str] = []
    if intent.opens_short and not capabilities.supports_short:
        violations.append("short-sale order intent is not supported")
    if _is_fractional(intent.quantity) and not capabilities.supports_fractional:
        violations.append("fractional order quantity is not supported")
    if (
        capabilities.quantity_increment is not None
        and intent.quantity % capabilities.quantity_increment != 0
    ):
        violations.append(
            f"order quantity must align to increment {capabilities.quantity_increment}"
        )
    if intent.order_type not in capabilities.supported_order_types:
        violations.append(f"order type {intent.order_type.value} is not supported")
    if intent.time_in_force not in capabilities.supported_time_in_force:
        violations.append(f"time in force {intent.time_in_force.value} is not supported")
    return tuple(violations)


def validate_portfolio_target_capabilities(
    target: PortfolioTarget,
    capabilities: ExecutionCapabilities,
) -> None:
    """Raise when a portfolio target is not supported by the capabilities."""

    violations = portfolio_target_capability_violations(target, capabilities)
    if violations:
        raise CapabilityValidationError(violations)


def validate_order_intent_capabilities(
    intent: OrderIntent,
    capabilities: ExecutionCapabilities,
) -> None:
    """Raise when an order intent is not supported by the capabilities."""

    violations = order_intent_capability_violations(intent, capabilities)
    if violations:
        raise CapabilityValidationError(violations)


__all__ = [
    "ApprovedTarget",
    "CapabilityValidationError",
    "ExecutionCapabilities",
    "ExecutionEventType",
    "Fill",
    "InstrumentId",
    "Money",
    "OrderEvent",
    "OrderIntent",
    "OrderSide",
    "OrderStatus",
    "OrderType",
    "PortfolioTarget",
    "TimeInForce",
    "order_intent_capability_violations",
    "portfolio_target_capability_violations",
    "validate_order_intent_capabilities",
    "validate_portfolio_target_capabilities",
]
