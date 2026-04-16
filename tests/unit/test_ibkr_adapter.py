from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import quant_execution_engine.cli as cli
import quant_execution_engine.broker.factory as factory
import quant_execution_engine.broker.ibkr_runtime as ibkr_runtime_mod
from quant_execution_engine.broker.base import (
    BrokerImportError,
    BrokerOrderRequest,
    BrokerValidationError,
)
from quant_execution_engine.broker.ibkr import IbkrPaperBrokerAdapter
from quant_execution_engine.broker.ibkr_runtime import (
    IbkrRuntimeConfig,
    resolve_ibkr_runtime_config,
)


pytestmark = pytest.mark.unit


def _load_smoke_operator_module():
    script_path = (
        Path(__file__).resolve().parents[2]
        / "project_tools"
        / "smoke_operator_harness.py"
    )
    spec = importlib.util.spec_from_file_location("smoke_operator_harness", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _trade(
    *,
    status: str = "Submitted",
    order_id: int = 42,
    side: str = "BUY",
    total_quantity: int = 1,
    filled: float = 0.0,
    remaining: float = 1.0,
    avg_fill_price: float = 0.0,
    canonical: str = "AAPL.US",
    order_ref: str = "child-1",
) -> SimpleNamespace:
    now = datetime(2026, 4, 16, 0, 0, tzinfo=timezone.utc)
    return SimpleNamespace(
        order=SimpleNamespace(
            orderId=order_id,
            action=side,
            totalQuantity=total_quantity,
            tif="DAY",
            outsideRth=False,
            orderRef=order_ref,
        ),
        orderStatus=SimpleNamespace(
            status=status,
            filled=filled,
            remaining=remaining,
            avgFillPrice=avg_fill_price,
            warningText="",
        ),
        contract=SimpleNamespace(canonical=canonical, symbol=canonical.split(".", 1)[0]),
        fills=[],
        log=[SimpleNamespace(time=now)],
        advancedError="",
    )


class FakeIbkrRuntime:
    def __init__(self) -> None:
        self.submitted: list[tuple[str, str | None]] = []
        self.cancelled: list[str] = []
        self.closed = False

    def resolve_account_id(self) -> str:
        return "DU123456"

    def normalize_symbol(self, symbol: str) -> str:
        cleaned = str(symbol).strip().upper()
        if "." not in cleaned:
            return f"{cleaned}.US"
        if not cleaned.endswith(".US"):
            raise BrokerValidationError(
                f"ibkr-paper only supports US equities in the initial slice: {cleaned}"
            )
        return cleaned

    def canonical_symbol_for_contract(self, contract) -> str | None:
        return getattr(contract, "canonical", None)

    def get_account_values(self, account_id: str | None = None):
        assert account_id == "DU123456"
        return [
            SimpleNamespace(tag="AccountType", value="INDIVIDUAL", currency=""),
            SimpleNamespace(tag="TotalCashValue", value="1000", currency="USD"),
            SimpleNamespace(tag="NetLiquidation", value="1250", currency="USD"),
        ]

    def get_positions(self, account_id: str | None = None):
        assert account_id == "DU123456"
        return [
            SimpleNamespace(
                account="DU123456",
                contract=SimpleNamespace(canonical="AAPL.US"),
                position=2,
                avgCost=150.0,
            ),
            SimpleNamespace(
                account="DU123456",
                contract=SimpleNamespace(canonical=None),
                position=1,
                avgCost=10.0,
            ),
        ]

    def request_tickers(self, symbols: list[str]):
        if any(str(symbol).upper().endswith(".HK") for symbol in symbols):
            raise BrokerValidationError(
                "ibkr-paper only supports US equities in the initial slice: 700.HK"
            )
        return {
            "AAPL.US": SimpleNamespace(
                marketPrice=lambda: 185.25,
                bid=185.2,
                ask=185.3,
                volume=1000000,
                time=datetime(2026, 4, 16, 0, 0, tzinfo=timezone.utc),
            )
        }

    def qualify_stock(self, symbol: str):
        return self.normalize_symbol(symbol), SimpleNamespace(canonical="AAPL.US")

    def submit_order(self, contract, request, *, account_id: str | None = None):
        self.submitted.append((getattr(contract, "canonical", ""), account_id))
        return _trade(
            status="Submitted",
            order_id=77,
            side=request.side,
            total_quantity=int(request.quantity),
            filled=0.0,
            remaining=float(request.quantity),
            canonical=getattr(contract, "canonical", "AAPL.US"),
            order_ref=request.client_order_id or "child-1",
        )

    def get_trade(self, broker_order_id: str):
        if str(broker_order_id) == "missing":
            raise RuntimeError("IBKR order not found: missing")
        return _trade(
            status="Filled",
            order_id=int(broker_order_id),
            side="BUY",
            total_quantity=1,
            filled=1.0,
            remaining=0.0,
            avg_fill_price=185.4,
        )

    def list_open_trades(self, account_id: str | None = None):
        assert account_id == "DU123456"
        return [
            _trade(status="Submitted", order_id=11, remaining=1.0),
            _trade(status="Cancelled", order_id=12, remaining=0.0),
        ]

    def cancel_order(self, broker_order_id: str) -> None:
        self.cancelled.append(str(broker_order_id))

    def list_fills(
        self,
        *,
        account_id: str | None = None,
        broker_order_id: str | None = None,
    ):
        assert account_id == "DU123456"
        order_id = str(broker_order_id or "42")
        return [
            SimpleNamespace(
                contract=SimpleNamespace(canonical="AAPL.US"),
                execution=SimpleNamespace(
                    orderId=order_id,
                    execId=f"{order_id}-exec",
                    shares=1,
                    price=185.5,
                    exchange="NYSE",
                    side="BOT",
                ),
                time=datetime(2026, 4, 16, 0, 1, tzinfo=timezone.utc),
            )
        ]

    def close(self) -> None:
        self.closed = True


def test_ibkr_import_surfaces_missing_dependency_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_import_module(name: str):
        raise ModuleNotFoundError("No module named 'eventkit'", name="eventkit")

    monkeypatch.setattr(ibkr_runtime_mod.importlib, "import_module", fake_import_module)

    with pytest.raises(BrokerImportError, match="dependency 'eventkit' is missing"):
        ibkr_runtime_mod._ibkr_import("ib_insync.IB")


def test_resolve_ibkr_runtime_config_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IBKR_HOST", "10.0.0.2")
    monkeypatch.setenv("IBKR_PORT_PAPER", "4102")
    monkeypatch.setenv("IBKR_CLIENT_ID", "17")
    monkeypatch.setenv("IBKR_ACCOUNT_ID", "DU999")
    monkeypatch.setenv("IBKR_CONNECT_TIMEOUT_SECONDS", "8.5")

    config = resolve_ibkr_runtime_config()

    assert config.host == "10.0.0.2"
    assert config.port == 4102
    assert config.client_id == 17
    assert config.account_id == "DU999"
    assert config.connect_timeout_seconds == 8.5
    assert config.host_source == "env (IBKR_HOST)"
    assert config.port_source == "env (IBKR_PORT_PAPER)"


def test_factory_returns_ibkr_adapter_with_injected_runtime() -> None:
    runtime = FakeIbkrRuntime()

    adapter = factory.get_broker_adapter(broker_name="ibkr-paper", client=runtime)

    assert isinstance(adapter, IbkrPaperBrokerAdapter)
    assert adapter.client is runtime
    assert factory.is_paper_broker("ibkr-paper") is True
    assert factory.is_ibkr_broker("ibkr-paper") is True


def test_ibkr_resolve_account_rejects_non_main() -> None:
    adapter = IbkrPaperBrokerAdapter(client=FakeIbkrRuntime())

    with pytest.raises(BrokerValidationError, match="does not support switching broker accounts"):
        adapter.resolve_account("secondary")


def test_ibkr_get_quotes_normalizes_market_data() -> None:
    adapter = IbkrPaperBrokerAdapter(client=FakeIbkrRuntime())

    quotes = adapter.get_quotes(["AAPL"], include_depth=True)

    assert set(quotes) == {"AAPL.US"}
    assert quotes["AAPL.US"].price == 185.25
    assert quotes["AAPL.US"].bid == 185.2
    assert quotes["AAPL.US"].ask == 185.3


def test_ibkr_market_scope_validation_rejects_non_us_quotes() -> None:
    adapter = IbkrPaperBrokerAdapter(client=FakeIbkrRuntime())

    with pytest.raises(BrokerValidationError, match="US equities"):
        adapter.get_quotes(["700.HK"])


def test_ibkr_account_snapshot_uses_runtime_data() -> None:
    adapter = IbkrPaperBrokerAdapter(client=FakeIbkrRuntime())

    snapshot = adapter.get_account_snapshot(include_quotes=True)

    assert snapshot.cash_usd == 1000.0
    assert snapshot.total_portfolio_value == 1250.0
    assert [position.symbol for position in snapshot.positions] == ["AAPL.US"]
    assert snapshot.positions[0].last_price == 185.25


def test_ibkr_submit_and_query_normalize_order_records() -> None:
    runtime = FakeIbkrRuntime()
    adapter = IbkrPaperBrokerAdapter(client=runtime)

    record = adapter.submit_order(
        BrokerOrderRequest(
            symbol="AAPL",
            quantity=1,
            side="BUY",
            client_order_id="child-77",
        )
    )
    queried = adapter.get_order("42")

    assert record.broker_order_id == "77"
    assert record.status == "ACCEPTED"
    assert record.symbol == "AAPL.US"
    assert runtime.submitted == [("AAPL.US", "DU123456")]
    assert queried.status == "FILLED"
    assert queried.avg_fill_price == 185.4


def test_ibkr_get_order_falls_back_to_fills() -> None:
    adapter = IbkrPaperBrokerAdapter(client=FakeIbkrRuntime())

    record = adapter.get_order("missing")

    assert record.status == "FILLED"
    assert record.side == "BUY"
    assert record.symbol == "AAPL.US"


def test_ibkr_list_open_orders_and_cancel() -> None:
    runtime = FakeIbkrRuntime()
    adapter = IbkrPaperBrokerAdapter(client=runtime)

    open_orders = adapter.list_open_orders()
    adapter.cancel_order("11")

    assert [record.broker_order_id for record in open_orders] == ["11"]
    assert runtime.cancelled == ["11"]


def test_run_config_ibkr_reports_runtime_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cli,
        "probe_ibkr_runtime_config",
        lambda: IbkrRuntimeConfig(
            host="127.0.0.1",
            port=4002,
            client_id=7,
            account_id="DU123456",
            connect_timeout_seconds=6.0,
            host_source="env (IBKR_HOST)",
            port_source="env (IBKR_PORT_PAPER)",
            client_id_source="env (IBKR_CLIENT_ID)",
            account_id_source="env (IBKR_ACCOUNT_ID)",
            connect_timeout_source="env (IBKR_CONNECT_TIMEOUT_SECONDS)",
        ),
    )

    result = cli.run_config(True, broker="ibkr-paper")

    assert result.exit_code == 0
    assert result.stdout is not None
    assert "- Gateway Host:          127.0.0.1" in result.stdout
    assert "- Paper Port:            4002" in result.stdout
    assert "- Client ID:             7" in result.stdout
    assert "- Account ID:            DU123456" in result.stdout


def test_smoke_operator_capture_broker_env_includes_ibkr_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_smoke_operator_module()
    monkeypatch.setenv("IBKR_HOST", "127.0.0.1")
    monkeypatch.setenv("IBKR_PORT_PAPER", "4002")
    monkeypatch.setenv("IBKR_CLIENT_ID", "9")

    snapshot = module.capture_broker_env("ibkr-paper")

    assert snapshot["IBKR_HOST"] == "127.0.0.1"
    assert snapshot["IBKR_PORT_PAPER"] == "4002"
    assert snapshot["IBKR_CLIENT_ID"] == "9"
