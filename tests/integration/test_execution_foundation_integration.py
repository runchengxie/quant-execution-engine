from __future__ import annotations

import pytest

from quant_execution_engine.broker.base import (
    BrokerAdapter,
    BrokerCapabilityMatrix,
    BrokerOrderRecord,
    BrokerOrderRequest,
    BrokerReconcileReport,
    ResolvedBrokerAccount,
)
from quant_execution_engine.execution import ExecutionStateStore, OrderLifecycleService
from quant_execution_engine.models import Order, Quote
from quant_execution_engine.risk import RiskGateChain


pytestmark = pytest.mark.integration


class IntegrationFakeAdapter(BrokerAdapter):
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
        return ResolvedBrokerAccount(label=account_label or "main")

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

    def get_order(
        self,
        broker_order_id: str,
        account: ResolvedBrokerAccount | None = None,
    ) -> BrokerOrderRecord:
        return self.orders[broker_order_id]

    def list_open_orders(
        self,
        account: ResolvedBrokerAccount | None = None,
    ) -> list[BrokerOrderRecord]:
        return [
            record
            for record in self.orders.values()
            if record.status not in {"CANCELED", "FILLED"}
        ]

    def cancel_order(
        self,
        broker_order_id: str,
        account: ResolvedBrokerAccount | None = None,
    ) -> None:
        self.orders[broker_order_id].status = "CANCELED"

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


def test_restart_recovery_reuses_open_order(tmp_path) -> None:
    adapter = IntegrationFakeAdapter()
    store = ExecutionStateStore(root_dir=tmp_path)
    kwargs = {
        "account_label": "main",
        "dry_run": False,
        "target_source": "integration",
        "target_asof": "2026-04-14",
        "target_input_path": "tests/targets.json",
    }
    service_a = OrderLifecycleService(
        adapter,
        state_store=store,
        risk_chain=RiskGateChain({}),
    )
    service_a.execute_orders([Order(symbol="AAPL.US", quantity=10, side="BUY", price=10.0)], **kwargs)

    service_b = OrderLifecycleService(
        adapter,
        state_store=store,
        risk_chain=RiskGateChain({}),
    )
    results = service_b.execute_orders(
        [Order(symbol="AAPL.US", quantity=10, side="BUY", price=10.0)],
        **kwargs,
    )

    assert adapter.submit_calls == 1
    assert results[0].status == "SUCCESS"
    assert service_b.last_reconcile_report is not None


def test_manual_kill_switch_blocks_submission(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = IntegrationFakeAdapter()
    service = OrderLifecycleService(
        adapter,
        state_store=ExecutionStateStore(root_dir=tmp_path),
        risk_chain=RiskGateChain({}),
    )
    monkeypatch.setenv("QEXEC_KILL_SWITCH", "1")

    results = service.execute_orders(
        [Order(symbol="AAPL.US", quantity=10, side="BUY", price=10.0)],
        account_label="main",
        dry_run=False,
        target_source="integration",
        target_asof="2026-04-14",
        target_input_path="tests/targets.json",
    )

    assert results[0].status == "BLOCKED"
    assert adapter.submit_calls == 0


def test_cancel_round_trip_on_supported_adapter() -> None:
    adapter = IntegrationFakeAdapter()
    request = BrokerOrderRequest(
        symbol="AAPL.US",
        quantity=10,
        side="BUY",
        account=ResolvedBrokerAccount(label="main"),
        client_order_id="cancel-check",
    )
    record = adapter.submit_order(request)
    assert adapter.list_open_orders()

    adapter.cancel_order(record.broker_order_id)

    assert adapter.get_order(record.broker_order_id).status == "CANCELED"
    assert adapter.list_open_orders() == []
