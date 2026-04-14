from __future__ import annotations

from pathlib import Path

import pytest

from quant_execution_engine.broker.base import (
    BrokerAdapter,
    BrokerCapabilityMatrix,
    BrokerOrderRecord,
    BrokerOrderRequest,
    BrokerReconcileReport,
    ResolvedBrokerAccount,
)
from quant_execution_engine.broker.factory import get_broker_capabilities
from quant_execution_engine.execution import (
    ExecutionState,
    ExecutionStateStore,
    OrderLifecycleService,
)
from quant_execution_engine.models import Order, Quote
from quant_execution_engine.risk import RiskGateChain


pytestmark = pytest.mark.unit


class FakeAdapter(BrokerAdapter):
    backend_name = "fake"
    capabilities = BrokerCapabilityMatrix(
        name="fake",
        supports_live_submit=True,
        supports_cancel=True,
        supports_order_query=True,
        supports_open_order_listing=True,
        supports_reconcile=True,
    )

    def __init__(self) -> None:
        self.submit_calls = 0
        self.orders: dict[str, BrokerOrderRecord] = {}

    def resolve_account(self, account_label: str | None = None) -> ResolvedBrokerAccount:
        label = account_label or "main"
        return ResolvedBrokerAccount(label=label)

    def get_quotes(
        self, symbols: list[str], *, include_depth: bool = False
    ) -> dict[str, Quote]:
        return {
            symbol: Quote(
                symbol=symbol,
                price=10.0,
                timestamp="2026-04-14T00:00:00Z",
                bid=9.99 if include_depth else None,
                ask=10.01 if include_depth else None,
                daily_volume=100000.0,
            )
            for symbol in symbols
        }

    def submit_order(self, request: BrokerOrderRequest) -> BrokerOrderRecord:
        self.submit_calls += 1
        record = BrokerOrderRecord(
            broker_order_id=f"fake-{request.client_order_id}",
            symbol=request.symbol,
            side=request.side,
            quantity=request.quantity,
            status="NEW",
            broker_name=self.backend_name,
            account_label=request.account.label if request.account else "main",
            client_order_id=request.client_order_id,
        )
        self.orders[record.broker_order_id] = record
        return record

    def list_open_orders(
        self,
        account: ResolvedBrokerAccount | None = None,
    ) -> list[BrokerOrderRecord]:
        return list(self.orders.values())

    def get_order(
        self,
        broker_order_id: str,
        account: ResolvedBrokerAccount | None = None,
    ) -> BrokerOrderRecord:
        return self.orders[broker_order_id]

    def reconcile(
        self,
        account: ResolvedBrokerAccount | None = None,
    ) -> BrokerReconcileReport:
        resolved = account or self.resolve_account()
        return BrokerReconcileReport(
            broker_name=self.backend_name,
            account_label=resolved.label,
            open_orders=self.list_open_orders(resolved),
            fills=[],
        )


def test_execution_state_store_round_trip(tmp_path: Path) -> None:
    store = ExecutionStateStore(root_dir=tmp_path)
    state = ExecutionState(broker_name="fake", account_label="main")
    state.consecutive_failures = 2
    store.save(state)

    loaded = store.load("fake", "main")

    assert loaded.broker_name == "fake"
    assert loaded.account_label == "main"
    assert loaded.consecutive_failures == 2


def test_risk_gate_blocks_oversized_order(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    service = OrderLifecycleService(
        adapter,
        state_store=ExecutionStateStore(root_dir=tmp_path),
        risk_chain=RiskGateChain({"max_qty_per_order": 5}),
    )
    order = Order(symbol="AAPL.US", quantity=10, side="BUY", price=10.0)

    results = service.execute_orders(
        [order],
        account_label="main",
        dry_run=False,
        target_source="unit",
        target_asof="2026-04-14",
        target_input_path="tests/targets.json",
    )

    assert results[0].status == "BLOCKED"
    assert "max_qty_per_order" in str(results[0].risk_decisions)
    assert adapter.submit_calls == 0


def test_idempotent_submission_reuses_existing_open_order(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    store = ExecutionStateStore(root_dir=tmp_path)
    service = OrderLifecycleService(
        adapter,
        state_store=store,
        risk_chain=RiskGateChain({}),
    )
    base_kwargs = {
        "account_label": "main",
        "dry_run": False,
        "target_source": "unit",
        "target_asof": "2026-04-14",
        "target_input_path": "tests/targets.json",
    }

    first = service.execute_orders(
        [Order(symbol="AAPL.US", quantity=10, side="BUY", price=10.0)],
        **base_kwargs,
    )
    second = service.execute_orders(
        [Order(symbol="AAPL.US", quantity=10, side="BUY", price=10.0)],
        **base_kwargs,
    )

    assert first[0].broker_order_id == second[0].broker_order_id
    assert adapter.submit_calls == 1


def test_broker_capabilities_include_alpaca_paper() -> None:
    caps = get_broker_capabilities("alpaca-paper")

    assert caps.name == "alpaca-paper"
    assert caps.supports_live_submit is True
