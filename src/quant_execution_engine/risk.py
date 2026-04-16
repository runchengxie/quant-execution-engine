"""Execution risk gates and kill-switch helpers."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import load_cfg
from .models import Order, Quote

MARKET_DATA_BYPASS_REASONS = (
    "bid/ask unavailable",
    "daily volume unavailable",
    "insufficient market data",
    "market data unavailable",
)


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


@dataclass(slots=True)
class RiskDecisionSummary:
    """Grouped risk decision counts for operator and audit output."""

    pass_count: int = 0
    block_count: int = 0
    bypass_count: int = 0
    disabled_bypass_count: int = 0
    market_data_bypass_count: int = 0
    other_bypass_count: int = 0
    bypass_reasons: list[dict[str, Any]] = field(default_factory=list)
    block_reasons: list[dict[str, Any]] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        return {
            "pass_count": self.pass_count,
            "block_count": self.block_count,
            "bypass_count": self.bypass_count,
            "disabled_bypass_count": self.disabled_bypass_count,
            "market_data_bypass_count": self.market_data_bypass_count,
            "other_bypass_count": self.other_bypass_count,
            "bypass_reasons": list(self.bypass_reasons),
            "block_reasons": list(self.block_reasons),
        }


RiskDecisionLike = RiskDecision | dict[str, Any]


def _decision_value(decision: RiskDecisionLike, key: str) -> Any:
    if isinstance(decision, RiskDecision):
        return getattr(decision, key)
    return decision.get(key)


def _classify_bypass_reason(reason: str) -> str:
    normalized = reason.lower()
    if "disabled" in normalized:
        return "disabled"
    if any(token in normalized for token in MARKET_DATA_BYPASS_REASONS):
        return "market_data_degraded"
    return "other"


def summarize_risk_decisions(
    decisions: list[RiskDecisionLike] | tuple[RiskDecisionLike, ...],
) -> RiskDecisionSummary:
    """Group risk decisions by outcome and bypass reason class."""

    summary = RiskDecisionSummary()
    for decision in decisions:
        outcome = str(_decision_value(decision, "outcome") or "").upper()
        gate = str(_decision_value(decision, "gate") or "")
        reason = str(_decision_value(decision, "reason") or "")
        metrics = _decision_value(decision, "metrics") or {}
        if outcome == "PASS":
            summary.pass_count += 1
        elif outcome == "BLOCK":
            summary.block_count += 1
            summary.block_reasons.append(
                {"gate": gate, "reason": reason, "metrics": dict(metrics)}
            )
        elif outcome == "BYPASS":
            summary.bypass_count += 1
            classification = _classify_bypass_reason(reason)
            if classification == "disabled":
                summary.disabled_bypass_count += 1
            elif classification == "market_data_degraded":
                summary.market_data_bypass_count += 1
            else:
                summary.other_bypass_count += 1
            summary.bypass_reasons.append(
                {
                    "gate": gate,
                    "reason": reason,
                    "classification": classification,
                    "metrics": dict(metrics),
                }
            )
    return summary


def format_risk_bypass_summary(
    summary: RiskDecisionSummary | dict[str, Any],
) -> str | None:
    """Return a compact operator-facing bypass summary."""

    payload = (
        summary.to_payload()
        if isinstance(summary, RiskDecisionSummary)
        else summary
    )
    bypass_count = int(payload.get("bypass_count") or 0)
    if bypass_count <= 0:
        return None
    parts = [f"{bypass_count} bypassed"]
    market_data_count = int(payload.get("market_data_bypass_count") or 0)
    disabled_count = int(payload.get("disabled_bypass_count") or 0)
    other_count = int(payload.get("other_bypass_count") or 0)
    if market_data_count:
        parts.append(f"{market_data_count} market-data degraded")
    if disabled_count:
        parts.append(f"{disabled_count} disabled")
    if other_count:
        parts.append(f"{other_count} other")
    reasons = payload.get("bypass_reasons") or []
    reason_text = "; ".join(
        f"{item.get('gate')}: {item.get('reason')}"
        for item in reasons
        if item.get("gate")
    )
    if reason_text:
        parts.append(reason_text)
    return " | ".join(parts)


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
    env_var = (
        str(cfg.get("env_var") or "QEXEC_KILL_SWITCH").strip()
        or "QEXEC_KILL_SWITCH"
    )
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

    def configured_market_data_dependencies(self) -> list[dict[str, Any]]:
        """Return configured market-data gates and fields needed to avoid BYPASS."""

        dependencies: list[dict[str, Any]] = []
        spread_threshold = float(self.config.get("max_spread_bps", 0.0) or 0.0)
        if spread_threshold > 0:
            dependencies.append(
                {
                    "gate": "spread_guard",
                    "config_key": "max_spread_bps",
                    "threshold": spread_threshold,
                    "required_fields": ["bid", "ask"],
                }
            )
        participation_threshold = float(
            self.config.get("max_participation_rate", 0.0) or 0.0
        )
        if participation_threshold > 0:
            dependencies.append(
                {
                    "gate": "participation_guard",
                    "config_key": "max_participation_rate",
                    "threshold": participation_threshold,
                    "required_fields": ["daily_volume"],
                }
            )
        impact_threshold = float(self.config.get("max_market_impact_bps", 0.0) or 0.0)
        if impact_threshold > 0:
            dependencies.append(
                {
                    "gate": "market_impact_guard",
                    "config_key": "max_market_impact_bps",
                    "threshold": impact_threshold,
                    "required_fields": ["price", "daily_volume"],
                }
            )
        return dependencies

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
        last_price = float(getattr(quote, "price", 0.0) or 0.0) or float(
            order.price or 0.0
        )
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
                    f"impact estimate {impact_bps:.2f}bps exceeds limit "
                    f"{threshold:.2f}bps"
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
