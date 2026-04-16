from __future__ import annotations

from pathlib import Path

import pytest

from quant_execution_engine.broker.base import (
    BrokerAdapter,
    BrokerCapabilityMatrix,
    BrokerFillRecord,
    BrokerValidationError,
    BrokerOrderRecord,
    BrokerOrderRequest,
    BrokerReconcileReport,
    ResolvedBrokerAccount,
)
import quant_execution_engine.broker.factory as broker_factory
from quant_execution_engine.broker.factory import get_broker_capabilities
from quant_execution_engine.execution import (
    ExecutionFillEvent,
    ExecutionState,
    ExecutionStateStore,
    OrderLifecycleService,
)
from quant_execution_engine.models import Order, Quote
from quant_execution_engine.renderers.table import render_tracked_order_detail
from quant_execution_engine.risk import RiskGateChain
from quant_execution_engine.state_tools import StateMaintenanceService


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
        self.cancel_calls: list[str] = []
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
        self.cancel_calls.append(broker_order_id)
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


class FailingSubmitAdapter(FakeAdapter):
    def submit_order(self, request: BrokerOrderRequest) -> BrokerOrderRecord:
        raise RuntimeError("submit rejected by broker")


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
    store = ExecutionStateStore(root_dir=tmp_path)
    service = OrderLifecycleService(
        adapter,
        state_store=store,
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
    state = store.load("fake", "main")
    assert state.child_orders[0].status == "BLOCKED"
    assert state.child_orders[0].message is not None
    assert state.parent_orders[0].status == "BLOCKED"


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


def test_market_order_intent_ignores_preview_price_for_idempotency(tmp_path: Path) -> None:
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
        [Order(symbol="AAPL.US", quantity=10, side="BUY", price=10.0, order_type="MARKET")],
        **base_kwargs,
    )
    second = service.execute_orders(
        [Order(symbol="AAPL.US", quantity=10, side="BUY", price=10.5, order_type="MARKET")],
        **base_kwargs,
    )
    state = store.load("fake", "main")

    assert first[0].broker_order_id == second[0].broker_order_id
    assert adapter.submit_calls == 1
    assert state.intents[0].limit_price is None


def test_broker_capabilities_include_alpaca_paper() -> None:
    caps = get_broker_capabilities("alpaca-paper")

    assert caps.name == "alpaca-paper"
    assert caps.supports_live_submit is True


def test_broker_capabilities_include_longport_paper() -> None:
    caps = get_broker_capabilities("longport-paper")

    assert caps.name == "longport-paper"
    assert caps.notes["submit_mode"] == "paper"
    assert caps.supports_cancel is True


def test_resolve_broker_name_requires_explicit_or_configured_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(broker_factory, "load_cfg", lambda: {})

    with pytest.raises(
        BrokerValidationError,
        match="broker backend is not configured",
    ):
        broker_factory.resolve_broker_name()


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
    assert tracked.intent.limit_price is None
    assert tracked.child.child_order_id == result.child_order_id
    assert tracked.broker_order.broker_order_id == result.broker_order_id


def test_cancel_all_open_orders_only_targets_tracked_open_orders(tmp_path: Path) -> None:
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
    )[0]
    second = service.execute_orders(
        [Order(symbol="MSFT.US", quantity=5, side="BUY", price=10.0)],
        **base_kwargs,
    )[0]
    third = service.execute_orders(
        [Order(symbol="TSLA.US", quantity=3, side="BUY", price=10.0)],
        **base_kwargs,
    )[0]
    service.cancel_order(account_label="main", order_ref=str(third.broker_order_id))

    outcome = service.cancel_all_open_orders(account_label="main")
    state = store.load("fake", "main")

    assert outcome.targeted_orders == 2
    assert {result.broker_order_id for result in outcome.results} == {
        str(first.broker_order_id),
        str(second.broker_order_id),
    }
    assert adapter.cancel_calls.count(str(first.broker_order_id)) == 1
    assert adapter.cancel_calls.count(str(second.broker_order_id)) == 1
    assert adapter.cancel_calls.count(str(third.broker_order_id)) == 1
    assert all(record.status == "CANCELED" for record in state.broker_orders)


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


def test_reprice_open_limit_order_creates_new_attempt(tmp_path: Path) -> None:
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

    original = service.execute_orders(
        [Order(symbol="AAPL.US", quantity=10, side="BUY", price=10.0, order_type="LIMIT")],
        **base_kwargs,
    )[0]

    outcome = service.reprice_order(
        account_label="main",
        order_ref=str(original.broker_order_id),
        limit_price=9.5,
    )
    state = store.load("fake", "main")

    assert outcome.cancel_status == "CANCELED"
    assert outcome.new_child_order_id is not None
    assert outcome.new_child_order_id.endswith("_2")
    assert outcome.broker_order_id is not None
    assert outcome.broker_status == "NEW"
    assert adapter.cancel_calls.count(str(original.broker_order_id)) == 1
    assert adapter.submit_calls == 2
    assert len(state.child_orders) == 2
    assert state.parent_orders[0].status == "PENDING"
    assert state.intents[0].limit_price == 9.5


def test_reprice_rejects_non_limit_order(tmp_path: Path) -> None:
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

    original = service.execute_orders(
        [Order(symbol="AAPL.US", quantity=10, side="BUY", price=10.0)],
        **base_kwargs,
    )[0]

    with pytest.raises(ValueError, match="LIMIT"):
        service.reprice_order(
            account_label="main",
            order_ref=str(original.broker_order_id),
            limit_price=9.5,
        )


def test_render_tracked_order_detail_includes_target_context_and_reprice_metadata(
    tmp_path: Path,
) -> None:
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
        "target_source": "smoke-signal",
        "target_asof": "2026-04-14",
        "target_input_path": "outputs/targets/smoke.json",
    }

    original = service.execute_orders(
        [Order(symbol="AAPL.US", quantity=10, side="BUY", price=10.0, order_type="LIMIT")],
        **base_kwargs,
    )[0]
    repriced = service.reprice_order(
        account_label="main",
        order_ref=str(original.broker_order_id),
        limit_price=9.5,
    )
    tracked = service.get_tracked_order(
        account_label="main",
        order_ref=str(repriced.broker_order_id),
    )

    rendered = render_tracked_order_detail(tracked)

    assert "Target Source: smoke-signal" in rendered
    assert "Target Asof: 2026-04-14" in rendered
    assert "Target Input: outputs/targets/smoke.json" in rendered
    assert "Intent Limit Price: 9.5" in rendered
    assert "Last Reprice At:" in rendered
    assert "Last Reprice From Limit: 10.0" in rendered


def test_retry_stale_orders_only_retries_eligible_open_orders(tmp_path: Path) -> None:
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

    stale = service.execute_orders(
        [Order(symbol="AAPL.US", quantity=10, side="BUY", price=10.0)],
        **base_kwargs,
    )[0]
    fresh = service.execute_orders(
        [Order(symbol="MSFT.US", quantity=5, side="BUY", price=10.0)],
        **base_kwargs,
    )[0]
    state = store.load("fake", "main")
    for broker_order in state.broker_orders:
        if broker_order.broker_order_id == stale.broker_order_id:
            broker_order.updated_at = "2000-01-01T00:00:00+00:00"
            broker_order.submitted_at = "2000-01-01T00:00:00+00:00"
    store.save(state)

    outcome = service.retry_stale_orders(account_label="main", older_than_minutes=5)
    refreshed_state = store.load("fake", "main")

    assert outcome.targeted_orders == 1
    assert len(outcome.cancel_results) == 1
    assert len(outcome.retry_results) == 1
    assert outcome.cancel_results[0].broker_order_id == stale.broker_order_id
    assert outcome.retry_results[0].new_child_order_id.endswith("_2")
    assert adapter.cancel_calls.count(str(stale.broker_order_id)) == 1
    assert adapter.cancel_calls.count(str(fresh.broker_order_id)) == 0
    assert adapter.submit_calls == 3
    assert len(refreshed_state.child_orders) == 3


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


def test_cancel_rest_on_partially_filled_open_order(tmp_path: Path) -> None:
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
    state.parent_orders[0].status = "PARTIALLY_FILLED"
    state.child_orders[0].status = "PARTIALLY_FILLED"
    state.broker_orders[0].filled_quantity = 1.0
    state.broker_orders[0].remaining_quantity = 9.0
    state.broker_orders[0].status = "PARTIALLY_FILLED"
    store.save(state)
    adapter.orders[str(result.broker_order_id)].filled_quantity = 1.0
    adapter.orders[str(result.broker_order_id)].remaining_quantity = 9.0
    adapter.orders[str(result.broker_order_id)].status = "PARTIALLY_FILLED"

    outcome = service.cancel_remaining_order(
        account_label="main",
        order_ref=str(result.broker_order_id),
    )
    refreshed = store.load("fake", "main")

    assert outcome.status == "CANCELED"
    assert refreshed.broker_orders[0].status == "CANCELED"
    assert refreshed.parent_orders[0].status == "PARTIALLY_FILLED"


def test_resume_remaining_order_creates_new_child_attempt(tmp_path: Path) -> None:
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
    state.parent_orders[0].status = "PARTIALLY_FILLED"
    state.child_orders[0].status = "CANCELED"
    state.broker_orders[0].filled_quantity = 1.0
    state.broker_orders[0].remaining_quantity = 9.0
    state.broker_orders[0].status = "CANCELED"
    store.save(state)
    adapter.orders[str(result.broker_order_id)].filled_quantity = 1.0
    adapter.orders[str(result.broker_order_id)].remaining_quantity = 9.0
    adapter.orders[str(result.broker_order_id)].status = "CANCELED"

    outcome = service.resume_remaining_order(
        account_label="main",
        order_ref=str(result.broker_order_id),
    )
    refreshed = store.load("fake", "main")

    assert outcome.submitted_quantity == 9.0
    assert outcome.new_child_order_id.endswith("_2")
    assert outcome.broker_status == "NEW"
    assert adapter.submit_calls == 2
    assert refreshed.child_orders[-1].quantity == 9.0


def test_resume_remaining_rejects_stale_child_reference_when_newer_attempt_exists(
    tmp_path: Path,
) -> None:
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
    state.parent_orders[0].status = "PARTIALLY_FILLED"
    state.child_orders[0].status = "CANCELED"
    state.broker_orders[0].filled_quantity = 1.0
    state.broker_orders[0].remaining_quantity = 9.0
    state.broker_orders[0].status = "CANCELED"
    store.save(state)
    adapter.orders[str(result.broker_order_id)].filled_quantity = 1.0
    adapter.orders[str(result.broker_order_id)].remaining_quantity = 9.0
    adapter.orders[str(result.broker_order_id)].status = "CANCELED"

    resumed = service.resume_remaining_order(
        account_label="main",
        order_ref=str(result.broker_order_id),
    )

    with pytest.raises(ValueError, match="latest tracked child attempt"):
        service.resume_remaining_order(
            account_label="main",
            order_ref=str(result.broker_order_id),
        )

    assert resumed.new_child_order_id.endswith("_2")


def test_accept_partial_fill_marks_parent_complete_locally(tmp_path: Path) -> None:
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
    state.parent_orders[0].status = "PARTIALLY_FILLED"
    state.child_orders[0].status = "CANCELED"
    state.broker_orders[0].filled_quantity = 1.0
    state.broker_orders[0].remaining_quantity = 9.0
    state.broker_orders[0].status = "CANCELED"
    store.save(state)
    adapter.orders[str(result.broker_order_id)].filled_quantity = 1.0
    adapter.orders[str(result.broker_order_id)].remaining_quantity = 9.0
    adapter.orders[str(result.broker_order_id)].status = "CANCELED"

    outcome = service.accept_partial_fill(
        account_label="main",
        order_ref=str(result.broker_order_id),
    )
    refreshed = store.load("fake", "main")

    assert outcome.accepted_filled_quantity == 1.0
    assert outcome.abandoned_remaining_quantity == 9.0
    assert refreshed.parent_orders[0].status == "ACCEPTED_PARTIAL"
    assert refreshed.parent_orders[0].metadata["manual_resolution"] == "accepted_partial"


def test_state_doctor_reports_duplicate_fill_and_orphan_broker_order(tmp_path: Path) -> None:
    store = ExecutionStateStore(root_dir=tmp_path)
    state = ExecutionState(broker_name="fake", account_label="main")
    state.broker_orders = [
        BrokerOrderRecord(
            broker_order_id="orphan-broker-order",
            symbol="AAPL.US",
            side="BUY",
            quantity=1,
            status="CANCELED",
            broker_name="fake",
            account_label="main",
        )
    ]
    state.fill_events = [
        ExecutionFillEvent(
            fill_id="fill-1",
            intent_id="intent-1",
            parent_order_id="parent-1",
            broker_order_id="missing-broker-order",
            symbol="AAPL.US",
            quantity=1,
            price=10.0,
            broker_name="fake",
            account_label="main",
        ),
        ExecutionFillEvent(
            fill_id="fill-1",
            intent_id="intent-1",
            parent_order_id="parent-1",
            broker_order_id="missing-broker-order",
            symbol="AAPL.US",
            quantity=1,
            price=10.0,
            broker_name="fake",
            account_label="main",
        ),
    ]
    store.save(state)

    result = StateMaintenanceService(state_store=store).doctor(
        broker_name="fake",
        account_label="main",
    )

    codes = {issue.code for issue in result.issues}
    assert "ORPHAN_TERMINAL_BROKER_ORDER" in codes
    assert "DUPLICATE_FILL_ID" in codes
    assert "ORPHAN_FILL_EVENT" in codes


def test_state_doctor_reports_parent_aggregate_mismatch(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    store = ExecutionStateStore(root_dir=tmp_path)
    service = OrderLifecycleService(
        adapter,
        state_store=store,
        risk_chain=RiskGateChain({}),
    )

    result = service.execute_orders(
        [Order(symbol="AAPL.US", quantity=10, side="BUY", price=10.0)],
        account_label="main",
        dry_run=False,
        target_source="unit",
        target_asof="2026-04-14",
        target_input_path="tests/targets.json",
    )[0]
    state = store.load("fake", "main")
    state.parent_orders[0].filled_quantity = 0.0
    state.parent_orders[0].remaining_quantity = 10.0
    state.parent_orders[0].status = "PENDING"
    state.broker_orders[0].filled_quantity = 4.0
    state.broker_orders[0].remaining_quantity = 6.0
    state.broker_orders[0].status = "PARTIALLY_FILLED"
    state.child_orders[0].status = "PARTIALLY_FILLED"
    store.save(state)
    adapter.orders[str(result.broker_order_id)].filled_quantity = 4.0
    adapter.orders[str(result.broker_order_id)].remaining_quantity = 6.0
    adapter.orders[str(result.broker_order_id)].status = "PARTIALLY_FILLED"

    diagnosis = StateMaintenanceService(state_store=store).doctor(
        broker_name="fake",
        account_label="main",
    )

    codes = {issue.code for issue in diagnosis.issues}
    assert "PARENT_AGGREGATE_MISMATCH" in codes
    assert "PARENT_STATUS_MISMATCH" in codes


def test_state_prune_previews_and_applies_old_terminal_records(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    store = ExecutionStateStore(root_dir=tmp_path)
    service = OrderLifecycleService(
        adapter,
        state_store=store,
        risk_chain=RiskGateChain({}),
    )
    result = service.execute_orders(
        [Order(symbol="AAPL.US", quantity=10, side="BUY", price=10.0)],
        account_label="main",
        dry_run=False,
        target_source="unit",
        target_asof="2026-04-14",
        target_input_path="tests/targets.json",
    )[0]
    service.cancel_order(account_label="main", order_ref=str(result.broker_order_id))
    state = store.load("fake", "main")
    state.parent_orders[0].updated_at = "2000-01-01T00:00:00+00:00"
    store.save(state)

    preview = StateMaintenanceService(state_store=store).prune(
        broker_name="fake",
        account_label="main",
        older_than_days=30,
        apply=False,
    )
    applied = StateMaintenanceService(state_store=store).prune(
        broker_name="fake",
        account_label="main",
        older_than_days=30,
        apply=True,
    )
    refreshed = store.load("fake", "main")

    assert preview.parent_orders_removed == 1
    assert applied.parent_orders_removed == 1
    assert refreshed.parent_orders == []
    assert refreshed.child_orders == []


def test_state_repair_clears_kill_switch_and_dedupes_fills(tmp_path: Path) -> None:
    store = ExecutionStateStore(root_dir=tmp_path)
    state = ExecutionState(broker_name="fake", account_label="main")
    state.kill_switch_active = True
    state.kill_switch_reason = "manual test"
    state.consecutive_failures = 2
    state.broker_orders = [
        BrokerOrderRecord(
            broker_order_id="orphan-broker-order",
            symbol="AAPL.US",
            side="BUY",
            quantity=1,
            status="CANCELED",
            broker_name="fake",
            account_label="main",
        )
    ]
    state.fill_events = [
        ExecutionFillEvent(
            fill_id="fill-1",
            intent_id="intent-1",
            parent_order_id="parent-1",
            broker_order_id="missing-broker-order",
            symbol="AAPL.US",
            quantity=1,
            price=10.0,
            broker_name="fake",
            account_label="main",
        ),
        ExecutionFillEvent(
            fill_id="fill-1",
            intent_id="intent-1",
            parent_order_id="parent-1",
            broker_order_id="missing-broker-order",
            symbol="AAPL.US",
            quantity=1,
            price=10.0,
            broker_name="fake",
            account_label="main",
        ),
    ]
    store.save(state)

    result = StateMaintenanceService(state_store=store).repair(
        broker_name="fake",
        account_label="main",
        clear_kill_switch=True,
        dedupe_fills=True,
        drop_orphan_fills=True,
        drop_orphan_terminal_broker_orders=True,
        recompute_parent_aggregates=False,
    )
    refreshed = store.load("fake", "main")

    assert result.cleared_kill_switch is True
    assert result.duplicate_fills_removed == 1
    assert result.orphan_fills_removed == 1
    assert result.orphan_terminal_broker_orders_removed == 1
    assert refreshed.kill_switch_active is False
    assert refreshed.fill_events == []
    assert refreshed.broker_orders == []


def test_state_repair_recomputes_parent_aggregates(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    store = ExecutionStateStore(root_dir=tmp_path)
    service = OrderLifecycleService(
        adapter,
        state_store=store,
        risk_chain=RiskGateChain({}),
    )

    result = service.execute_orders(
        [Order(symbol="AAPL.US", quantity=10, side="BUY", price=10.0)],
        account_label="main",
        dry_run=False,
        target_source="unit",
        target_asof="2026-04-14",
        target_input_path="tests/targets.json",
    )[0]
    state = store.load("fake", "main")
    state.parent_orders[0].filled_quantity = 0.0
    state.parent_orders[0].remaining_quantity = 10.0
    state.parent_orders[0].status = "PENDING"
    state.broker_orders[0].filled_quantity = 4.0
    state.broker_orders[0].remaining_quantity = 6.0
    state.broker_orders[0].status = "PARTIALLY_FILLED"
    state.child_orders[0].status = "PARTIALLY_FILLED"
    store.save(state)
    adapter.orders[str(result.broker_order_id)].filled_quantity = 4.0
    adapter.orders[str(result.broker_order_id)].remaining_quantity = 6.0
    adapter.orders[str(result.broker_order_id)].status = "PARTIALLY_FILLED"

    repaired = StateMaintenanceService(state_store=store).repair(
        broker_name="fake",
        account_label="main",
        clear_kill_switch=False,
        dedupe_fills=False,
        drop_orphan_fills=False,
        drop_orphan_terminal_broker_orders=False,
        recompute_parent_aggregates=True,
    )
    refreshed = store.load("fake", "main")

    assert repaired.parent_aggregates_recomputed == 1
    assert refreshed.parent_orders[0].filled_quantity == 4.0
    assert refreshed.parent_orders[0].remaining_quantity == 6.0
    assert refreshed.parent_orders[0].status == "PARTIALLY_FILLED"


def test_list_exception_orders_includes_local_blocked_and_failed(tmp_path: Path) -> None:
    store = ExecutionStateStore(root_dir=tmp_path)
    blocked_service = OrderLifecycleService(
        FakeAdapter(),
        state_store=store,
        risk_chain=RiskGateChain({"max_qty_per_order": 5}),
    )
    failed_service = OrderLifecycleService(
        FailingSubmitAdapter(),
        state_store=store,
        risk_chain=RiskGateChain({}),
    )

    blocked_service.execute_orders(
        [Order(symbol="AAPL.US", quantity=10, side="BUY", price=10.0)],
        account_label="main",
        dry_run=False,
        target_source="unit",
        target_asof="2026-04-14",
        target_input_path="tests/targets.json",
    )
    failed_service.execute_orders(
        [Order(symbol="MSFT.US", quantity=5, side="BUY", price=10.0)],
        account_label="main",
        dry_run=False,
        target_source="unit-submit-failure",
        target_asof="2026-04-14",
        target_input_path="tests/targets-submit-failure.json",
    )

    records = failed_service.list_exception_orders(account_label="main")

    assert {record.status for record in records} >= {"BLOCKED", "FAILED"}
    blocked = next(record for record in records if record.status == "BLOCKED")
    failed = next(record for record in records if record.status == "FAILED")
    assert blocked.source == "local"
    assert blocked.message is not None
    assert failed.source == "local"
    assert failed.message == "submit rejected by broker"


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


class RefreshLookupErrorAdapter(FakeAdapter):
    def list_open_orders(
        self,
        account: ResolvedBrokerAccount | None = None,
    ) -> list[BrokerOrderRecord]:
        return []

    def get_order(
        self,
        broker_order_id: str,
        account: ResolvedBrokerAccount | None = None,
    ) -> BrokerOrderRecord:
        raise RuntimeError("order refresh unavailable")


class PendingCancelRefreshAdapter(FakeAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.pending_cancel_ids: set[str] = set()

    def cancel_order(
        self,
        broker_order_id: str,
        account: ResolvedBrokerAccount | None = None,
    ) -> None:
        self.cancel_calls.append(broker_order_id)
        self.pending_cancel_ids.add(broker_order_id)

    def get_order(
        self,
        broker_order_id: str,
        account: ResolvedBrokerAccount | None = None,
    ) -> BrokerOrderRecord:
        if broker_order_id in self.pending_cancel_ids:
            raise RuntimeError("cancel refresh unavailable")
        return super().get_order(broker_order_id, account)


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
    assert outcome.changed_orders[0].after_status == "FILLED"
    assert outcome.changed_orders[0].new_fill_events == 1
    assert state.fill_events[0].broker_order_id.startswith("fake-child_")
    assert state.parent_orders[0].status == "FILLED"
    assert state.parent_orders[0].remaining_quantity == 0.0
    assert any(order.status == "FILLED" for order in state.broker_orders)


def test_manual_reconcile_warns_and_preserves_state_when_tracked_order_refresh_fails(
    tmp_path: Path,
) -> None:
    adapter = RefreshLookupErrorAdapter()
    store = ExecutionStateStore(root_dir=tmp_path)
    service = OrderLifecycleService(
        adapter,
        state_store=store,
        risk_chain=RiskGateChain({}),
    )

    result = service.execute_orders(
        [Order(symbol="AAPL.US", quantity=10, side="BUY", price=10.0)],
        account_label="main",
        dry_run=False,
        target_source="unit",
        target_asof="2026-04-14",
        target_input_path="tests/targets.json",
    )[0]

    outcome = service.reconcile(account_label="main")
    state = store.load("fake", "main")

    assert outcome.refreshed_orders == 0
    assert outcome.new_fill_events == 0
    assert outcome.report.warnings == [
        f"failed to refresh tracked order {result.broker_order_id}: order refresh unavailable"
    ]
    assert state.broker_orders[0].broker_order_id == result.broker_order_id
    assert state.child_orders[0].broker_order_id == result.broker_order_id


def test_manual_reconcile_warns_and_preserves_state_when_fill_lookup_fails(
    tmp_path: Path,
) -> None:
    adapter = FillLookupErrorAdapter()
    store = ExecutionStateStore(root_dir=tmp_path)
    service = OrderLifecycleService(
        adapter,
        state_store=store,
        risk_chain=RiskGateChain({}),
    )

    result = service.execute_orders(
        [Order(symbol="AAPL.US", quantity=10, side="BUY", price=10.0)],
        account_label="main",
        dry_run=False,
        target_source="unit",
        target_asof="2026-04-14",
        target_input_path="tests/targets.json",
    )[0]

    outcome = service.reconcile(account_label="main")
    state = store.load("fake", "main")

    assert outcome.refreshed_orders == 0
    assert outcome.new_fill_events == 0
    assert outcome.report.warnings == [
        f"failed to load fills for tracked order {result.broker_order_id}: fill lookup unavailable"
    ]
    assert state.broker_orders[0].broker_order_id == result.broker_order_id
    assert state.fill_events == []


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


def test_cancel_order_records_pending_cancel_when_refresh_fails(tmp_path: Path) -> None:
    adapter = PendingCancelRefreshAdapter()
    store = ExecutionStateStore(root_dir=tmp_path)
    service = OrderLifecycleService(
        adapter,
        state_store=store,
        risk_chain=RiskGateChain({}),
    )

    result = service.execute_orders(
        [Order(symbol="AAPL.US", quantity=10, side="BUY", price=10.0, order_type="LIMIT")],
        account_label="main",
        dry_run=False,
        target_source="unit",
        target_asof="2026-04-14",
        target_input_path="tests/targets.json",
    )[0]

    outcome = service.cancel_order(
        account_label="main",
        order_ref=str(result.broker_order_id),
    )
    state = store.load("fake", "main")

    assert outcome.status == "PENDING_CANCEL"
    assert outcome.warnings == [
        "cancel submitted but post-cancel refresh failed: cancel refresh unavailable"
    ]
    assert state.broker_orders[0].status == "PENDING_CANCEL"
    assert state.child_orders[0].status == "PENDING_CANCEL"


def test_reprice_rejects_pending_cancel_order(tmp_path: Path) -> None:
    adapter = PendingCancelRefreshAdapter()
    store = ExecutionStateStore(root_dir=tmp_path)
    service = OrderLifecycleService(
        adapter,
        state_store=store,
        risk_chain=RiskGateChain({}),
    )

    result = service.execute_orders(
        [Order(symbol="AAPL.US", quantity=10, side="BUY", price=10.0, order_type="LIMIT")],
        account_label="main",
        dry_run=False,
        target_source="unit",
        target_asof="2026-04-14",
        target_input_path="tests/targets.json",
    )[0]
    service.cancel_order(
        account_label="main",
        order_ref=str(result.broker_order_id),
    )

    with pytest.raises(ValueError, match="pending cancel"):
        service.reprice_order(
            account_label="main",
            order_ref=str(result.broker_order_id),
            limit_price=9.5,
        )
