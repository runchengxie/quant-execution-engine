from __future__ import annotations

from pathlib import Path

import pytest

from quant_execution_engine.broker.base import BrokerOrderRequest
from quant_execution_engine.broker.factory import (
    get_broker_adapter,
    get_broker_capabilities,
    is_paper_broker,
)
from quant_execution_engine.broker.mock_sim import (
    DEFAULT_CLOCK,
    MockSimBrokerAdapter,
)

pytestmark = pytest.mark.unit


@pytest.fixture()
def sim_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QEXEC_MOCK_SIM_STATE_DIR", str(tmp_path / "mock-sim"))
    monkeypatch.setenv("QEXEC_MOCK_SIM_CLOCK", DEFAULT_CLOCK)
    monkeypatch.setenv("QEXEC_MOCK_SIM_PRICE", "100.0")


def test_mock_sim_is_registered_paper_backend() -> None:
    capabilities = get_broker_capabilities("mock-sim")
    assert capabilities.supports_live_submit is False
    assert capabilities.supports_cancel is True
    assert capabilities.supports_order_query is True
    assert capabilities.supports_open_order_listing is True
    assert capabilities.supports_reconcile is True
    assert is_paper_broker("mock-sim") is True
    adapter = get_broker_adapter(broker_name="mock-sim")
    assert isinstance(adapter, MockSimBrokerAdapter)


def test_mock_sim_cn_lot_size_and_persisted_state(sim_env, tmp_path: Path) -> None:
    adapter = MockSimBrokerAdapter()
    account = adapter.resolve_account("main")
    assert adapter.lot_size("600519.SH.CN") == 100
    assert adapter.lot_size("AAPL.US") == 1

    record = adapter.submit_order(
        BrokerOrderRequest(
            symbol="AAPL.US",
            quantity=10,
            side="BUY",
            account=account,
        )
    )
    assert record.status == "FILLED"
    assert record.avg_fill_price == 100.0

    snapshot = adapter.get_account_snapshot(account)
    assert {position.symbol: position.quantity for position in snapshot.positions} == {
        "AAPL.US": 10
    }

    resumed = MockSimBrokerAdapter()
    resumed_snapshot = resumed.get_account_snapshot(resumed.resolve_account("main"))
    assert {position.symbol: position.quantity for position in resumed_snapshot.positions} == {
        "AAPL.US": 10
    }


def test_mock_sim_reconcile_reports_fills(sim_env) -> None:
    adapter = MockSimBrokerAdapter()
    account = adapter.resolve_account("main")
    record = adapter.submit_order(
        BrokerOrderRequest(symbol="AAPL.US", quantity=5, side="BUY", account=account)
    )
    report = adapter.reconcile(account)
    assert report.open_orders == []
    fills = adapter.list_fills(account, broker_order_id=record.broker_order_id)
    assert len(fills) == 1
    assert fills[0].fill_id == f"{record.broker_order_id}-fill"
    assert fills[0].quantity == 5.0


def test_mock_sim_cancel_marks_order_canceled(sim_env) -> None:
    adapter = MockSimBrokerAdapter()
    account = adapter.resolve_account("main")
    record = adapter.submit_order(
        BrokerOrderRequest(
            symbol="AAPL.US",
            quantity=1,
            side="BUY",
            order_type="LIMIT",
            limit_price=50.0,
            account=account,
        )
    )
    assert record.status == "NEW"
    adapter.cancel_order(record.broker_order_id, account)
    assert adapter.get_order(record.broker_order_id, account).status == "CANCELED"


def test_mock_sim_rejects_insufficient_cash(sim_env) -> None:
    adapter = MockSimBrokerAdapter()
    account = adapter.resolve_account("main")
    with pytest.raises(Exception, match="insufficient cash"):
        adapter.submit_order(
            BrokerOrderRequest(
                symbol="AAPL.US",
                quantity=999_999_999,
                side="BUY",
                account=account,
            )
        )


def test_mock_sim_rejects_oversell(sim_env) -> None:
    adapter = MockSimBrokerAdapter()
    account = adapter.resolve_account("main")
    with pytest.raises(Exception, match="mock-sim rejects SELL"):
        adapter.submit_order(
            BrokerOrderRequest(
                symbol="AAPL.US",
                quantity=1,
                side="SELL",
                account=account,
            )
        )
