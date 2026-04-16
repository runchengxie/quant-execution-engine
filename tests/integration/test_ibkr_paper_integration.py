from __future__ import annotations

import os

import pytest


pytestmark = [pytest.mark.integration, pytest.mark.requires_api]

pytest.importorskip("ib_insync")

from quant_execution_engine.broker.base import BrokerOrderRequest
from quant_execution_engine.broker.ibkr import IbkrPaperBrokerAdapter


def _integration_enabled() -> bool:
    return str(os.getenv("IBKR_ENABLE_INTEGRATION", "")).strip() == "1"


def _mutation_enabled() -> bool:
    return str(os.getenv("IBKR_ENABLE_MUTATION_TESTS", "")).strip() == "1"


def _fill_enabled() -> bool:
    return str(os.getenv("IBKR_ENABLE_FILL_TESTS", "")).strip() == "1"


def _runtime_issue(message: str) -> bool:
    lowered = str(message or "").lower()
    return any(
        token in lowered
        for token in (
            "unable to connect",
            "connection",
            "gateway",
            "timeout",
            "market data",
            "not available",
        )
    )


@pytest.mark.skipif(
    not _integration_enabled(),
    reason="Set IBKR_ENABLE_INTEGRATION=1 to run IBKR paper integration tests",
)
def test_ibkr_paper_account_and_quote_round_trip() -> None:
    adapter = IbkrPaperBrokerAdapter()
    try:
        account = adapter.resolve_account("main")
        snapshot = adapter.get_account_snapshot(account, include_quotes=False)
        quotes = adapter.get_quotes(["AAPL"], include_depth=True)
    except Exception as exc:
        if _runtime_issue(str(exc)):
            pytest.skip(f"IBKR paper runtime is not reachable: {exc}")
        raise
    finally:
        adapter.close()

    assert account.label == "main"
    assert snapshot.base_currency in {None, "USD"}
    assert "AAPL.US" in quotes
    assert quotes["AAPL.US"].price >= 0


@pytest.mark.skipif(
    not _mutation_enabled(),
    reason="Set IBKR_ENABLE_MUTATION_TESTS=1 to run IBKR paper mutation tests",
)
def test_ibkr_paper_submit_query_cancel_and_reconcile() -> None:
    adapter = IbkrPaperBrokerAdapter()
    try:
        account = adapter.resolve_account("main")
        quote = adapter.get_quotes(["AAPL"])["AAPL.US"]
        limit_price = max(1.0, round(float(quote.price or 1.0) * 0.5, 2))
        record = adapter.submit_order(
            BrokerOrderRequest(
                symbol="AAPL",
                quantity=1,
                side="BUY",
                order_type="LIMIT",
                limit_price=limit_price,
                account=account,
                client_order_id="ibkr-int-limit",
            )
        )
        queried = adapter.get_order(record.broker_order_id, account)
        open_orders = adapter.list_open_orders(account)
        adapter.cancel_order(record.broker_order_id, account)
        refreshed = adapter.get_order(record.broker_order_id, account)
        report = adapter.reconcile(account)
    except Exception as exc:
        if _runtime_issue(str(exc)):
            pytest.skip(f"IBKR paper runtime is not reachable: {exc}")
        raise
    finally:
        adapter.close()

    assert record.broker_order_id
    assert queried.broker_order_id == record.broker_order_id
    assert report.account_label == "main"
    assert any(
        order.broker_order_id == record.broker_order_id for order in open_orders
    ) or queried.status in {"PENDING_NEW", "NEW", "ACCEPTED", "PARTIALLY_FILLED"}
    assert refreshed.status in {
        "CANCELED",
        "PENDING_CANCEL",
        "NEW",
        "ACCEPTED",
        "PARTIALLY_FILLED",
        "FILLED",
    }


@pytest.mark.skipif(
    not _fill_enabled(),
    reason="Set IBKR_ENABLE_FILL_TESTS=1 to run IBKR paper fill tests",
)
def test_ibkr_paper_market_order_can_surface_fills() -> None:
    adapter = IbkrPaperBrokerAdapter()
    try:
        account = adapter.resolve_account("main")
        record = adapter.submit_order(
            BrokerOrderRequest(
                symbol="AAPL",
                quantity=1,
                side="BUY",
                account=account,
                client_order_id="ibkr-int-fill",
            )
        )
        refreshed = adapter.get_order(record.broker_order_id, account)
        fills = adapter.list_fills(account, broker_order_id=record.broker_order_id)
        report = adapter.reconcile(account)
    except Exception as exc:
        if _runtime_issue(str(exc)):
            pytest.skip(f"IBKR paper runtime is not reachable: {exc}")
        raise
    finally:
        adapter.close()

    assert refreshed.broker_order_id == record.broker_order_id
    assert report.account_label == "main"
    assert fills or refreshed.status in {
        "NEW",
        "ACCEPTED",
        "PENDING_NEW",
        "PARTIALLY_FILLED",
        "FILLED",
    }
