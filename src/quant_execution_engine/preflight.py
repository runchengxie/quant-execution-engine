"""Execution readiness checks."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .broker.factory import (
    get_broker_adapter,
    get_broker_capabilities,
    is_paper_broker,
    resolve_broker_name,
)
from .execution import ExecutionStateStore
from .guards import LIVE_ENABLE_ENV_VAR, validate_live_execution_guard
from .risk import RiskGateChain, get_kill_switch_config, is_manual_kill_switch_active


@dataclass(slots=True)
class PreflightCheck:
    """Single readiness check."""

    name: str
    outcome: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PreflightResult:
    """Broker/account preflight summary."""

    broker_name: str
    account_label: str
    env_name: str
    symbols: list[str]
    checks: list[PreflightCheck]

    @property
    def has_failures(self) -> bool:
        return any(check.outcome == "FAIL" for check in self.checks)

    @property
    def has_warnings(self) -> bool:
        return any(check.outcome == "WARN" for check in self.checks)


def _quote_market_data_health(
    quotes: dict[str, Any],
    *,
    require_depth: bool,
) -> tuple[str, str]:
    if not quotes:
        return "FAIL", "quote lookup returned no symbols"
    if not require_depth:
        return "PASS", f"retrieved quotes for {len(quotes)} symbol(s)"

    missing_depth = [
        symbol
        for symbol, quote in quotes.items()
        if getattr(quote, "bid", None) in (None, 0)
        or getattr(quote, "ask", None) in (None, 0)
    ]
    missing_volume = [
        symbol
        for symbol, quote in quotes.items()
        if getattr(quote, "daily_volume", None) in (None, 0)
    ]
    if not missing_depth and not missing_volume:
        return "PASS", f"retrieved depth/volume for {len(quotes)} symbol(s)"

    parts: list[str] = []
    if missing_depth:
        parts.append(f"missing bid/ask for {', '.join(sorted(missing_depth))}")
    if missing_volume:
        parts.append(f"missing daily volume for {', '.join(sorted(missing_volume))}")
    return "WARN", "; ".join(parts)


def _missing_quote_fields(quote: Any, fields: list[str]) -> list[str]:
    missing: list[str] = []
    for field_name in fields:
        value = getattr(quote, field_name, None) if quote is not None else None
        if value in (None, 0):
            missing.append(field_name)
    return missing


def _risk_market_data_check(
    risk_chain: RiskGateChain,
    quotes: dict[str, Any],
) -> PreflightCheck | None:
    dependencies = risk_chain.configured_market_data_dependencies()
    if not dependencies:
        return None

    degraded: list[dict[str, Any]] = []
    for dependency in dependencies:
        missing_by_symbol: dict[str, list[str]] = {}
        fields = list(dependency["required_fields"])
        for symbol, quote in quotes.items():
            missing = _missing_quote_fields(quote, fields)
            if missing:
                missing_by_symbol[symbol] = missing
        if missing_by_symbol:
            degraded.append(
                {
                    "gate": dependency["gate"],
                    "config_key": dependency["config_key"],
                    "threshold": dependency["threshold"],
                    "required_fields": fields,
                    "missing_by_symbol": missing_by_symbol,
                    "expected_runtime_outcome": "BYPASS",
                }
            )

    details = {
        "configured_market_data_gates": dependencies,
        "degraded_gates": degraded,
    }
    if not degraded:
        return PreflightCheck(
            name="risk_market_data_gates",
            outcome="PASS",
            message=(
                "configured market-data-dependent risk gates have required "
                "quote fields"
            ),
            details=details,
        )

    parts = []
    for item in degraded:
        symbols = ", ".join(sorted(item["missing_by_symbol"]))
        required = "/".join(item["required_fields"])
        parts.append(f"{item['gate']} missing {required} for {symbols}")
    return PreflightCheck(
        name="risk_market_data_gates",
        outcome="WARN",
        message="configured risk gates may BYPASS: " + "; ".join(parts),
        details=details,
    )


def run_preflight_checks(
    *,
    broker_name: str | None = None,
    account_label: str = "main",
    symbols: list[str] | None = None,
) -> PreflightResult:
    """Run broker/account readiness checks without mutating broker state."""

    selected_broker = resolve_broker_name(broker_name)
    env_name = "paper" if is_paper_broker(selected_broker) else "real"
    requested_symbols = [
        str(symbol).strip()
        for symbol in (symbols or ["AAPL"])
        if str(symbol).strip()
    ]
    checks: list[PreflightCheck] = []

    capabilities = get_broker_capabilities(selected_broker)
    checks.append(
        PreflightCheck(
            name="capabilities",
            outcome="PASS",
            message=(
                f"live_submit={capabilities.supports_live_submit}, "
                f"cancel={capabilities.supports_cancel}, "
                f"query={capabilities.supports_order_query}, "
                f"reconcile={capabilities.supports_reconcile}, "
                f"account_selection={capabilities.supports_account_selection}"
            ),
            details={
                "supports_live_submit": capabilities.supports_live_submit,
                "supports_cancel": capabilities.supports_cancel,
                "supports_order_query": capabilities.supports_order_query,
                "supports_reconcile": capabilities.supports_reconcile,
                "supports_account_selection": capabilities.supports_account_selection,
            },
        )
    )

    guard_error = validate_live_execution_guard(env_name=env_name, dry_run=False)
    checks.append(
        PreflightCheck(
            name="live_guard",
            outcome="FAIL" if guard_error else "PASS",
            message=guard_error
            or (
                "paper broker path does not require live guard"
                if env_name == "paper"
                else (
                    f"live execution guard satisfied ({LIVE_ENABLE_ENV_VAR}=1 "
                    "and no repo-local live secrets)"
                )
            ),
        )
    )

    manual_kill_active, manual_kill_reason = is_manual_kill_switch_active()
    checks.append(
        PreflightCheck(
            name="manual_kill_switch",
            outcome="FAIL" if manual_kill_active else "PASS",
            message=manual_kill_reason or "manual kill switch not active",
            details={
                "env_var": (
                    get_kill_switch_config().get("env_var")
                    or "QEXEC_KILL_SWITCH"
                )
            },
        )
    )

    adapter = get_broker_adapter(broker_name=selected_broker)
    resolved_account_label = account_label
    try:
        try:
            resolved_account = adapter.resolve_account(account_label)
            resolved_account_label = resolved_account.label
            checks.append(
                PreflightCheck(
                    name="account_resolution",
                    outcome="PASS",
                    message=f"resolved account label '{resolved_account.label}'",
                )
            )
        except Exception as exc:
            checks.append(
                PreflightCheck(
                    name="account_resolution",
                    outcome="FAIL",
                    message=str(exc),
                )
            )
            return PreflightResult(
                broker_name=selected_broker,
                account_label=resolved_account_label,
                env_name=env_name,
                symbols=requested_symbols,
                checks=checks,
            )

        state = ExecutionStateStore().load(selected_broker, resolved_account.label)
        state_kill_message = (
            state.kill_switch_reason
            or (
                "local execution state kill switch active with "
                f"{state.consecutive_failures} consecutive failures"
            )
        )
        checks.append(
            PreflightCheck(
                name="state_kill_switch",
                outcome="FAIL" if state.kill_switch_active else "PASS",
                message=(
                    state_kill_message
                    if state.kill_switch_active
                    else "local state kill switch not active"
                ),
                details={"consecutive_failures": state.consecutive_failures},
            )
        )

        try:
            snapshot = adapter.get_account_snapshot(
                resolved_account,
                include_quotes=False,
            )
            checks.append(
                PreflightCheck(
                    name="account_snapshot",
                    outcome="PASS",
                    message=(
                        f"cash={float(snapshot.cash_usd or 0.0):.2f}, "
                        f"positions={len(snapshot.positions)}, "
                        "portfolio_value="
                        f"{float(snapshot.total_portfolio_value or 0.0):.2f}"
                    ),
                )
            )
        except Exception as exc:
            checks.append(
                PreflightCheck(
                    name="account_snapshot",
                    outcome="FAIL",
                    message=str(exc),
                )
            )
            return PreflightResult(
                broker_name=selected_broker,
                account_label=resolved_account_label,
                env_name=env_name,
                symbols=requested_symbols,
                checks=checks,
            )

        risk_chain = RiskGateChain()
        require_depth = risk_chain.needs_market_data()
        try:
            quotes = adapter.get_quotes(requested_symbols, include_depth=require_depth)
            quote_outcome, quote_message = _quote_market_data_health(
                quotes, require_depth=require_depth
            )
            checks.append(
                PreflightCheck(
                    name="quotes",
                    outcome=quote_outcome,
                    message=quote_message,
                    details={
                        "requested_symbols": requested_symbols,
                        "returned_symbols": sorted(quotes),
                    },
                )
            )
            risk_market_data_check = _risk_market_data_check(risk_chain, quotes)
            if risk_market_data_check is not None:
                checks.append(risk_market_data_check)
        except Exception as exc:
            checks.append(
                PreflightCheck(
                    name="quotes",
                    outcome="FAIL",
                    message=str(exc),
                    details={"requested_symbols": requested_symbols},
                )
            )
    finally:
        close_fn = getattr(adapter, "close", None)
        if callable(close_fn):
            close_fn()

    return PreflightResult(
        broker_name=selected_broker,
        account_label=resolved_account_label,
        env_name=env_name,
        symbols=requested_symbols,
        checks=checks,
    )
