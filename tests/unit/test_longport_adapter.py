from __future__ import annotations

from types import SimpleNamespace

import pytest

from quant_execution_engine.broker.longport_adapter import LongPortPaperBrokerAdapter


pytestmark = pytest.mark.unit


def test_longport_adapter_list_order_history_uses_history_api() -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def list_orders(self, **kwargs):
            self.calls.append(("list_orders", kwargs))
            return [
                SimpleNamespace(
                    order_id="broker-1",
                    symbol="AAPL.US",
                    side=SimpleNamespace(value="Buy"),
                    quantity="10",
                    executed_quantity="4",
                    status=SimpleNamespace(value="Filled"),
                    remark="child-1",
                    executed_price="187.5",
                    submitted_at="2026-04-19T00:00:00Z",
                    updated_at="2026-04-19T00:01:00Z",
                    msg="done",
                    order_type=SimpleNamespace(value="LO"),
                    time_in_force=SimpleNamespace(value="Day"),
                )
            ]

        def close(self) -> None:
            return None

    client = FakeClient()
    adapter = LongPortPaperBrokerAdapter(client=client)

    records = adapter.list_order_history(symbol="AAPL", broker_order_id="broker-1")

    assert client.calls == [
        (
            "list_orders",
            {
                "symbol": "AAPL",
                "order_id": "broker-1",
                "include_history": True,
            },
        )
    ]
    assert len(records) == 1
    assert records[0].broker_order_id == "broker-1"
    assert records[0].symbol == "AAPL.US"
    assert records[0].filled_quantity == 4.0
    assert records[0].status == "FILLED"
    assert records[0].raw["order_type"] == "LO"


def test_longport_adapter_list_fill_history_uses_history_api() -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def list_executions(self, **kwargs):
            self.calls.append(("list_executions", kwargs))
            return [
                SimpleNamespace(
                    trade_id="fill-1",
                    order_id="broker-1",
                    symbol="AAPL.US",
                    quantity="4",
                    price="187.5",
                    trade_done_at="2026-04-19T00:01:30Z",
                )
            ]

        def close(self) -> None:
            return None

    client = FakeClient()
    adapter = LongPortPaperBrokerAdapter(client=client)

    fills = adapter.list_fill_history(symbol="AAPL", broker_order_id="broker-1")

    assert client.calls == [
        (
            "list_executions",
            {
                "symbol": "AAPL",
                "order_id": "broker-1",
                "include_history": True,
            },
        )
    ]
    assert len(fills) == 1
    assert fills[0].fill_id == "fill-1"
    assert fills[0].broker_order_id == "broker-1"
    assert fills[0].symbol == "AAPL.US"
    assert fills[0].quantity == 4.0
    assert fills[0].price == 187.5
