"""Execution risk gates and kill-switch helpers."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import load_cfg
from .models import Order, Quote


@dataclass(slots=True)
class RiskDecision:
    """Structured risk gate result."""

    gate: str
    outcome: str
    reason: str
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {
            "gate": self.gate,
            "outcome": self.outcome,
            "reason": self.reason,
            "metrics": dict(self.metrics),
        }


def _execution_cfg() -> dict[str, Any]:
    cfg = load_cfg() or {}
    execution = cfg.get("execution") or {}
    return execution if isinstance(execution, dict) else {}


def get_risk_config() -> dict[str, Any]:
    """Return execution risk configuration."""

    risk_cfg = _execution_cfg().get("risk") or {}
    return risk_cfg if isinstance(risk_cfg, dict) else {}


def get_kill_switch_config() -> dict[str, Any]:
    """Return kill-switch configuration."""

    ks_cfg = _execution_cfg().get("kill_switch") or {}
    return ks_cfg if isinstance(ks_cfg, dict) else {}


def is_manual_kill_switch_active() -> tuple[bool, str | None]:
    """Check whether a manual kill switch has been activated."""

    cfg = get_kill_switch_config()
    env_var = str(cfg.get("env_var") or "QEXEC_KILL_SWITCH").strip() or "QEXEC_KILL_SWITCH"
    raw_env = os.getenv(env_var)
    if raw_env and str(raw_env).strip().lower() in {"1", "true", "yes", "on"}:
        return True, f"{env_var}=true"

    path_value = str(cfg.get("path") or "").strip()
    if path_value:
        path = Path(path_value)
        if not path.is_absolute():
            path = Path.cwd() / path
        if path.exists():
            return True, f"kill switch file exists: {path}"

    return False, None


class RiskGateChain:
    """Evaluate lightweight execution risk guards."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or get_risk_config()

    def needs_market_data(self) -> bool:
        return any(
            float(self.config.get(key, 0.0) or 0.0) > 0.0
            for key in (
                "max_spread_bps",
                "max_participation_rate",
                "max_market_impact_bps",
            )
        )

    def evaluate(
        self,
        order: Order,
        *,
        quote: Quote | None = None,
    ) -> list[RiskDecision]:
        decisions: list[RiskDecision] = []
        decisions.append(self._max_qty_or_notional(order))
        decisions.append(self._spread_guard(order, quote))
        decisions.append(self._participation_guard(order, quote))
        decisions.append(self._market_impact_guard(order, quote))
        return decisions

    def _max_qty_or_notional(self, order: Order) -> RiskDecision:
        max_qty = int(float(self.config.get("max_qty_per_order", 0) or 0))
        max_notional = float(self.config.get("max_notional_per_order", 0.0) or 0.0)
        est_notional = float(order.price or 0.0) * float(order.quantity)

        if max_qty > 0 and int(order.quantity) > max_qty:
            return RiskDecision(
                gate="max_qty_per_order",
                outcome="BLOCK",
                reason=f"quantity {order.quantity} exceeds max_qty_per_order {max_qty}",
                metrics={"quantity": order.quantity, "max_qty_per_order": max_qty},
            )
        if max_notional > 0 and est_notional > max_notional:
            return RiskDecision(
                gate="max_notional_per_order",
                outcome="BLOCK",
                reason=(
                    f"estimated notional {est_notional:.2f} exceeds "
                    f"max_notional_per_order {max_notional:.2f}"
                ),
                metrics={
                    "estimated_notional": est_notional,
                    "max_notional_per_order": max_notional,
                },
            )
        return RiskDecision(
            gate="max_size",
            outcome="PASS",
            reason="size limits passed",
            metrics={
                "quantity": order.quantity,
                "estimated_notional": est_notional,
            },
        )

    def _spread_guard(self, order: Order, quote: Quote | None) -> RiskDecision:
        threshold = float(self.config.get("max_spread_bps", 0.0) or 0.0)
        if threshold <= 0:
            return RiskDecision(
                gate="spread_guard",
                outcome="BYPASS",
                reason="spread guard disabled",
            )
        bid = float(getattr(quote, "bid", 0.0) or 0.0)
        ask = float(getattr(quote, "ask", 0.0) or 0.0)
        if bid <= 0 or ask <= 0 or ask < bid:
            return RiskDecision(
                gate="spread_guard",
                outcome="BYPASS",
                reason="bid/ask unavailable for spread check",
            )
        mid = (bid + ask) / 2.0
        spread_bps = ((ask - bid) / mid) * 10000 if mid > 0 else 0.0
        if spread_bps > threshold:
            return RiskDecision(
                gate="spread_guard",
                outcome="BLOCK",
                reason=f"spread {spread_bps:.2f}bps exceeds limit {threshold:.2f}bps",
                metrics={"bid": bid, "ask": ask, "spread_bps": spread_bps},
            )
        return RiskDecision(
            gate="spread_guard",
            outcome="PASS",
            reason="spread within configured limit",
            metrics={"bid": bid, "ask": ask, "spread_bps": spread_bps},
        )

    def _participation_guard(self, order: Order, quote: Quote | None) -> RiskDecision:
        threshold = float(self.config.get("max_participation_rate", 0.0) or 0.0)
        if threshold <= 0:
            return RiskDecision(
                gate="participation_guard",
                outcome="BYPASS",
                reason="participation guard disabled",
            )
        daily_volume = float(getattr(quote, "daily_volume", 0.0) or 0.0)
        if daily_volume <= 0:
            return RiskDecision(
                gate="participation_guard",
                outcome="BYPASS",
                reason="daily volume unavailable for participation check",
            )
        participation = float(order.quantity) / daily_volume
        if participation > threshold:
            return RiskDecision(
                gate="participation_guard",
                outcome="BLOCK",
                reason=(
                    f"participation {participation:.4f} exceeds limit {threshold:.4f}"
                ),
                metrics={
                    "quantity": order.quantity,
                    "daily_volume": daily_volume,
                    "participation_rate": participation,
                },
            )
        return RiskDecision(
            gate="participation_guard",
            outcome="PASS",
            reason="participation within configured limit",
            metrics={
                "quantity": order.quantity,
                "daily_volume": daily_volume,
                "participation_rate": participation,
            },
        )

    def _market_impact_guard(self, order: Order, quote: Quote | None) -> RiskDecision:
        threshold = float(self.config.get("max_market_impact_bps", 0.0) or 0.0)
        if threshold <= 0:
            return RiskDecision(
                gate="market_impact_guard",
                outcome="BYPASS",
                reason="market impact guard disabled",
            )
        daily_volume = float(getattr(quote, "daily_volume", 0.0) or 0.0)
        last_price = float(getattr(quote, "price", 0.0) or 0.0) or float(order.price or 0.0)
        if daily_volume <= 0 or last_price <= 0:
            return RiskDecision(
                gate="market_impact_guard",
                outcome="BYPASS",
                reason="insufficient market data for impact estimate",
            )
        participation = float(order.quantity) / daily_volume
        impact_bps = participation * 10000.0
        if impact_bps > threshold:
            return RiskDecision(
                gate="market_impact_guard",
                outcome="BLOCK",
                reason=(
                    f"impact estimate {impact_bps:.2f}bps exceeds limit {threshold:.2f}bps"
                ),
                metrics={
                    "estimated_impact_bps": impact_bps,
                    "participation_rate": participation,
                    "last_price": last_price,
                },
            )
        return RiskDecision(
            gate="market_impact_guard",
            outcome="PASS",
            reason="impact estimate within configured limit",
            metrics={
                "estimated_impact_bps": impact_bps,
                "participation_rate": participation,
                "last_price": last_price,
            },
        )
