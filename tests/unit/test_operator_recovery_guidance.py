from pathlib import Path

import pytest

import quant_execution_engine.cli as cli
import quant_execution_engine.execution as execution
from quant_execution_engine.broker.base import (
    BrokerAdapter,
    BrokerOrderRecord,
    BrokerOrderRequest,
    ResolvedBrokerAccount,
)
from quant_execution_engine.diagnostics import (
    diagnose_order_issue,
    diagnose_warning_message,
)
from quant_execution_engine.execution_state import (
    ChildOrder,
    ExecutionCancelResult,
    ExecutionStaleRetryResult,
    ExecutionState,
    ExecutionStateStore,
    OrderIntent,
    ParentOrder,
)
from quant_execution_engine.renderers.table import (
    render_broker_orders,
    render_stale_retry_summary,
)

pytestmark = pytest.mark.unit


def test_diagnostics_classify_stale_open_order_and_pending_cancel() -> None:
    stale = BrokerOrderRecord(
        broker_order_id="broker-stale",
        symbol="AAPL.US",
        side="BUY",
        quantity=10,
        broker_name="fake",
        account_label="main",
        status="NEW",
        message="stale open order older than operator threshold",
    )
    pending_cancel = BrokerOrderRecord(
        broker_order_id="broker-pending",
        symbol="AAPL.US",
        side="BUY",
        quantity=10,
        broker_name="fake",
        account_label="main",
        status="PENDING_CANCEL",
    )

    stale_diagnostic = diagnose_order_issue(stale)
    pending_diagnostic = diagnose_order_issue(pending_cancel)

    assert stale_diagnostic is not None
    assert stale_diagnostic.code == "STALE_OPEN_ORDER"
    assert "Run reconcile first" in str(stale_diagnostic.action_hint)
    assert pending_diagnostic is not None
    assert pending_diagnostic.code == "CANCEL_PENDING"


def test_warning_diagnostics_cover_stale_retry_followups() -> None:
    pending = diagnose_warning_message(
        "broker-1: skipped retry because post-cancel status is PENDING_CANCEL"
    )
    cancel_failed = diagnose_warning_message("broker-1: cancel failed: timeout")
    retry_failed = diagnose_warning_message("broker-1: retry failed: rejected")

    assert pending.code == "CANCEL_PENDING"
    assert cancel_failed.code == "STALE_CANCEL_FAILED"
    assert retry_failed.code == "STALE_RETRY_FAILED"


def test_orders_and_retry_stale_render_normalized_next_steps(tmp_path: Path) -> None:
    orders_output = render_broker_orders(
        [
            BrokerOrderRecord(
                broker_order_id="broker-stale",
                symbol="AAPL.US",
                side="BUY",
                quantity=10,
                broker_name="fake",
                account_label="main",
                status="NEW",
                message="stale open order older than operator threshold",
            )
        ]
    )
    stale_output = render_stale_retry_summary(
        ExecutionStaleRetryResult(
            broker_name="fake",
            account_label="main",
            state_path=tmp_path / "state.json",
            older_than_minutes=5,
            targeted_orders=1,
            cancel_results=[
                ExecutionCancelResult(
                    broker_name="fake",
                    account_label="main",
                    order_ref="broker-1",
                    broker_order_id="broker-1",
                    client_order_id=None,
                    status="PENDING_CANCEL",
                    state_path=tmp_path / "state.json",
                    warnings=[
                        "cancel submitted but post-cancel refresh failed: timeout"
                    ],
                )
            ],
        )
    )

    assert "[STALE_OPEN_ORDER]" in orders_output
    assert "Next: Run reconcile first" in orders_output
    assert "[POST_CANCEL_REFRESH_FAILED]" in stale_output
    assert "next: Run reconcile before taking further action" in stale_output


class _MutationRecordingAdapter(BrokerAdapter):
    backend_name = "fake"

    def __init__(self) -> None:
        self.submit_calls = 0
        self.cancel_calls: list[str] = []

    def resolve_account(
        self,
        account_label: str | None = None,
    ) -> ResolvedBrokerAccount:
        return ResolvedBrokerAccount(label=account_label or "main")

    def submit_order(self, request: BrokerOrderRequest) -> BrokerOrderRecord:
        self.submit_calls += 1
        raise AssertionError("run_order must not submit")

    def cancel_order(
        self,
        broker_order_id: str,
        account: ResolvedBrokerAccount | None = None,
    ) -> None:
        self.cancel_calls.append(broker_order_id)
        raise AssertionError("run_order must not cancel")


def test_order_guidance_is_advisory_and_does_not_mutate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = ExecutionStateStore(root_dir=tmp_path)
    state = ExecutionState(broker_name="fake", account_label="main")
    state.intents.append(
        OrderIntent(
            intent_id="intent-1",
            symbol="AAPL.US",
            side="BUY",
            quantity=10,
            order_type="MARKET",
            broker_name="fake",
            account_label="main",
        )
    )
    state.parent_orders.append(
        ParentOrder(
            parent_order_id="parent-1",
            intent_id="intent-1",
            symbol="AAPL.US",
            side="BUY",
            requested_quantity=10,
            remaining_quantity=10,
            status="PENDING_CANCEL",
            child_order_ids=["child-1"],
        )
    )
    state.child_orders.append(
        ChildOrder(
            child_order_id="child-1",
            parent_order_id="parent-1",
            intent_id="intent-1",
            quantity=10,
            broker_order_id="broker-1",
            status="PENDING_CANCEL",
        )
    )
    state.broker_orders.append(
        BrokerOrderRecord(
            broker_order_id="broker-1",
            symbol="AAPL.US",
            side="BUY",
            quantity=10,
            broker_name="fake",
            account_label="main",
            status="PENDING_CANCEL",
        )
    )
    store.save(state)
    adapter = _MutationRecordingAdapter()

    monkeypatch.setattr(cli, "get_broker_adapter", lambda broker_name=None: adapter)
    monkeypatch.setattr(execution, "ExecutionStateStore", lambda: store)

    result = cli.run_order(order_ref="broker-1", account="main", broker="fake")

    assert result.exit_code == 0
    assert result.stdout is not None
    assert "Suggested Next Step" in result.stdout
    assert adapter.submit_calls == 0
    assert adapter.cancel_calls == []
