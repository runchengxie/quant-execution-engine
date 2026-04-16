import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import quant_execution_engine.preflight as preflight
from quant_execution_engine.broker.base import ResolvedBrokerAccount
from quant_execution_engine.logging import set_run_id
from quant_execution_engine.models import (
    AccountSnapshot,
    Order,
    Position,
    Quote,
    RebalanceResult,
)
from quant_execution_engine.rebalance import RebalanceService
from quant_execution_engine.renderers.diff import render_rebalance_diff
from quant_execution_engine.risk import RiskGateChain, summarize_risk_decisions

pytestmark = pytest.mark.unit


def test_summarize_risk_decisions_separates_disabled_and_market_data_bypasses() -> None:
    order = Order(symbol="AAPL.US", quantity=10, side="BUY", price=10.0)
    disabled = summarize_risk_decisions(RiskGateChain({}).evaluate(order))
    missing_data = summarize_risk_decisions(
        RiskGateChain(
            {
                "max_spread_bps": 5,
                "max_participation_rate": 0.1,
                "max_market_impact_bps": 20,
            }
        ).evaluate(
            order,
            quote=Quote(
                symbol="AAPL.US",
                price=10.0,
                timestamp="2026-04-16T00:00:00Z",
            ),
        )
    )

    assert disabled.disabled_bypass_count == 3
    assert disabled.market_data_bypass_count == 0
    assert missing_data.market_data_bypass_count == 3
    assert missing_data.disabled_bypass_count == 0


class _PreflightAdapter:
    def resolve_account(
        self,
        account_label: str | None = None,
    ) -> ResolvedBrokerAccount:
        return ResolvedBrokerAccount(label=account_label or "main")

    def get_account_snapshot(
        self,
        account: ResolvedBrokerAccount,
        *,
        include_quotes: bool = False,
    ) -> AccountSnapshot:
        return AccountSnapshot(env="paper", cash_usd=1000.0, positions=[])

    def get_quotes(
        self,
        symbols: list[str],
        *,
        include_depth: bool = False,
    ) -> dict[str, Quote]:
        return {
            symbol: Quote(
                symbol=symbol,
                price=10.0,
                timestamp="2026-04-16T00:00:00Z",
                bid=None,
                ask=None,
                daily_volume=None,
            )
            for symbol in symbols
        }

    def close(self) -> None:
        return None


def test_preflight_surfaces_market_data_dependent_risk_bypasses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        preflight,
        "resolve_broker_name",
        lambda broker_name: "fake-paper",
    )
    monkeypatch.setattr(preflight, "is_paper_broker", lambda broker_name: True)
    monkeypatch.setattr(
        preflight,
        "get_broker_capabilities",
        lambda broker_name: SimpleNamespace(
            supports_live_submit=True,
            supports_cancel=True,
            supports_order_query=True,
            supports_reconcile=True,
            supports_account_selection=False,
        ),
    )
    monkeypatch.setattr(
        preflight,
        "validate_live_execution_guard",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        preflight,
        "is_manual_kill_switch_active",
        lambda: (False, None),
    )
    monkeypatch.setattr(preflight, "get_kill_switch_config", lambda: {})
    monkeypatch.setattr(
        preflight,
        "ExecutionStateStore",
        lambda: SimpleNamespace(
            load=lambda broker_name, account_label: SimpleNamespace(
                kill_switch_active=False,
                kill_switch_reason=None,
                consecutive_failures=0,
            )
        ),
    )
    monkeypatch.setattr(
        preflight,
        "get_broker_adapter",
        lambda broker_name: _PreflightAdapter(),
    )
    monkeypatch.setattr(
        preflight,
        "RiskGateChain",
        lambda: RiskGateChain(
            {
                "max_spread_bps": 5,
                "max_participation_rate": 0.1,
                "max_market_impact_bps": 20,
            }
        ),
    )

    result = preflight.run_preflight_checks(
        broker_name="fake-paper",
        account_label="main",
        symbols=["AAPL.US"],
    )

    check = next(
        item for item in result.checks if item.name == "risk_market_data_gates"
    )
    assert check.outcome == "WARN"
    assert "spread_guard" in check.message
    assert "participation_guard" in check.message
    assert "market_impact_guard" in check.message
    assert {item["gate"] for item in check.details["degraded_gates"]} == {
        "spread_guard",
        "participation_guard",
        "market_impact_guard",
    }


def test_rebalance_audit_and_output_include_risk_bypass_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    set_run_id("risk-run")
    order = Order(symbol="AAPL.US", quantity=10, side="BUY", price=10.0)
    order.risk_decisions = [
        decision.to_payload()
        for decision in RiskGateChain(
            {
                "max_spread_bps": 5,
                "max_participation_rate": 0.1,
                "max_market_impact_bps": 20,
            }
        ).evaluate(
            order,
            quote=Quote(
                symbol="AAPL.US",
                price=10.0,
                timestamp="2026-04-16T00:00:00Z",
            ),
        )
    ]
    result = RebalanceResult(
        target_positions=[
            Position(
                symbol="AAPL.US",
                quantity=10,
                last_price=10.0,
                estimated_value=100.0,
            )
        ],
        current_positions=[],
        orders=[order],
        total_portfolio_value=1000.0,
        target_value_per_stock=100.0,
        dry_run=False,
        env="paper",
        target_source="unit",
        target_asof="2026-04-16",
        target_input_path="outputs/targets/unit.json",
        broker_name="fake-paper",
        account_label="main",
    )

    audit_path = RebalanceService(
        env="paper",
        broker_name="fake-paper",
        account_label="main",
    ).save_audit_log(result, dry_run=False)
    output = render_rebalance_diff(
        result,
        AccountSnapshot(env="paper", cash_usd=1000.0, positions=[]),
    ).text

    records = [
        json.loads(line)
        for line in audit_path.read_text(encoding="utf-8").splitlines()
    ]
    summary, audit_order = records
    assert summary["risk_decision_summary"]["market_data_bypass_count"] == 3
    assert audit_order["risk_decision_summary"]["bypass_count"] == 3
    assert audit_order["risk_decision_summary"]["disabled_bypass_count"] == 0
    assert "Risk BYPASS: 3 bypassed" in output
    assert "market-data degraded" in output
