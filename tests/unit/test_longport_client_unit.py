from datetime import date
from decimal import Decimal
from enum import Enum
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from quant_execution_engine.broker.base import BrokerImportError
import quant_execution_engine.broker.longport as longport_mod
from quant_execution_engine.broker.longport import BrokerLimits, LongPortClient


@pytest.mark.unit
def test_longport_client_requires_optional_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(longport_mod, "_LONGPORT_SDK_SOURCE", "stub")
    monkeypatch.setattr(
        longport_mod,
        "_LONGPORT_SDK_IMPORT_ERROR",
        ModuleNotFoundError("No module named 'longport'", name="longport"),
    )

    with pytest.raises(BrokerImportError, match="uv sync --extra longport"):
        LongPortClient()


@pytest.mark.unit
def test_quote_last_mapping() -> None:
    fake_resp = [
        SimpleNamespace(symbol="AAPL.US", last_done=189.5, timestamp=1234567890),
        SimpleNamespace(symbol="MSFT.US", last_done=350.2, timestamp=1234567891),
    ]

    mock_quote_context = Mock()
    mock_quote_context.quote.return_value = fake_resp

    with patch("quant_execution_engine.broker.longport.get_config"):
        client = LongPortClient.__new__(LongPortClient)
        client.q = mock_quote_context
        client.t = Mock()

        result = client.quote_last(["AAPL", "MSFT"])

    mock_quote_context.quote.assert_called_once_with(["AAPL.US", "MSFT.US"])
    assert result == {
        "AAPL.US": (189.5, 1234567890),
        "MSFT.US": (350.2, 1234567891),
    }


@pytest.mark.unit
def test_candles_parameters() -> None:
    mock_quote_context = Mock()
    mock_quote_context.history_candlesticks_by_date.return_value = []

    with patch("quant_execution_engine.broker.longport.get_config"):
        client = LongPortClient.__new__(LongPortClient)
        client.q = mock_quote_context
        client.t = Mock()

        start_date = date(2023, 1, 1)
        end_date = date(2023, 12, 31)
        custom_period = Mock()

        client.candles("AAPL", start_date, end_date, custom_period)

    call_args = mock_quote_context.history_candlesticks_by_date.call_args
    assert call_args[0][0] == "AAPL.US"
    assert call_args[0][1] == custom_period
    assert call_args[0][3] == start_date
    assert call_args[0][4] == end_date


@pytest.mark.unit
def test_submit_limit_buy_order() -> None:
    from quant_execution_engine.broker.longport import (
        OrderSide,
        OrderType,
        TimeInForceType,
    )

    mock_trade_context = Mock()
    mock_trade_context.submit_order.return_value = SimpleNamespace(order_id="12345")

    with patch("quant_execution_engine.broker.longport.get_config"):
        client = LongPortClient.__new__(LongPortClient)
        client.q = Mock()
        client.t = mock_trade_context

        result = client.submit_limit("AAPL", 150.0, 100)

    mock_trade_context.submit_order.assert_called_with(
        symbol="AAPL.US",
        order_type=OrderType.LO,
        side=OrderSide.Buy,
        submitted_price=Decimal("150.0"),
        submitted_quantity=Decimal("100"),
        time_in_force=TimeInForceType.Day,
        remark=None,
    )
    assert result.order_id == "12345"


@pytest.mark.unit
def test_submit_limit_sell_order() -> None:
    from quant_execution_engine.broker.longport import (
        OrderSide,
        OrderType,
        TimeInForceType,
    )

    mock_trade_context = Mock()
    mock_trade_context.submit_order.return_value = SimpleNamespace(order_id="67890")

    with patch("quant_execution_engine.broker.longport.get_config"):
        client = LongPortClient.__new__(LongPortClient)
        client.q = Mock()
        client.t = mock_trade_context

        result = client.submit_limit("MSFT", 300.0, -50, remark="test sell")

    mock_trade_context.submit_order.assert_called_with(
        symbol="MSFT.US",
        order_type=OrderType.LO,
        side=OrderSide.Sell,
        submitted_price=Decimal("300.0"),
        submitted_quantity=Decimal("50"),
        time_in_force=TimeInForceType.Day,
        remark="test sell",
    )
    assert result.order_id == "67890"


@pytest.mark.unit
def test_submit_limit_with_custom_tif() -> None:
    mock_order_type = Mock()
    mock_order_side = Mock()
    mock_tif_gtc = Mock()

    mock_trade_context = Mock()
    mock_trade_context.submit_order.return_value = SimpleNamespace(order_id="11111")

    with patch("quant_execution_engine.broker.longport.get_config"):
        with patch("quant_execution_engine.broker.longport.OrderType") as mock_ot:
            with patch("quant_execution_engine.broker.longport.OrderSide") as mock_os:
                with patch("quant_execution_engine.broker.longport.TimeInForceType") as mock_tif:
                    mock_ot.LO = mock_order_type
                    mock_os.Buy = mock_order_side
                    mock_tif.GTC = mock_tif_gtc

                    client = LongPortClient.__new__(LongPortClient)
                    client.q = Mock()
                    client.t = mock_trade_context

                    client.submit_limit("GOOGL", 2500.0, 10, mock_tif_gtc)

    mock_trade_context.submit_order.assert_called_with(
        symbol="GOOGL.US",
        order_type=mock_order_type,
        side=mock_order_side,
        submitted_price=Decimal("2500.0"),
        submitted_quantity=Decimal("10"),
        time_in_force=mock_tif_gtc,
        remark=None,
    )


@pytest.mark.unit
def test_decimal_precision() -> None:
    mock_trade_context = Mock()
    mock_trade_context.submit_order.return_value = SimpleNamespace(order_id="22222")

    with patch("quant_execution_engine.broker.longport.get_config"):
        client = LongPortClient.__new__(LongPortClient)
        client.q = Mock()
        client.t = mock_trade_context

        client.submit_limit("TSLA", 199.99, 25)

    call_args = mock_trade_context.submit_order.call_args
    assert call_args.kwargs["submitted_price"] == Decimal("199.99")
    assert call_args.kwargs["submitted_quantity"] == Decimal("25")
    assert isinstance(call_args.kwargs["submitted_price"], Decimal)
    assert isinstance(call_args.kwargs["submitted_quantity"], Decimal)


@pytest.mark.unit
def test_submit_market_preserves_sdk_enum_objects() -> None:
    class FakeOrderType(Enum):
        LO = "LO"
        MO = "MO"

    class FakeOrderSide(Enum):
        Buy = "Buy"
        Sell = "Sell"

    class FakeTif(Enum):
        Day = "Day"
        GTC = "GTC"

    mock_trade_context = Mock()
    mock_trade_context.submit_order.return_value = SimpleNamespace(order_id="33333")

    with patch("quant_execution_engine.broker.longport.get_config"):
        with patch("quant_execution_engine.broker.longport.OrderType", FakeOrderType):
            with patch("quant_execution_engine.broker.longport.OrderSide", FakeOrderSide):
                with patch(
                    "quant_execution_engine.broker.longport.TimeInForceType",
                    FakeTif,
                ):
                    client = LongPortClient.__new__(LongPortClient)
                    client.q = Mock()
                    client.t = mock_trade_context

                    client.submit_market("AAPL", 1)

    mock_trade_context.submit_order.assert_called_with(
        symbol="AAPL.US",
        order_type=FakeOrderType.MO,
        side=FakeOrderSide.Buy,
        submitted_quantity=Decimal("1"),
        time_in_force=FakeTif.Day,
        remark=None,
    )


@pytest.mark.unit
def test_portfolio_snapshot_basic(monkeypatch: pytest.MonkeyPatch) -> None:
    cash_info = SimpleNamespace(currency="HKD", available_cash=2000.0)
    asset_obj = SimpleNamespace(cash_infos=[cash_info], net_assets=2000.0, currency="HKD")
    pos1 = SimpleNamespace(symbol="AAPL.US", quantity=10, market="US")
    pos2 = SimpleNamespace(symbol="TSLA.US", quantity=5, market="US")
    mock_trade = Mock()
    mock_trade.asset.return_value = [asset_obj]
    mock_trade.stock_positions.return_value = [pos1, pos2]

    client = LongPortClient.__new__(LongPortClient)
    client.trade = mock_trade
    client.quote = Mock()

    monkeypatch.setenv("FX_HKD_USD", "0.25")

    cash_usd, pos_map, net_assets, base_ccy = client.portfolio_snapshot()
    assert cash_usd == pytest.approx(500.0)
    assert pos_map == {"AAPL.US": 10, "TSLA.US": 5}
    assert net_assets == 2000.0
    assert base_ccy == "HKD"


@pytest.mark.unit
def test_place_order_dry_run_returns_estimate() -> None:
    client = LongPortClient.__new__(LongPortClient)
    client.env = SimpleNamespace(value="real")
    client.limits = BrokerLimits()

    with (
        patch.object(client, "lot_size", return_value=1),
        patch.object(client, "quote_last", return_value={"AAPL.US": (150.0, "")}),
    ):
        result = client.place_order("AAPL", 2, "BUY", dry_run=True)

    assert result["dry_run"] is True
    assert result["symbol"] == "AAPL.US"
    assert result["qty"] == 2
    assert result["side"] == "BUY"
    assert result["est_px"] == 150.0
    assert result["est_notional"] == 300.0


@pytest.mark.unit
def test_place_order_live_mode_is_currently_simulated() -> None:
    client = LongPortClient.__new__(LongPortClient)
    client.env = SimpleNamespace(value="real")
    client.limits = BrokerLimits()

    with (
        patch.object(client, "_check_window"),
        patch.object(client, "_check_lot"),
        patch.object(client, "quote_last", return_value={"AAPL.US": (150.0, "")}),
        patch.object(
            client,
            "submit_market",
            return_value=SimpleNamespace(order_id="LONGPORT-123"),
        ) as mock_submit,
    ):
        result = client.place_order("AAPL", 2, "BUY", dry_run=False)

    assert result["dry_run"] is False
    assert result["symbol"] == "AAPL.US"
    assert result["qty"] == 2
    assert result["order_id"] == "LONGPORT-123"
    assert result["success"] is True
    mock_submit.assert_called_once()
