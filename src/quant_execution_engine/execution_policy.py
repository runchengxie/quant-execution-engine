"""Execution policies for dynamic sizing, limit prices, and participation caps.

These functions operate only on approved target and market inputs. They do not
read research metrics or modify portfolio selection rules.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DynamicLimitConfig:
    """Configuration for AFML-style sigmoid target and limit-price policies."""

    max_position: int
    lot_size: int = 1
    max_participation_rate: float = 0.05
    minimum_order_quantity: int = 1

    def __post_init__(self) -> None:
        if self.max_position <= 0:
            raise ValueError("max_position must be > 0")
        if self.lot_size <= 0:
            raise ValueError("lot_size must be > 0")
        if not 0 < self.max_participation_rate <= 1:
            raise ValueError("max_participation_rate must be in (0, 1]")
        if self.minimum_order_quantity <= 0:
            raise ValueError("minimum_order_quantity must be > 0")


@dataclass(frozen=True)
class ExecutionPolicyDecision:
    """Reviewable output of a dynamic execution-policy calculation."""

    current_price: float
    forecast_price: float
    current_quantity: int
    raw_target_quantity: int
    target_quantity: int
    order_quantity: int
    participation_capped_quantity: int
    limit_price: float | None
    omega: float
    config: DynamicLimitConfig

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["config"] = asdict(self.config)
        return payload


def calibrate_sigmoid_width(
    *,
    price_divergence: float,
    target_size: float,
) -> float:
    """Calibrate omega so ``m=x/sqrt(omega+x^2)`` reaches target_size."""

    x = float(price_divergence)
    size = abs(float(target_size))
    if not math.isfinite(x) or x == 0:
        raise ValueError("price_divergence must be finite and non-zero")
    if not 0 < size < 1:
        raise ValueError("target_size must have absolute value in (0, 1)")
    return x * x * (1.0 / (size * size) - 1.0)


def sigmoid_bet_size(
    *,
    forecast_price: float,
    market_price: float,
    omega: float,
) -> float:
    """Return a continuous target intensity in (-1, 1)."""

    forecast = _positive_finite(forecast_price, "forecast_price")
    market = _positive_finite(market_price, "market_price")
    width = float(omega)
    if not math.isfinite(width) or width <= 0:
        raise ValueError("omega must be finite and > 0")
    divergence = forecast - market
    return divergence / math.sqrt(width + divergence * divergence)


def inverse_price_for_size(
    *,
    forecast_price: float,
    target_size: float,
    omega: float,
) -> float:
    """Invert the sigmoid and return the price consistent with a target size."""

    forecast = _positive_finite(forecast_price, "forecast_price")
    size = float(target_size)
    width = float(omega)
    if not -1 < size < 1:
        raise ValueError("target_size must be in (-1, 1)")
    if not math.isfinite(width) or width <= 0:
        raise ValueError("omega must be finite and > 0")
    divergence = math.sqrt(width) * size / math.sqrt(1.0 - size * size)
    price = forecast - divergence
    if price <= 0:
        raise ValueError("inverse target size implies a non-positive price")
    return price


def average_limit_price(
    *,
    forecast_price: float,
    current_size: float,
    target_size: float,
    omega: float,
) -> float | None:
    """Return the exact average inverse-sigmoid price over a position change.

    The formula integrates the inverse price function between normalized
    current and target positions. A zero position change returns ``None``.
    """

    forecast = _positive_finite(forecast_price, "forecast_price")
    current = float(current_size)
    target = float(target_size)
    width = float(omega)
    if not -1 < current < 1 or not -1 < target < 1:
        raise ValueError("current_size and target_size must be in (-1, 1)")
    if not math.isfinite(width) or width <= 0:
        raise ValueError("omega must be finite and > 0")
    change = target - current
    if abs(change) <= 1e-15:
        return None
    integral_adjustment = math.sqrt(width) * (
        math.sqrt(1.0 - target * target) - math.sqrt(1.0 - current * current)
    )
    limit = forecast + integral_adjustment / change
    if limit <= 0:
        raise ValueError("average limit price is non-positive")
    return limit


def discretize_quantity(quantity: float, *, lot_size: int) -> int:
    """Round a signed quantity to the nearest valid lot."""

    if lot_size <= 0:
        raise ValueError("lot_size must be > 0")
    if not math.isfinite(float(quantity)):
        raise ValueError("quantity must be finite")
    return int(round(float(quantity) / lot_size)) * lot_size


def participation_capped_quantity(
    requested_quantity: int,
    *,
    recent_market_volume: float | None,
    max_participation_rate: float,
    lot_size: int = 1,
) -> int:
    """Cap an order by a fraction of recent observable market volume."""

    requested = int(requested_quantity)
    if requested == 0:
        return 0
    if not 0 < max_participation_rate <= 1:
        raise ValueError("max_participation_rate must be in (0, 1]")
    if recent_market_volume is None:
        return requested
    volume = float(recent_market_volume)
    if not math.isfinite(volume) or volume < 0:
        raise ValueError("recent_market_volume must be finite and >= 0")
    cap = discretize_quantity(volume * max_participation_rate, lot_size=lot_size)
    capped = min(abs(requested), max(cap, 0))
    return int(math.copysign(capped, requested)) if capped > 0 else 0


def build_dynamic_execution_decision(
    *,
    current_price: float,
    forecast_price: float,
    current_quantity: int,
    omega: float,
    config: DynamicLimitConfig,
    recent_market_volume: float | None = None,
) -> ExecutionPolicyDecision:
    """Build a dynamic target, limit price, and participation-capped order."""

    market = _positive_finite(current_price, "current_price")
    forecast = _positive_finite(forecast_price, "forecast_price")
    normalized_target = sigmoid_bet_size(
        forecast_price=forecast,
        market_price=market,
        omega=omega,
    )
    raw_target = int(round(normalized_target * config.max_position))
    target = discretize_quantity(raw_target, lot_size=config.lot_size)
    target = max(-config.max_position, min(config.max_position, target))
    order = target - int(current_quantity)
    if abs(order) < config.minimum_order_quantity:
        order = 0
        target = int(current_quantity)

    capped_order = participation_capped_quantity(
        order,
        recent_market_volume=recent_market_volume,
        max_participation_rate=config.max_participation_rate,
        lot_size=config.lot_size,
    )
    current_size = max(-0.999999, min(0.999999, current_quantity / config.max_position))
    reachable_quantity = current_quantity + capped_order
    reachable_size = max(-0.999999, min(0.999999, reachable_quantity / config.max_position))
    limit = average_limit_price(
        forecast_price=forecast,
        current_size=current_size,
        target_size=reachable_size,
        omega=omega,
    )
    return ExecutionPolicyDecision(
        current_price=market,
        forecast_price=forecast,
        current_quantity=int(current_quantity),
        raw_target_quantity=raw_target,
        target_quantity=target,
        order_quantity=order,
        participation_capped_quantity=capped_order,
        limit_price=limit,
        omega=float(omega),
        config=config,
    )


def execution_policy_receipt(
    decision: ExecutionPolicyDecision,
    *,
    target_artifact_sha256: str | None = None,
) -> dict[str, Any]:
    """Create a deterministic audit receipt without research performance data."""

    payload = decision.to_dict()
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return {
        "schema_version": 1,
        "artifact_type": "quant_execution_engine.execution_policy_decision",
        "decision": payload,
        "target_artifact_sha256": target_artifact_sha256,
        "decision_sha256": hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
    }


def write_execution_policy_receipt(receipt: dict[str, Any], path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )


def _positive_finite(value: float, name: str) -> float:
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise ValueError(f"{name} must be finite and > 0")
    return result


__all__ = [
    "DynamicLimitConfig",
    "ExecutionPolicyDecision",
    "average_limit_price",
    "build_dynamic_execution_decision",
    "calibrate_sigmoid_width",
    "discretize_quantity",
    "execution_policy_receipt",
    "inverse_price_for_size",
    "participation_capped_quantity",
    "sigmoid_bet_size",
    "write_execution_policy_receipt",
]
