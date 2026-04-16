from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from quant_execution_engine.broker.base import BrokerAdapter, BrokerOrderRecord, ResolvedBrokerAccount
from quant_execution_engine.execution import (
    ChildOrder,
    ExecutionState,
    ExecutionStateStore,
    OrderIntent,
    ParentOrder,
)
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


class DummyLongPortPaperAdapter(BrokerAdapter):
    backend_name = "longport-paper"

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


def test_latest_tracked_order_ref_uses_current_target_input_path_over_stale_symbol_match(
    tmp_path: Path,
) -> None:
    module = load_smoke_operator_module()
    store = ExecutionStateStore(root_dir=tmp_path)
    target_input_path = str(tmp_path / "smoke-operator.json")
    state = ExecutionState(broker_name="longport-paper", account_label="main")
    state.intents = [
        OrderIntent(
            intent_id="old-intent",
            symbol="AAPL.US",
            side="BUY",
            quantity=1.0,
            order_type="MARKET",
            broker_name="longport-paper",
            account_label="main",
            target_input_path="outputs/targets/old-smoke.json",
        ),
        OrderIntent(
            intent_id="current-intent",
            symbol="AAPL.US",
            side="BUY",
            quantity=1.0,
            order_type="MARKET",
            broker_name="longport-paper",
            account_label="main",
            target_input_path=target_input_path,
        ),
    ]
    state.parent_orders = [
        ParentOrder(
            parent_order_id="parent-old",
            intent_id="old-intent",
            symbol="AAPL.US",
            side="BUY",
            requested_quantity=1.0,
            remaining_quantity=1.0,
            status="CANCELED",
            updated_at="2026-04-14T00:00:00+00:00",
        ),
        ParentOrder(
            parent_order_id="parent-current",
            intent_id="current-intent",
            symbol="AAPL.US",
            side="BUY",
            requested_quantity=1.0,
            remaining_quantity=1.0,
            status="BLOCKED",
            updated_at="2026-04-14T00:05:00+00:00",
        ),
    ]
    state.child_orders = [
        ChildOrder(
            child_order_id="child-old_1",
            parent_order_id="parent-old",
            intent_id="old-intent",
            quantity=1.0,
            attempt=1,
            broker_order_id="broker-old",
            client_order_id="child-old_1",
            status="CANCELED",
            updated_at="2026-04-14T00:00:00+00:00",
        ),
        ChildOrder(
            child_order_id="child-current_1",
            parent_order_id="parent-current",
            intent_id="current-intent",
            quantity=1.0,
            attempt=1,
            status="BLOCKED",
            message="QEXEC_KILL_SWITCH=true",
            updated_at="2026-04-14T00:05:00+00:00",
        ),
    ]
    state.broker_orders = [
        BrokerOrderRecord(
            broker_order_id="broker-old",
            symbol="AAPL.US",
            side="BUY",
            quantity=1,
            status="CANCELED",
            broker_name="longport-paper",
            account_label="main",
            client_order_id="child-old_1",
            updated_at="2026-04-14T00:00:00+00:00",
        )
    ]
    store.save(state)

    order_ref = module.latest_tracked_order_ref(
        broker_name="longport-paper",
        account_label="main",
        symbol_filter="AAPL",
        target_input_path=target_input_path,
        state_store=store,
    )
    outcome = module.latest_operator_outcome(
        broker_name="longport-paper",
        account_label="main",
        symbol_filter="AAPL",
        target_input_path=target_input_path,
        state_store=store,
    )

    assert order_ref is None
    assert outcome == {
        "status": "BLOCKED",
        "source": "local",
        "message": "QEXEC_KILL_SWITCH=true",
        "category": "RISK_BLOCKED",
        "next_step_hint": "Adjust size, price, spread/impact thresholds, or clear the kill switch before retrying.",
        "parent_order_id": "parent-current",
        "child_order_id": "child-current_1",
        "broker_order_id": None,
        "client_order_id": None,
    }


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
        preflight_only=False,
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
        preflight_only=False,
        cleanup_open_orders=False,
        allow_non_paper=False,
    )

    assert module.run_operator_smoke_workflow(args) == 2


def test_run_operator_smoke_workflow_preflight_only_skips_mutating_steps(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = load_smoke_operator_module()
    called: list[str] = []

    def ok(name: str):
        def _inner(*args, **kwargs):
            called.append(name)
            return SimpleNamespace(exit_code=0, stdout=f"{name} ok", stderr=None)

        return _inner

    def should_not_run(*args, **kwargs):
        raise AssertionError("mutating step should not run in preflight mode")

    monkeypatch.setattr(module, "run_config", ok("config"))
    monkeypatch.setattr(module, "run_account", ok("account"))
    monkeypatch.setattr(module, "run_quote", ok("quote"))
    monkeypatch.setattr(module, "run_rebalance", should_not_run)
    monkeypatch.setattr(module, "get_broker_adapter", lambda broker_name=None: DummyAdapter())
    monkeypatch.setattr(module, "get_account_snapshot", should_not_run)

    args = argparse.Namespace(
        broker="alpaca-paper",
        account="main",
        symbol="AAPL",
        market="US",
        output=str(tmp_path / "smoke-operator.json"),
        execute=False,
        preflight_only=True,
        cleanup_open_orders=False,
        allow_non_paper=False,
    )

    result = module.run_operator_smoke_workflow(args)
    output = capsys.readouterr().out

    assert result == 0
    assert called == ["config", "account", "quote"]
    assert not (tmp_path / "smoke-operator.json").exists()
    assert "Preflight checks passed" in output


def test_run_operator_smoke_workflow_accepts_longport_paper_as_paper_backend(
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
    monkeypatch.setattr(module, "get_broker_adapter", lambda broker_name=None: DummyLongPortPaperAdapter())

    args = argparse.Namespace(
        broker="longport-paper",
        account="main",
        symbol="AAPL",
        market="US",
        output=str(tmp_path / "smoke-operator.json"),
        execute=False,
        preflight_only=True,
        cleanup_open_orders=False,
        allow_non_paper=False,
    )

    result = module.run_operator_smoke_workflow(args)

    assert result == 0
    assert called == ["config", "account", "quote"]


def test_run_operator_smoke_workflow_reapplies_longport_env_between_steps(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_smoke_operator_module()
    seen: list[tuple[str, str | None, str | None]] = []

    monkeypatch.setenv("LONGPORT_REGION", "cn")
    monkeypatch.setenv("LONGPORT_ENABLE_OVERNIGHT", "true")
    monkeypatch.setenv("LONGPORT_ACCESS_TOKEN_TEST", "paper-token")

    def ok(name: str, *, mutate_region: str | None = None):
        def _inner(*args, **kwargs):
            seen.append(
                (
                    name,
                    module.os.getenv("LONGPORT_REGION"),
                    module.os.getenv("LONGPORT_ENABLE_OVERNIGHT"),
                )
            )
            if mutate_region is not None:
                module.os.environ["LONGPORT_REGION"] = mutate_region
            return SimpleNamespace(exit_code=0, stdout=f"{name} ok", stderr=None)

        return _inner

    monkeypatch.setattr(module, "run_config", ok("config", mutate_region="hk"))
    monkeypatch.setattr(module, "run_account", ok("account", mutate_region="us"))
    monkeypatch.setattr(module, "run_quote", ok("quote"))
    monkeypatch.setattr(module, "get_broker_adapter", lambda broker_name=None: DummyLongPortPaperAdapter())

    args = argparse.Namespace(
        broker="longport-paper",
        account="main",
        symbol="AAPL",
        market="US",
        output=str(tmp_path / "smoke-operator.json"),
        execute=False,
        preflight_only=True,
        cleanup_open_orders=False,
        allow_non_paper=False,
    )

    result = module.run_operator_smoke_workflow(args)

    assert result == 0
    assert seen == [
        ("config", "cn", "true"),
        ("account", "cn", "true"),
        ("quote", "cn", "true"),
    ]


def test_run_operator_smoke_workflow_uses_subprocess_cleanup_for_longport(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_smoke_operator_module()
    called: list[str] = []
    subprocess_calls: list[list[str]] = []

    def ok(name: str):
        def _inner(*args, **kwargs):
            called.append(name)
            return SimpleNamespace(exit_code=0, stdout=f"{name} ok", stderr=None)

        return _inner

    def fake_subprocess_run(argv, **kwargs):
        subprocess_calls.append(list(argv))
        return SimpleNamespace(returncode=0, stdout="cancel-all ok\n", stderr="")

    monkeypatch.setattr(module, "run_config", ok("config"))
    monkeypatch.setattr(module, "run_account", ok("account"))
    monkeypatch.setattr(module, "run_quote", ok("quote"))
    monkeypatch.setattr(module, "run_rebalance", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("run_rebalance should not be called for longport execute path")))
    monkeypatch.setattr(module, "run_orders", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("run_orders should not be called for longport execute path")))
    monkeypatch.setattr(module, "run_order", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("run_order should not be called for longport execute path")))
    monkeypatch.setattr(module, "run_reconcile", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("run_reconcile should not be called for longport execute path")))
    monkeypatch.setattr(module, "run_exceptions", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("run_exceptions should not be called for longport execute path")))
    monkeypatch.setattr(module, "run_cancel_all", lambda **kwargs: (_ for _ in ()).throw(AssertionError("run_cancel_all should not be called for longport cleanup")))
    monkeypatch.setattr(module.subprocess, "run", fake_subprocess_run)
    monkeypatch.setattr(module, "get_broker_adapter", lambda broker_name=None: DummyLongPortPaperAdapter())
    monkeypatch.setattr(
        module,
        "get_account_snapshot",
        lambda **kwargs: AccountSnapshot(
            env="paper",
            cash_usd=1000.0,
            positions=[],
        ),
    )
    monkeypatch.setattr(module, "latest_tracked_order_ref", lambda **kwargs: "broker-msft-1")

    args = argparse.Namespace(
        broker="longport-paper",
        account="main",
        symbol="MSFT",
        market="US",
        output=str(tmp_path / "smoke-operator.json"),
        execute=True,
        preflight_only=False,
        cleanup_open_orders=True,
        allow_non_paper=False,
        evidence_output=None,
    )

    result = module.run_operator_smoke_workflow(args)

    assert result == 0
    assert called == ["config", "account", "quote"]
    assert len(subprocess_calls) == 6
    assert subprocess_calls[0][-6:] == [
        str(tmp_path / "smoke-operator.json"),
        "--broker",
        "longport-paper",
        "--account",
        "main",
        "--execute",
    ]
    assert subprocess_calls[-1][-5:] == [
        "cancel-all",
        "--broker",
        "longport-paper",
        "--account",
        "main",
    ]


def test_run_operator_smoke_workflow_writes_evidence_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_smoke_operator_module()

    def ok(name: str):
        def _inner(*args, **kwargs):
            return SimpleNamespace(exit_code=0, stdout=f"{name} ok", stderr=None)

        return _inner

    monkeypatch.setattr(module, "run_config", ok("config"))
    monkeypatch.setattr(module, "run_account", ok("account"))
    monkeypatch.setattr(module, "run_quote", ok("quote"))
    monkeypatch.setattr(module, "run_rebalance", ok("rebalance"))
    monkeypatch.setattr(module, "get_broker_adapter", lambda broker_name=None: DummyAdapter())
    monkeypatch.setattr(
        module,
        "get_account_snapshot",
        lambda **kwargs: AccountSnapshot(
            env="paper",
            cash_usd=1000.0,
            positions=[],
        ),
    )

    output_path = tmp_path / "smoke-operator.json"
    evidence_path = tmp_path / "smoke-evidence.json"
    args = argparse.Namespace(
        broker="alpaca-paper",
        account="main",
        symbol="AAPL",
        market="US",
        output=str(output_path),
        execute=False,
        preflight_only=False,
        cleanup_open_orders=False,
        allow_non_paper=False,
        evidence_output=str(evidence_path),
    )

    result = module.run_operator_smoke_workflow(args)
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))

    assert result == 0
    assert evidence["broker"] == "alpaca-paper"
    assert evidence["success"] is True
    assert evidence["failed_step"] is None
    assert evidence["failure_category"] is None
    assert evidence["next_step_hint"] is None
    assert evidence["latest_tracked_order_ref"] is None
    assert evidence["skipped_steps"] == []
    assert evidence["operator_outcome_status"] is None
    assert evidence["operator_outcome_source"] is None
    assert evidence["operator_outcome_category"] is None
    assert evidence["operator_next_step_hint"] is None
    assert evidence["targets_output"] == str(output_path)
    assert [step["name"] for step in evidence["steps"]] == ["config", "account", "quote", "rebalance"]


def test_run_operator_smoke_workflow_writes_failure_evidence_for_longport_subprocess_step(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_smoke_operator_module()
    subprocess_calls: list[list[str]] = []

    def ok(name: str):
        def _inner(*args, **kwargs):
            return SimpleNamespace(exit_code=0, stdout=f"{name} ok", stderr=None)

        return _inner

    def fake_subprocess_run(argv, **kwargs):
        captured = list(argv)
        subprocess_calls.append(captured)
        step_name = captured[3]
        if step_name == "reconcile":
            return SimpleNamespace(returncode=7, stdout="", stderr="reconcile exploded\n")
        return SimpleNamespace(returncode=0, stdout=f"{step_name} ok\n", stderr="")

    monkeypatch.setattr(module, "run_config", ok("config"))
    monkeypatch.setattr(module, "run_account", ok("account"))
    monkeypatch.setattr(module, "run_quote", ok("quote"))
    monkeypatch.setattr(module.subprocess, "run", fake_subprocess_run)
    monkeypatch.setattr(module, "get_broker_adapter", lambda broker_name=None: DummyLongPortPaperAdapter())
    monkeypatch.setattr(
        module,
        "get_account_snapshot",
        lambda **kwargs: AccountSnapshot(
            env="paper",
            cash_usd=1000.0,
            positions=[],
        ),
    )
    monkeypatch.setattr(module, "latest_tracked_order_ref", lambda **kwargs: "broker-aapl-1")

    output_path = tmp_path / "smoke-operator.json"
    evidence_path = tmp_path / "smoke-failure-evidence.json"
    args = argparse.Namespace(
        broker="longport-paper",
        account="main",
        symbol="AAPL",
        market="US",
        output=str(output_path),
        execute=True,
        preflight_only=False,
        cleanup_open_orders=False,
        allow_non_paper=False,
        evidence_output=str(evidence_path),
    )

    result = module.run_operator_smoke_workflow(args)
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))

    assert result == 1
    assert len(subprocess_calls) == 4
    assert evidence["success"] is False
    assert evidence["failed_step"] == "reconcile"
    assert evidence["failure_message"] == "reconcile failed with exit code 7"
    assert evidence["failure_category"] == "RECONCILE_FAILED"
    assert "Rerun `qexec reconcile`" in evidence["next_step_hint"]
    assert evidence["latest_tracked_order_ref"] == "broker-aapl-1"
    assert evidence["skipped_steps"] == [
        {
            "name": "exceptions",
            "reason": "workflow stopped after failed step 'reconcile'",
        }
    ]
    assert [step["name"] for step in evidence["steps"]] == [
        "config",
        "account",
        "quote",
        "rebalance",
        "orders",
        "order",
        "reconcile",
    ]
    assert evidence["steps"][-1]["exit_code"] == 7
    assert evidence["steps"][-1]["stderr"] == "reconcile exploded"


def test_run_operator_smoke_workflow_writes_failure_evidence_when_rebalance_step_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_smoke_operator_module()
    subprocess_calls: list[list[str]] = []

    def ok(name: str):
        def _inner(*args, **kwargs):
            return SimpleNamespace(exit_code=0, stdout=f"{name} ok", stderr=None)

        return _inner

    def fake_subprocess_run(argv, **kwargs):
        captured = list(argv)
        subprocess_calls.append(captured)
        return SimpleNamespace(returncode=9, stdout="", stderr="rebalance blew up\n")

    monkeypatch.setattr(module, "run_config", ok("config"))
    monkeypatch.setattr(module, "run_account", ok("account"))
    monkeypatch.setattr(module, "run_quote", ok("quote"))
    monkeypatch.setattr(module.subprocess, "run", fake_subprocess_run)
    monkeypatch.setattr(module, "get_broker_adapter", lambda broker_name=None: DummyLongPortPaperAdapter())
    monkeypatch.setattr(
        module,
        "get_account_snapshot",
        lambda **kwargs: AccountSnapshot(
            env="paper",
            cash_usd=1000.0,
            positions=[],
        ),
    )
    monkeypatch.setattr(
        module,
        "latest_tracked_order_ref",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("latest_tracked_order_ref should not run")),
    )

    output_path = tmp_path / "smoke-operator.json"
    evidence_path = tmp_path / "smoke-rebalance-failure-evidence.json"
    args = argparse.Namespace(
        broker="longport-paper",
        account="main",
        symbol="AAPL",
        market="US",
        output=str(output_path),
        execute=True,
        preflight_only=False,
        cleanup_open_orders=False,
        allow_non_paper=False,
        evidence_output=str(evidence_path),
    )

    result = module.run_operator_smoke_workflow(args)
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))

    assert result == 1
    assert len(subprocess_calls) == 1
    assert evidence["success"] is False
    assert evidence["failed_step"] == "rebalance"
    assert evidence["failure_message"] == "rebalance failed with exit code 9"
    assert evidence["failure_category"] == "REBALANCE_EXECUTION_FAILED"
    assert "rebalance stderr" in evidence["next_step_hint"]
    assert evidence["latest_tracked_order_ref"] is None
    assert [item["name"] for item in evidence["skipped_steps"]] == [
        "orders",
        "order",
        "reconcile",
        "exceptions",
    ]
    assert [step["name"] for step in evidence["steps"]] == [
        "config",
        "account",
        "quote",
        "rebalance",
    ]
    assert evidence["steps"][-1]["stderr"] == "rebalance blew up"


def test_run_operator_smoke_workflow_skips_order_step_when_no_tracked_order_exists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = load_smoke_operator_module()
    subprocess_calls: list[list[str]] = []

    def ok(name: str):
        def _inner(*args, **kwargs):
            return SimpleNamespace(exit_code=0, stdout=f"{name} ok", stderr=None)

        return _inner

    def fake_subprocess_run(argv, **kwargs):
        captured = list(argv)
        subprocess_calls.append(captured)
        step_name = captured[3]
        return SimpleNamespace(returncode=0, stdout=f"{step_name} ok\n", stderr="")

    monkeypatch.setattr(module, "run_config", ok("config"))
    monkeypatch.setattr(module, "run_account", ok("account"))
    monkeypatch.setattr(module, "run_quote", ok("quote"))
    monkeypatch.setattr(module.subprocess, "run", fake_subprocess_run)
    monkeypatch.setattr(module, "get_broker_adapter", lambda broker_name=None: DummyLongPortPaperAdapter())
    monkeypatch.setattr(
        module,
        "get_account_snapshot",
        lambda **kwargs: AccountSnapshot(
            env="paper",
            cash_usd=1000.0,
            positions=[],
        ),
    )
    monkeypatch.setattr(module, "latest_tracked_order_ref", lambda **kwargs: None)

    output_path = tmp_path / "smoke-operator.json"
    evidence_path = tmp_path / "smoke-no-order-evidence.json"
    args = argparse.Namespace(
        broker="longport-paper",
        account="main",
        symbol="AAPL",
        market="US",
        output=str(output_path),
        execute=True,
        preflight_only=False,
        cleanup_open_orders=False,
        allow_non_paper=False,
        evidence_output=str(evidence_path),
    )

    result = module.run_operator_smoke_workflow(args)
    output = capsys.readouterr().out
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))

    assert result == 0
    assert [call[3] for call in subprocess_calls] == [
        "rebalance",
        "orders",
        "reconcile",
        "exceptions",
    ]
    assert "No tracked broker order found after rebalance" in output
    assert evidence["latest_tracked_order_ref"] is None
    assert evidence["failure_category"] is None
    assert evidence["next_step_hint"] is None
    assert evidence["skipped_steps"] == [
        {
            "name": "order",
            "reason": "no tracked order reference available after rebalance",
        }
    ]
    assert [step["name"] for step in evidence["steps"]] == [
        "config",
        "account",
        "quote",
        "rebalance",
        "orders",
        "reconcile",
        "exceptions",
    ]


def test_run_operator_smoke_workflow_writes_blocked_operator_outcome_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_smoke_operator_module()
    real_store_cls = ExecutionStateStore
    store = real_store_cls(root_dir=tmp_path)
    output_path = tmp_path / "smoke-operator.json"
    target_input_path = str(output_path)
    state = ExecutionState(broker_name="longport-paper", account_label="main")
    state.intents = [
        OrderIntent(
            intent_id="old-intent",
            symbol="AAPL.US",
            side="BUY",
            quantity=1.0,
            order_type="MARKET",
            broker_name="longport-paper",
            account_label="main",
            target_input_path="outputs/targets/old-smoke.json",
        ),
        OrderIntent(
            intent_id="current-intent",
            symbol="AAPL.US",
            side="BUY",
            quantity=1.0,
            order_type="MARKET",
            broker_name="longport-paper",
            account_label="main",
            target_input_path=target_input_path,
        ),
    ]
    state.parent_orders = [
        ParentOrder(
            parent_order_id="parent-old",
            intent_id="old-intent",
            symbol="AAPL.US",
            side="BUY",
            requested_quantity=1.0,
            remaining_quantity=1.0,
            status="CANCELED",
            updated_at="2026-04-14T00:00:00+00:00",
        ),
        ParentOrder(
            parent_order_id="parent-current",
            intent_id="current-intent",
            symbol="AAPL.US",
            side="BUY",
            requested_quantity=1.0,
            remaining_quantity=1.0,
            status="BLOCKED",
            updated_at="2026-04-14T00:05:00+00:00",
        ),
    ]
    state.child_orders = [
        ChildOrder(
            child_order_id="child-old_1",
            parent_order_id="parent-old",
            intent_id="old-intent",
            quantity=1.0,
            attempt=1,
            broker_order_id="broker-old",
            client_order_id="child-old_1",
            status="CANCELED",
            updated_at="2026-04-14T00:00:00+00:00",
        ),
        ChildOrder(
            child_order_id="child-current_1",
            parent_order_id="parent-current",
            intent_id="current-intent",
            quantity=1.0,
            attempt=1,
            status="BLOCKED",
            message="QEXEC_KILL_SWITCH=true",
            updated_at="2026-04-14T00:05:00+00:00",
        ),
    ]
    state.broker_orders = [
        BrokerOrderRecord(
            broker_order_id="broker-old",
            symbol="AAPL.US",
            side="BUY",
            quantity=1,
            status="CANCELED",
            broker_name="longport-paper",
            account_label="main",
            client_order_id="child-old_1",
            updated_at="2026-04-14T00:00:00+00:00",
        )
    ]
    store.save(state)

    def store_factory(*args, **kwargs):
        return real_store_cls(root_dir=tmp_path)

    def ok(name: str):
        def _inner(*args, **kwargs):
            return SimpleNamespace(exit_code=0, stdout=f"{name} ok", stderr=None)

        return _inner

    def fake_subprocess_run(argv, **kwargs):
        step_name = list(argv)[3]
        return SimpleNamespace(returncode=0, stdout=f"{step_name} ok\n", stderr="")

    monkeypatch.setattr(module, "ExecutionStateStore", store_factory)
    monkeypatch.setattr(module, "run_config", ok("config"))
    monkeypatch.setattr(module, "run_account", ok("account"))
    monkeypatch.setattr(module, "run_quote", ok("quote"))
    monkeypatch.setattr(module.subprocess, "run", fake_subprocess_run)
    monkeypatch.setattr(module, "get_broker_adapter", lambda broker_name=None: DummyLongPortPaperAdapter())
    monkeypatch.setattr(
        module,
        "get_account_snapshot",
        lambda **kwargs: AccountSnapshot(
            env="paper",
            cash_usd=1000.0,
            positions=[],
        ),
    )

    evidence_path = tmp_path / "smoke-blocked-evidence.json"
    args = argparse.Namespace(
        broker="longport-paper",
        account="main",
        symbol="AAPL",
        market="US",
        output=str(output_path),
        execute=True,
        preflight_only=False,
        cleanup_open_orders=False,
        allow_non_paper=False,
        evidence_output=str(evidence_path),
    )

    result = module.run_operator_smoke_workflow(args)
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))

    assert result == 0
    assert evidence["success"] is True
    assert evidence["failed_step"] is None
    assert evidence["latest_tracked_order_ref"] is None
    assert evidence["operator_outcome_status"] == "BLOCKED"
    assert evidence["operator_outcome_source"] == "local"
    assert evidence["operator_outcome_message"] == "QEXEC_KILL_SWITCH=true"
    assert evidence["operator_outcome_category"] == "RISK_BLOCKED"
    assert "clear the kill switch" in evidence["operator_next_step_hint"]
    assert evidence["operator_outcome_parent_order_id"] == "parent-current"
    assert evidence["operator_outcome_child_order_id"] == "child-current_1"
    assert evidence["operator_outcome_broker_order_id"] is None
    assert evidence["operator_outcome_client_order_id"] is None
    assert evidence["skipped_steps"] == [
        {
            "name": "order",
            "reason": "latest tracked outcome is BLOCKED and has no broker order reference",
        }
    ]
    assert [step["name"] for step in evidence["steps"]] == [
        "config",
        "account",
        "quote",
        "rebalance",
        "orders",
        "reconcile",
        "exceptions",
    ]


@pytest.mark.parametrize(
    ("failed_step", "cleanup_open_orders", "expected_step_names", "expected_skipped_names", "expected_category"),
    [
        (
            "orders",
            False,
            ["config", "account", "quote", "rebalance", "orders"],
            ["order", "reconcile", "exceptions"],
            "OPEN_ORDER_QUERY_FAILED",
        ),
        (
            "order",
            False,
            ["config", "account", "quote", "rebalance", "orders", "order"],
            ["reconcile", "exceptions"],
            "TRACKED_ORDER_QUERY_FAILED",
        ),
        (
            "exceptions",
            False,
            ["config", "account", "quote", "rebalance", "orders", "order", "reconcile", "exceptions"],
            [],
            "EXCEPTION_VIEW_FAILED",
        ),
        (
            "cancel-all",
            True,
            [
                "config",
                "account",
                "quote",
                "rebalance",
                "orders",
                "order",
                "reconcile",
                "exceptions",
                "cancel-all",
            ],
            [],
            "BULK_CANCEL_FAILED",
        ),
    ],
)
def test_run_operator_smoke_workflow_writes_failure_evidence_for_downstream_steps(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failed_step: str,
    cleanup_open_orders: bool,
    expected_step_names: list[str],
    expected_skipped_names: list[str],
    expected_category: str,
) -> None:
    module = load_smoke_operator_module()

    def ok(name: str):
        def _inner(*args, **kwargs):
            return SimpleNamespace(exit_code=0, stdout=f"{name} ok", stderr=None)

        return _inner

    def fake_subprocess_run(argv, **kwargs):
        step_name = list(argv)[3]
        if step_name == failed_step:
            return SimpleNamespace(
                returncode=5,
                stdout="",
                stderr=f"{failed_step} exploded\n",
            )
        return SimpleNamespace(returncode=0, stdout=f"{step_name} ok\n", stderr="")

    monkeypatch.setattr(module, "run_config", ok("config"))
    monkeypatch.setattr(module, "run_account", ok("account"))
    monkeypatch.setattr(module, "run_quote", ok("quote"))
    monkeypatch.setattr(module.subprocess, "run", fake_subprocess_run)
    monkeypatch.setattr(module, "get_broker_adapter", lambda broker_name=None: DummyLongPortPaperAdapter())
    monkeypatch.setattr(
        module,
        "get_account_snapshot",
        lambda **kwargs: AccountSnapshot(
            env="paper",
            cash_usd=1000.0,
            positions=[],
        ),
    )
    if failed_step == "orders":
        monkeypatch.setattr(
            module,
            "latest_tracked_order_ref",
            lambda **kwargs: (_ for _ in ()).throw(
                AssertionError("latest_tracked_order_ref should not run when orders fails")
            ),
        )
    else:
        monkeypatch.setattr(module, "latest_tracked_order_ref", lambda **kwargs: "broker-aapl-1")

    evidence_path = tmp_path / f"{failed_step}-failure-evidence.json"
    args = argparse.Namespace(
        broker="longport-paper",
        account="main",
        symbol="AAPL",
        market="US",
        output=str(tmp_path / "smoke-operator.json"),
        execute=True,
        preflight_only=False,
        cleanup_open_orders=cleanup_open_orders,
        allow_non_paper=False,
        evidence_output=str(evidence_path),
    )

    result = module.run_operator_smoke_workflow(args)
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))

    assert result == 1
    assert evidence["success"] is False
    assert evidence["failed_step"] == failed_step
    assert evidence["failure_category"] == expected_category
    assert evidence["failure_message"] == f"{failed_step} failed with exit code 5"
    assert evidence["next_step_hint"] is not None
    assert evidence["latest_tracked_order_ref"] == (
        None if failed_step == "orders" else "broker-aapl-1"
    )
    assert [item["name"] for item in evidence["skipped_steps"]] == expected_skipped_names
    assert [step["name"] for step in evidence["steps"]] == expected_step_names
    assert evidence["steps"][-1]["stderr"] == f"{failed_step} exploded"
