from __future__ import annotations

from types import SimpleNamespace

import pytest

import quant_execution_engine.broker.alpaca as alpaca_mod
from quant_execution_engine.broker.base import BrokerImportError


pytestmark = pytest.mark.unit


def test_alpaca_import_surfaces_missing_dependency_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_import_module(name: str):
        raise ModuleNotFoundError("No module named 'pytz'", name="pytz")

    monkeypatch.setattr(alpaca_mod.importlib, "import_module", fake_import_module)

    with pytest.raises(BrokerImportError, match="dependency 'pytz' is missing"):
        alpaca_mod._alpaca_import("alpaca.data.requests.StockLatestTradeRequest")


def test_get_account_snapshot_only_requires_trading_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested_paths: list[str] = []

    class FakeTradingClient:
        def __init__(self, *, api_key: str, secret_key: str, paper: bool) -> None:
            assert api_key == "key"
            assert secret_key == "secret"
            assert paper is True

        def get_account(self):
            return SimpleNamespace(cash="1000", portfolio_value="1000")

        def get_all_positions(self):
            return []

    def fake_alpaca_import(path: str):
        requested_paths.append(path)
        if path == "alpaca.trading.client.TradingClient":
            return FakeTradingClient
        raise AssertionError(f"unexpected import path: {path}")

    monkeypatch.setattr(alpaca_mod, "_alpaca_import", fake_alpaca_import)
    monkeypatch.setenv("ALPACA_API_KEY", "key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "secret")

    adapter = alpaca_mod.AlpacaPaperBrokerAdapter()
    snapshot = adapter.get_account_snapshot()

    assert snapshot.cash_usd == 1000.0
    assert requested_paths == ["alpaca.trading.client.TradingClient"]
