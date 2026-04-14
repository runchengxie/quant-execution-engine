from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from quant_execution_engine.broker.base import BrokerAdapter, BrokerOrderRecord, ResolvedBrokerAccount
from quant_execution_engine.execution import ExecutionState, ExecutionStateStore
from quant_execution_engine.models import AccountSnapshot, Position


pytestmark = pytest.mark.unit


def load_smoke_operator_module():
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


class DummyAdapter(BrokerAdapter):
    backend_name = "alpaca-paper"

    def resolve_account(self, account_label: str | None = None) -> ResolvedBrokerAccount:
        return ResolvedBrokerAccount(label=account_label or "main")


def test_build_operator_smoke_targets_is_minimal_delta() -> None:
    module = load_smoke_operator_module()

    targets = module.build_operator_smoke_targets(
        symbol="AAPL",
        market="US",
        current_quantity=3,
    )

    assert targets[0]["symbol"] == "AAPL"
    assert targets[0]["market"] == "US"
    assert targets[0]["target_quantity"] == 4


def test_latest_tracked_order_ref_prefers_latest_matching_symbol(tmp_path: Path) -> None:
    module = load_smoke_operator_module()
    store = ExecutionStateStore(root_dir=tmp_path)
    state = ExecutionState(broker_name="alpaca-paper", account_label="main")
    state.broker_orders = [
        BrokerOrderRecord(
            broker_order_id="aapl-old",
            symbol="AAPL.US",
            side="BUY",
            quantity=1,
            status="NEW",
            broker_name="alpaca-paper",
            account_label="main",
            updated_at="2026-04-14T00:00:00+00:00",
        ),
        BrokerOrderRecord(
            broker_order_id="msft-new",
            symbol="MSFT.US",
            side="BUY",
            quantity=1,
            status="NEW",
            broker_name="alpaca-paper",
            account_label="main",
            updated_at="2026-04-14T00:02:00+00:00",
        ),
        BrokerOrderRecord(
            broker_order_id="aapl-new",
            symbol="AAPL.US",
            side="BUY",
            quantity=1,
            status="NEW",
            broker_name="alpaca-paper",
            account_label="main",
            updated_at="2026-04-14T00:03:00+00:00",
        ),
    ]
    store.save(state)

    order_ref = module.latest_tracked_order_ref(
        broker_name="alpaca-paper",
        account_label="main",
        symbol_filter="AAPL",
        state_store=store,
    )

    assert order_ref == "aapl-new"


def test_run_operator_smoke_workflow_executes_fixed_sequence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_smoke_operator_module()
    called: list[str] = []

    def ok(name: str):
        def _inner(*args, **kwargs):
            called.append(name)
            return SimpleNamespace(exit_code=0, stdout=f"{name} ok", stderr=None)

        return _inner

    monkeypatch.setattr(module, "run_config", ok("config"))
    monkeypatch.setattr(module, "run_account", ok("account"))
    monkeypatch.setattr(module, "run_quote", ok("quote"))
    monkeypatch.setattr(module, "run_rebalance", ok("rebalance"))
    monkeypatch.setattr(module, "run_orders", ok("orders"))
    monkeypatch.setattr(module, "run_order", ok("order"))
    monkeypatch.setattr(module, "run_reconcile", ok("reconcile"))
    monkeypatch.setattr(module, "run_exceptions", ok("exceptions"))
    monkeypatch.setattr(module, "run_cancel_all", ok("cancel-all"))
    monkeypatch.setattr(module, "get_broker_adapter", lambda broker_name=None: DummyAdapter())
    monkeypatch.setattr(
        module,
        "get_account_snapshot",
        lambda **kwargs: AccountSnapshot(
            env="paper",
            cash_usd=1000.0,
            positions=[
                Position(
                    symbol="AAPL.US",
                    quantity=0,
                    last_price=10.0,
                    estimated_value=0.0,
                    env="paper",
                )
            ],
        ),
    )
    monkeypatch.setattr(module, "latest_tracked_order_ref", lambda **kwargs: "broker-aapl-1")

    args = argparse.Namespace(
        broker="alpaca-paper",
        account="main",
        symbol="AAPL",
        market="US",
        output=str(tmp_path / "smoke-operator.json"),
        execute=True,
        cleanup_open_orders=True,
        allow_non_paper=False,
    )

    result = module.run_operator_smoke_workflow(args)
    payload = json.loads((tmp_path / "smoke-operator.json").read_text(encoding="utf-8"))

    assert result == 0
    assert called == [
        "config",
        "account",
        "quote",
        "rebalance",
        "orders",
        "order",
        "reconcile",
        "exceptions",
        "cancel-all",
    ]
    assert payload["source"] == "smoke-operator-harness"
    assert payload["targets"][0]["target_quantity"] == 1


def test_run_operator_smoke_workflow_refuses_non_paper_by_default() -> None:
    module = load_smoke_operator_module()
    args = argparse.Namespace(
        broker="longport",
        account="main",
        symbol="AAPL",
        market="US",
        output="outputs/targets/smoke-operator.json",
        execute=False,
        cleanup_open_orders=False,
        allow_non_paper=False,
    )

    assert module.run_operator_smoke_workflow(args) == 2
