"""Execution capability validation against the typed domain models."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from ._domain_enums import (
    OrderType,
    TimeInForce,
    _require_bool,
    _require_decimal,
    _require_enum,
)
from ._domain_models import OrderIntent, PortfolioTarget


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
