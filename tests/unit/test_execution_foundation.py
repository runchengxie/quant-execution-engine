from __future__ import annotations

from pathlib import Path

import pytest

from quant_execution_engine.broker.base import (
    BrokerAdapter,
    BrokerCapabilityMatrix,
    BrokerFillRecord,
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


def test_cancel_tracked_order_updates_state(tmp_path: Path) -> None:
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

    result = service.execute_orders(
        [Order(symbol="AAPL.US", quantity=10, side="BUY", price=10.0)],
        **base_kwargs,
    )[0]

    outcome = service.cancel_order(
        account_label="main",
        order_ref=str(result.broker_order_id),
    )
    state = store.load("fake", "main")

    assert outcome.status == "CANCELED"
    assert state.broker_orders[0].status == "CANCELED"
    assert state.child_orders[0].status == "CANCELED"
    assert state.parent_orders[0].status == "CANCELED"


def test_cancel_accepts_child_order_id_reference(tmp_path: Path) -> None:
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

    result = service.execute_orders(
        [Order(symbol="AAPL.US", quantity=10, side="BUY", price=10.0)],
        **base_kwargs,
    )[0]

    outcome = service.cancel_order(
        account_label="main",
        order_ref=str(result.child_order_id),
    )

    assert outcome.broker_order_id == result.broker_order_id
    assert outcome.status == "CANCELED"


def test_get_tracked_order_returns_lifecycle_details(tmp_path: Path) -> None:
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

    result = service.execute_orders(
        [Order(symbol="AAPL.US", quantity=10, side="BUY", price=10.0)],
        **base_kwargs,
    )[0]

    tracked = service.get_tracked_order(
        account_label="main",
        order_ref=str(result.broker_order_id),
    )

    assert tracked.intent is not None
    assert tracked.parent is not None
    assert tracked.child is not None
    assert tracked.broker_order is not None
    assert tracked.child.child_order_id == result.child_order_id
    assert tracked.broker_order.broker_order_id == result.broker_order_id


def test_retry_canceled_zero_fill_order_creates_new_attempt(tmp_path: Path) -> None:
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

    result = service.execute_orders(
        [Order(symbol="AAPL.US", quantity=10, side="BUY", price=10.0)],
        **base_kwargs,
    )[0]
    service.cancel_order(account_label="main", order_ref=str(result.broker_order_id))

    outcome = service.retry_order(
        account_label="main",
        order_ref=str(result.broker_order_id),
    )
    state = store.load("fake", "main")

    assert outcome.new_child_order_id.endswith("_2")
    assert outcome.broker_order_id is not None
    assert outcome.broker_status == "NEW"
    assert len(state.child_orders) == 2
    assert state.child_orders[-1].attempt == 2
    assert state.parent_orders[0].status == "PENDING"
    assert adapter.submit_calls == 2


def test_retry_rejects_partially_filled_order(tmp_path: Path) -> None:
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

    result = service.execute_orders(
        [Order(symbol="AAPL.US", quantity=10, side="BUY", price=10.0)],
        **base_kwargs,
    )[0]
    state = store.load("fake", "main")
    state.parent_orders[0].filled_quantity = 1.0
    state.parent_orders[0].remaining_quantity = 9.0
    state.parent_orders[0].status = "CANCELED"
    state.child_orders[0].status = "CANCELED"
    state.broker_orders[0].filled_quantity = 1.0
    state.broker_orders[0].remaining_quantity = 9.0
    state.broker_orders[0].status = "CANCELED"
    store.save(state)

    with pytest.raises(ValueError, match="partially filled"):
        service.retry_order(
            account_label="main",
            order_ref=str(result.broker_order_id),
        )


class ClosedFillAdapter(FakeAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.fill_available = False

    def submit_order(self, request: BrokerOrderRequest) -> BrokerOrderRecord:
        record = super().submit_order(request)
        record.status = "NEW"
        self.orders[record.broker_order_id] = record
        return record

    def get_order(
        self,
        broker_order_id: str,
        account: ResolvedBrokerAccount | None = None,
    ) -> BrokerOrderRecord:
        record = self.orders[broker_order_id]
        self.fill_available = True
        return BrokerOrderRecord(
            broker_order_id=record.broker_order_id,
            symbol=record.symbol,
            side=record.side,
            quantity=record.quantity,
            filled_quantity=record.quantity,
            remaining_quantity=0.0,
            status="FILLED",
            broker_name=record.broker_name,
            account_label=record.account_label,
            client_order_id=record.client_order_id,
            avg_fill_price=10.25,
        )

    def list_open_orders(
        self,
        account: ResolvedBrokerAccount | None = None,
    ) -> list[BrokerOrderRecord]:
        return []

    def list_fills(
        self,
        account: ResolvedBrokerAccount | None = None,
        *,
        broker_order_id: str | None = None,
    ) -> list[BrokerFillRecord]:
        assert broker_order_id is not None
        if not self.fill_available:
            return []
        record = self.orders[broker_order_id]
        return [
            BrokerFillRecord(
                fill_id=f"{broker_order_id}-fill",
                broker_order_id=broker_order_id,
                symbol=record.symbol,
                quantity=record.quantity,
                price=10.25,
                broker_name=self.backend_name,
                account_label=record.account_label,
                filled_at="2026-04-14T00:05:00Z",
            )
        ]

    def reconcile(
        self,
        account: ResolvedBrokerAccount | None = None,
    ) -> BrokerReconcileReport:
        resolved = account or self.resolve_account()
        return BrokerReconcileReport(
            broker_name=self.backend_name,
            account_label=resolved.label,
            open_orders=[],
            fills=[],
        )


class FillLookupErrorAdapter(FakeAdapter):
    def list_fills(
        self,
        account: ResolvedBrokerAccount | None = None,
        *,
        broker_order_id: str | None = None,
    ) -> list[BrokerFillRecord]:
        raise RuntimeError("fill lookup unavailable")


def test_manual_reconcile_recovers_fill_for_closed_tracked_order(tmp_path: Path) -> None:
    adapter = ClosedFillAdapter()
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

    service.execute_orders(
        [Order(symbol="AAPL.US", quantity=10, side="BUY", price=10.0)],
        **base_kwargs,
    )

    outcome = service.reconcile(account_label="main")
    state = store.load("fake", "main")

    assert outcome.new_fill_events == 1
    assert outcome.refreshed_orders == 1
    assert state.fill_events[0].broker_order_id.startswith("fake-child_")
    assert state.parent_orders[0].status == "FILLED"
    assert state.parent_orders[0].remaining_quantity == 0.0
    assert any(order.status == "FILLED" for order in state.broker_orders)


def test_submit_success_survives_fill_lookup_failure(tmp_path: Path) -> None:
    adapter = FillLookupErrorAdapter()
    service = OrderLifecycleService(
        adapter,
        state_store=ExecutionStateStore(root_dir=tmp_path),
        risk_chain=RiskGateChain({}),
    )

    results = service.execute_orders(
        [Order(symbol="AAPL.US", quantity=10, side="BUY", price=10.0)],
        account_label="main",
        dry_run=False,
        target_source="unit",
        target_asof="2026-04-14",
        target_input_path="tests/targets.json",
    )

    assert results[0].status == "SUCCESS"
    assert results[0].broker_order_id is not None
