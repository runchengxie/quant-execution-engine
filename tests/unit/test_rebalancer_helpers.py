from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import pytest

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
