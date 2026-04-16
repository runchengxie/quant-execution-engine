from __future__ import annotations

import pytest

from quant_execution_engine.broker.base import BrokerOrderRecord
from quant_execution_engine.diagnostics import diagnose_order_issue, diagnose_warning_message


pytestmark = pytest.mark.unit


def test_diagnose_order_issue_classifies_buying_power_rejections() -> None:
    record = BrokerOrderRecord(
        broker_order_id="broker-1",
        symbol="AAPL.US",
        side="BUY",
        quantity=10,
        status="REJECTED",
        broker_name="alpaca-paper",
        account_label="main",
        message="insufficient buying power for order",
    )

    diagnostic = diagnose_order_issue(record)

    assert diagnostic is not None
    assert diagnostic.code == "BROKER_REJECTED_FUNDS"
    assert "Reduce order size" in str(diagnostic.action_hint)


def test_diagnose_order_issue_classifies_session_rejections() -> None:
    record = BrokerOrderRecord(
        broker_order_id="broker-2",
        symbol="700.HK",
        side="BUY",
        quantity=1,
        status="REJECTED",
        broker_name="longport",
        account_label="main",
        message="market is closed for the requested trading session",
    )

    diagnostic = diagnose_order_issue(record)

    assert diagnostic is not None
    assert diagnostic.code == "BROKER_REJECTED_SESSION"
    assert "session" in diagnostic.summary.lower()


def test_diagnose_order_issue_preserves_generic_raw_code_when_unclassified() -> None:
    record = BrokerOrderRecord(
        broker_order_id="broker-3",
        symbol="AAPL.US",
        side="BUY",
        quantity=1,
        status="REJECTED",
        broker_name="fake",
        account_label="main",
        message="unexpected broker validation",
        raw={"error_code": "ERR-42"},
    )

    diagnostic = diagnose_order_issue(record)

    assert diagnostic is not None
    assert diagnostic.code == "ERR-42"


def test_diagnose_warning_message_classifies_network_failures() -> None:
    diagnostic = diagnose_warning_message("network timeout while querying broker")

    assert diagnostic.code == "BROKER_NETWORK_WARNING"
    assert "Retry" in str(diagnostic.action_hint)

