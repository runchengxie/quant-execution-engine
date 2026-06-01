from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from quant_execution_engine.broker.factory import (
    get_broker_adapter,
    get_broker_capabilities,
    is_paper_broker,
)
from quant_execution_engine.models import AccountSnapshot, Position, Quote
from quant_execution_engine.rebalance import FeeSchedule, RebalanceService
from quant_execution_engine.targets import TargetEntry

pytestmark = pytest.mark.unit


def make_snapshot() -> AccountSnapshot:
    position = Position(symbol="AAA.US", quantity=1, last_price=10.0, estimated_value=10.0)
    return AccountSnapshot(env="test", cash_usd=100.0, positions=[position])


def test_fetch_quotes() -> None:
    service = RebalanceService()

    with (
        patch("quant_execution_engine.rebalance.get_quotes") as mock_get,
        patch.object(RebalanceService, "_get_client", return_value=object()),
    ):
        mock_get.return_value = {"AAA.US": Quote(symbol="AAA.US", price=10.0, timestamp="")}
        quotes = service._fetch_quotes(["AAA"])

    assert quotes == {"AAA.US": 10.0}
    mock_get.assert_called_once()


def test_coerce_lb_symbol_preserves_a_share_exchange_suffix() -> None:
    assert (
        RebalanceService._coerce_lb_symbol(
            TargetEntry(symbol="600519.SH", market="CN", target_weight=1.0)
        )
        == "600519.SH.CN"
    )
    assert RebalanceService._coerce_lb_symbol("858.SZ") == "000858.SZ.CN"
    assert RebalanceService._coerce_lb_symbol("600000.XSHG") == "600000.SH.CN"
    assert RebalanceService._coerce_lb_symbol("1.XSHE") == "000001.SZ.CN"


def test_plan_rebalance_cn_dry_run_lot_sizing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FX_CNY_USD", "0.14")
    service = RebalanceService(env="paper")
    client = SimpleNamespace(lot_size=lambda symbol: 100 if symbol.endswith(".CN") else 1)
    snapshot = AccountSnapshot(env="paper", cash_usd=1400.0, positions=[])
    targets = [TargetEntry(symbol="600519.SH", market="CN", target_weight=1.0)]

    with patch.object(RebalanceService, "_get_client", return_value=client):
        result = service.plan_rebalance(
            targets,
            snapshot,
            quotes={"600519.SH.CN": 10.0},
        )

    assert result.target_positions[0].symbol == "600519.SH.CN"
    assert result.target_positions[0].quantity == 1000
    assert result.orders[0].symbol == "600519.SH.CN"
    assert result.orders[0].quantity == 1000
    assert result.orders[0].side == "BUY"


def test_plan_rebalance_rejects_cn_quote_without_fx_rate() -> None:
    service = RebalanceService(env="paper")
    client = SimpleNamespace(lot_size=lambda symbol: 100 if symbol.endswith(".CN") else 1)
    snapshot = AccountSnapshot(env="paper", cash_usd=1400.0, positions=[])
    targets = [TargetEntry(symbol="600519.SH", market="CN", target_weight=1.0)]

    with (
        patch.object(RebalanceService, "_get_client", return_value=client),
        patch("quant_execution_engine.rebalance.get_rate_to_usd", return_value=None),
        pytest.raises(ValueError, match="missing FX rate for CNY"),
    ):
        service.plan_rebalance(
            targets,
            snapshot,
            quotes={"600519.SH.CN": 10.0},
        )


def test_local_dry_run_backend_supports_offline_cn_file_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QEXEC_LOCAL_DRY_RUN_CASH_USD", "1400")
    monkeypatch.setenv("QEXEC_LOCAL_DRY_RUN_PRICE", "10")

    capabilities = get_broker_capabilities("local-dry-run")
    adapter = get_broker_adapter(broker_name="local-dry-run")

    assert is_paper_broker("local-dry-run") is True
    assert capabilities.supports_live_submit is False
    assert adapter.get_account_snapshot().cash_usd == pytest.approx(1400)
    assert adapter.get_quotes(["600519.SH.CN"])["600519.SH.CN"].price == pytest.approx(10)
    assert adapter.lot_size("600519.SH.CN") == 100


def test_compute_effective_total() -> None:
    service = RebalanceService()
    snapshot = make_snapshot()

    effective_total = service._compute_effective_total(snapshot, {"AAA.US": 10.0}, 1.0)

    assert effective_total == pytest.approx(110.0)


def test_build_order() -> None:
    service = RebalanceService()
    client = SimpleNamespace(lot_size=lambda _symbol: 1)
    fees = FeeSchedule(0, 0, 0, 0, 0)

    position, order = service._build_order(
        "AAA.US",
        10.0,
        0,
        10.0,
        False,
        client,
        fees,
        True,
        Decimal("0.001"),
    )

    assert position.quantity == 10
    assert order is not None
    assert order.quantity == 10
    assert order.side == "BUY"


def test_plan_rebalance_honors_target_weights() -> None:
    service = RebalanceService()
    client = SimpleNamespace(lot_size=lambda _symbol: 1)
    snapshot = AccountSnapshot(env="test", cash_usd=100.0, positions=[])
    targets = [
        TargetEntry(symbol="AAA", market="US", target_weight=0.2),
        TargetEntry(symbol="BBB", market="US", target_weight=0.8),
    ]

    with patch.object(RebalanceService, "_get_client", return_value=client):
        result = service.plan_rebalance(
            targets,
            snapshot,
            quotes={"AAA.US": 10.0, "BBB.US": 10.0},
        )

    target_map = {position.symbol: position.quantity for position in result.target_positions}
    assert target_map["AAA.US"] == 2
    assert target_map["BBB.US"] == 8


def test_plan_rebalance_honors_target_quantity() -> None:
    service = RebalanceService()
    client = SimpleNamespace(lot_size=lambda _symbol: 1)
    snapshot = AccountSnapshot(env="test", cash_usd=100.0, positions=[])
    targets = [TargetEntry(symbol="AAA", market="US", target_quantity=5)]

    with patch.object(RebalanceService, "_get_client", return_value=client):
        result = service.plan_rebalance(
            targets,
            snapshot,
            quotes={"AAA.US": 10.0},
        )

    assert result.target_positions[0].symbol == "AAA.US"
    assert result.target_positions[0].quantity == 5


def test_plan_rebalance_converts_hk_quote_to_usd_before_sizing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FX_HKD_USD", "0.125")
    service = RebalanceService()
    client = SimpleNamespace(lot_size=lambda _symbol: 1)
    snapshot = AccountSnapshot(env="paper", cash_usd=100.0, positions=[])
    targets = [TargetEntry(symbol="700", market="HK", target_weight=1.0)]

    with patch.object(RebalanceService, "_get_client", return_value=client):
        result = service.plan_rebalance(
            targets,
            snapshot,
            quotes={"700.HK": 100.0},
        )

    assert result.target_positions[0].last_price == pytest.approx(12.5)
    assert result.target_positions[0].quantity == 8


def test_plan_rebalance_rejects_non_us_quote_without_fx_rate() -> None:
    service = RebalanceService()
    client = SimpleNamespace(lot_size=lambda _symbol: 1)
    snapshot = AccountSnapshot(env="paper", cash_usd=100.0, positions=[])
    targets = [TargetEntry(symbol="700", market="HK", target_weight=1.0)]

    with (
        patch.object(RebalanceService, "_get_client", return_value=client),
        patch("quant_execution_engine.rebalance.get_rate_to_usd", return_value=None),
        pytest.raises(ValueError, match="missing FX rate for HKD"),
    ):
        service.plan_rebalance(
            targets,
            snapshot,
            quotes={"700.HK": 100.0},
        )


def test_plan_rebalance_requires_quote_for_held_non_us_position(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FX_HKD_USD", "0.125")
    service = RebalanceService()
    client = SimpleNamespace(lot_size=lambda _symbol: 1)
    snapshot = AccountSnapshot(
        env="paper",
        cash_usd=100.0,
        positions=[
            Position(
                symbol="388.HK",
                quantity=100,
                last_price=250.0,
                estimated_value=25000.0,
            )
        ],
    )
    targets = [TargetEntry(symbol="700", market="HK", target_weight=1.0)]

    with (
        patch.object(RebalanceService, "_get_client", return_value=client),
        pytest.raises(ValueError, match="existing non-USD position"),
    ):
        service.plan_rebalance(
            targets,
            snapshot,
            quotes={"700.HK": 100.0},
        )
