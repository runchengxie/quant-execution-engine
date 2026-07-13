from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import cast

import pytest

from quant_execution_engine.broker.alpaca import AlpacaPaperBrokerAdapter
from quant_execution_engine.broker.base import (
    BrokerAdapter,
    BrokerCapabilityMatrix,
    BrokerOrderRecord,
    BrokerOrderRequest,
    ResolvedBrokerAccount,
)
from quant_execution_engine.broker.ibkr import IbkrPaperBrokerAdapter
from quant_execution_engine.broker.local_dry_run import LocalDryRunBrokerAdapter
from quant_execution_engine.broker.longport_adapter import (
    LongPortBrokerAdapter,
    LongPortPaperBrokerAdapter,
)
from quant_execution_engine.broker_transport import BrokerAdapterExecutionTransport
from quant_execution_engine.domain import (
    InstrumentId,
    OrderIntent,
    OrderSide,
    OrderStatus,
    OrderType,
)
from quant_execution_engine.execution_journal import DurableExecutionJournal, SubmissionState
from quant_execution_engine.paper_transport import InMemoryPaperExecutionTransport
from quant_execution_engine.transport import (
    ExecutionTransport,
    SubmissionOutcomeUnknownError,
    TransportMappingError,
    TransportOrderReference,
    TransportSubmitRequest,
    UnsupportedTransportCapabilityError,
)
from quant_execution_engine.transport_service import JournaledExecutionTransport

pytestmark = pytest.mark.unit

NOW = datetime(2026, 7, 13, 10, 0, tzinfo=timezone.utc)


def _intent(
    intent_id: str = "intent-transport-001",
    *,
    broker_name: str = "memory-paper",
) -> OrderIntent:
    return OrderIntent(
        intent_id=intent_id,
        instrument=InstrumentId(symbol="AAPL", market="US", currency="USD"),
        side=OrderSide.BUY,
        quantity=Decimal("10"),
        order_type=OrderType.MARKET,
        created_at=NOW,
        broker_name=broker_name,
        account_label="main",
        run_id="run-transport-001",
    )


class _ConformingBroker(BrokerAdapter):
    backend_name = "conforming-broker"
    capabilities = BrokerCapabilityMatrix(
        name=backend_name,
        supports_live_submit=True,
        supports_cancel=True,
        supports_order_query=True,
        supports_open_order_listing=True,
        supports_reconcile=True,
        supports_fractional=False,
        supports_short=False,
        supported_order_types=("MARKET", "LIMIT"),
        supported_time_in_force=("DAY",),
    )

    def __init__(self) -> None:
        self.submit_calls = 0
        self.orders: dict[str, BrokerOrderRecord] = {}

    def resolve_account(self, account_label: str | None = None) -> ResolvedBrokerAccount:
        return ResolvedBrokerAccount(label=account_label or "main")

    def submit_order(self, request: BrokerOrderRequest) -> BrokerOrderRecord:
        self.submit_calls += 1
        record = BrokerOrderRecord(
            broker_order_id=f"broker-{request.client_order_id}",
            symbol=request.symbol,
            side=request.side,
            quantity=request.quantity,
            broker_name=self.backend_name,
            account_label=request.account.label if request.account else "main",
            status="ACCEPTED",
            client_order_id=request.client_order_id,
            submitted_at=NOW.isoformat(),
            updated_at=NOW.isoformat(),
        )
        self.orders[record.broker_order_id] = record
        return record

    def get_order(
        self,
        broker_order_id: str,
        account: ResolvedBrokerAccount | None = None,
    ) -> BrokerOrderRecord:
        return self.orders[broker_order_id]

    def list_open_orders(
        self,
        account: ResolvedBrokerAccount | None = None,
    ) -> list[BrokerOrderRecord]:
        return list(self.orders.values())

    def cancel_order(
        self,
        broker_order_id: str,
        account: ResolvedBrokerAccount | None = None,
    ) -> None:
        record = self.orders[broker_order_id]
        record.status = "CANCELED"
        record.updated_at = datetime(2026, 7, 13, 10, 1, tzinfo=timezone.utc).isoformat()


class _AcceptedThenTimeoutBroker(_ConformingBroker):
    backend_name = "accepted-timeout-broker"
    capabilities = BrokerCapabilityMatrix(
        name=backend_name,
        supports_live_submit=True,
        supports_cancel=True,
        supports_order_query=True,
        supports_open_order_listing=True,
        supported_order_types=("MARKET",),
        supported_time_in_force=("DAY",),
    )

    def submit_order(self, request: BrokerOrderRequest) -> BrokerOrderRecord:
        record = super().submit_order(request)
        raise TimeoutError(f"response lost after accepting {record.broker_order_id}")


def _service(
    tmp_path: Path,
    transport: ExecutionTransport,
) -> tuple[JournaledExecutionTransport, DurableExecutionJournal]:
    journal = DurableExecutionJournal(tmp_path / "transport-journal.sqlite3")
    return JournaledExecutionTransport(transport, journal), journal


def test_in_memory_transport_is_fully_offline_and_journaled(tmp_path: Path) -> None:
    transport = InMemoryPaperExecutionTransport()
    service, journal = _service(tmp_path, transport)
    intent = _intent()

    outcome = service.submit(
        intent,
        idempotency_key="portfolio/main/run/row-1",
        attempt_id="attempt-001",
        occurred_at=NOW,
    )
    duplicate = service.submit(
        intent,
        idempotency_key="portfolio/main/run/row-1",
        attempt_id="attempt-duplicate",
        occurred_at=NOW,
    )

    assert outcome.submitted is True
    assert outcome.lifecycle.submission_state is SubmissionState.ACCEPTED
    assert duplicate.submitted is False
    assert duplicate.preparation.should_submit is False
    assert outcome.submission is not None

    reference = outcome.submission.reference
    transport.record_fill(
        reference,
        fill_id="paper-fill-001",
        quantity=Decimal("4"),
        price=Decimal("190.5"),
        filled_at=datetime(2026, 7, 13, 10, 2, tzinfo=timezone.utc),
    )
    partial = service.poll_and_record(reference)
    repeated = service.poll_and_record(reference)

    assert partial.submission_state is SubmissionState.PARTIALLY_FILLED
    assert partial.filled_quantity == Decimal("4")
    assert repeated == partial
    assert len(journal.replay().intents[intent.intent_id].fills) == 1

    cancellation = service.cancel_and_record(reference)
    assert cancellation.accepted is True
    assert journal.replay().intents[intent.intent_id].submission_state is SubmissionState.CANCELLED


def test_in_memory_transport_rejects_conflicting_fill_identity(tmp_path: Path) -> None:
    transport = InMemoryPaperExecutionTransport()
    service, _ = _service(tmp_path, transport)
    outcome = service.submit(
        _intent(),
        idempotency_key="portfolio/main/fill-conflict",
        attempt_id="attempt-fill-conflict",
        occurred_at=NOW,
    )
    assert outcome.submission is not None
    reference = outcome.submission.reference
    filled_at = datetime(2026, 7, 13, 10, 3, tzinfo=timezone.utc)
    transport.record_fill(
        reference,
        fill_id="same-fill-id",
        quantity=Decimal("1"),
        price=Decimal("100"),
        filled_at=filled_at,
    )

    with pytest.raises(ValueError, match="reused for different content"):
        transport.record_fill(
            reference,
            fill_id="same-fill-id",
            quantity=Decimal("2"),
            price=Decimal("100"),
            filled_at=filled_at,
        )


@pytest.mark.parametrize("kind", ["memory", "broker-adapter"])
def test_transport_common_submit_query_poll_cancel_conformance(
    tmp_path: Path,
    kind: str,
) -> None:
    transport: ExecutionTransport
    if kind == "memory":
        transport = InMemoryPaperExecutionTransport()
    else:
        transport = BrokerAdapterExecutionTransport(_ConformingBroker())
    assert isinstance(transport, ExecutionTransport)
    capabilities = transport.discover_capabilities()
    assert capabilities.supports_submit is True
    assert capabilities.supports_query is True
    assert capabilities.supports_event_poll is True
    assert capabilities.supports_cancel is True

    service, _ = _service(tmp_path, transport)
    outcome = service.submit(
        _intent(f"intent-{kind}", broker_name=capabilities.backend_name),
        idempotency_key=f"portfolio/main/{kind}",
        attempt_id=f"attempt-{kind}",
        occurred_at=NOW,
    )
    assert outcome.submission is not None
    queried = transport.query(outcome.submission.reference)
    polled = transport.poll(outcome.submission.reference)
    assert queried.reference == polled.reference
    assert queried.order_events[-1].status is OrderStatus.ACCEPTED
    cancelled = service.cancel_and_record(outcome.submission.reference)
    assert cancelled.accepted is True


def test_accepted_but_timed_out_submission_is_never_retried_blindly(tmp_path: Path) -> None:
    adapter = _AcceptedThenTimeoutBroker()
    transport = BrokerAdapterExecutionTransport(adapter)
    service, journal = _service(tmp_path, transport)
    intent = _intent("intent-timeout", broker_name=adapter.backend_name)

    with pytest.raises(SubmissionOutcomeUnknownError, match="response lost after accepting"):
        service.submit(
            intent,
            idempotency_key="portfolio/main/timeout-row",
            attempt_id="attempt-timeout",
            occurred_at=NOW,
        )

    uncertain = journal.replay().intents[intent.intent_id]
    assert uncertain.submission_state is SubmissionState.SUBMISSION_UNCERTAIN
    assert uncertain.requires_reconciliation is True
    assert "TimeoutError" in uncertain.uncertainty_messages[-1]

    duplicate = service.submit(
        intent,
        idempotency_key="portfolio/main/timeout-row",
        attempt_id="attempt-restart",
        occurred_at=NOW,
    )
    assert duplicate.submitted is False
    assert adapter.submit_calls == 1

    reconciled = service.query_and_record(TransportOrderReference.from_intent(intent))
    assert reconciled.submission_state is SubmissionState.ACCEPTED
    assert reconciled.broker_order_id == f"broker-{intent.intent_id}"


def test_unsupported_submit_fails_before_consuming_journal_permission(tmp_path: Path) -> None:
    transport = BrokerAdapterExecutionTransport(LocalDryRunBrokerAdapter())
    service, journal = _service(tmp_path, transport)

    with pytest.raises(UnsupportedTransportCapabilityError, match="does not support submission"):
        service.submit(
            _intent(),
            idempotency_key="portfolio/main/unsupported",
            attempt_id="attempt-unsupported",
            occurred_at=NOW,
        )

    assert journal.replay().through_sequence == 0


def test_route_mismatch_fails_before_consuming_journal_permission(tmp_path: Path) -> None:
    service, journal = _service(tmp_path, InMemoryPaperExecutionTransport())

    with pytest.raises(TransportMappingError, match="does not match transport"):
        service.submit(
            _intent(broker_name="another-paper-backend"),
            idempotency_key="portfolio/main/route-mismatch",
            attempt_id="attempt-route-mismatch",
            occurred_at=NOW,
        )

    assert journal.replay().through_sequence == 0


def test_transport_submit_request_rejects_non_permission(tmp_path: Path) -> None:
    journal = DurableExecutionJournal(tmp_path / "permission.sqlite3")
    intent = _intent()
    first = journal.prepare_submission(
        intent,
        idempotency_key="portfolio/main/permission",
        attempt_id="attempt-first",
        occurred_at=NOW,
    )
    denied = journal.prepare_submission(
        intent,
        idempotency_key="portfolio/main/permission",
        attempt_id="attempt-second",
        occurred_at=NOW,
    )
    assert first.should_submit is True
    assert denied.should_submit is False
    with pytest.raises(ValueError, match="one-shot should_submit permission"):
        TransportSubmitRequest(intent=intent, preparation=denied)


@pytest.mark.parametrize(
    "adapter_type",
    [
        AlpacaPaperBrokerAdapter,
        IbkrPaperBrokerAdapter,
        LocalDryRunBrokerAdapter,
        LongPortBrokerAdapter,
        LongPortPaperBrokerAdapter,
    ],
)
def test_all_builtin_broker_capabilities_map_without_loading_runtime(
    adapter_type: type[BrokerAdapter],
) -> None:
    adapter = cast(BrokerAdapter, object.__new__(adapter_type))
    capabilities = BrokerAdapterExecutionTransport(adapter).discover_capabilities()

    assert capabilities.backend_name == adapter_type.backend_name
    assert capabilities.execution.supported_order_types
    assert capabilities.execution.supported_time_in_force
    if adapter_type is LongPortPaperBrokerAdapter:
        assert capabilities.supports_submit is True
    if adapter_type is LocalDryRunBrokerAdapter:
        assert capabilities.supports_submit is False
