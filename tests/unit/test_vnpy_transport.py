# ruff: noqa: E402
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

vnpy = pytest.importorskip("vnpy", reason="install the optional vnpy extra")

from vnpy.event import Event
from vnpy.trader.constant import (
    Direction as VnDirection,
)
from vnpy.trader.constant import (
    Exchange as VnExchange,
)
from vnpy.trader.constant import (
    OrderType as VnOrderType,
)
from vnpy.trader.constant import Product, Status
from vnpy.trader.event import EVENT_ORDER, EVENT_TRADE
from vnpy.trader.object import CancelRequest, ContractData, OrderData, OrderRequest, TradeData

from quant_execution_engine.domain import (
    InstrumentId,
    OrderIntent,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
)
from quant_execution_engine.execution_journal import DurableExecutionJournal, SubmissionState
from quant_execution_engine.transport import (
    ExecutionTransport,
    ExecutionTransportError,
    SubmissionOutcomeUnknownError,
    TransportOrderReference,
    TransportSubmitRequest,
    UnsupportedTransportCapabilityError,
)
from quant_execution_engine.transport_service import JournaledExecutionTransport
from quant_execution_engine.vnpy_transport import (
    VnPyExecutionTransport,
    VnPyGatewayProfile,
    VnPyOrderPreview,
    VnPyTransportMode,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 7, 13, 11, 0, tzinfo=timezone.utc)


class _FakeEventEngine:
    def __init__(self) -> None:
        self.handlers: dict[str, list[Callable[[object], None]]] = {}

    def register(self, event_type: str, handler: Callable[[object], None]) -> None:
        self.handlers.setdefault(event_type, []).append(handler)

    def unregister(self, event_type: str, handler: Callable[[object], None]) -> None:
        self.handlers[event_type].remove(handler)

    def emit(self, event: Event) -> None:
        for handler in tuple(self.handlers.get(event.type, ())):
            handler(event)


class _FakeGateway:
    def __init__(self, name: str) -> None:
        self.name = name
        self.order_requests: list[OrderRequest] = []
        self.cancel_requests: list[CancelRequest] = []

    def send_order(self, request: object) -> str:
        assert isinstance(request, OrderRequest)
        self.order_requests.append(request)
        return f"{self.name}.{len(self.order_requests)}"

    def cancel_order(self, request: object) -> None:
        assert isinstance(request, CancelRequest)
        self.cancel_requests.append(request)


class _FakeMainEngine:
    def __init__(self, contract: ContractData, *, gateway_name: str = "SIM") -> None:
        self.event_engine = _FakeEventEngine()
        self.gateway = _FakeGateway(gateway_name)
        self.contracts = {contract.vt_symbol: contract}
        self.close_calls = 0

    def send_order(self, request: object, gateway_name: str) -> str:
        assert gateway_name == self.gateway.name
        return self.gateway.send_order(request)

    def cancel_order(self, request: object, gateway_name: str) -> None:
        assert gateway_name == self.gateway.name
        self.gateway.cancel_order(request)

    def get_contract(self, vt_symbol: str) -> object | None:
        return self.contracts.get(vt_symbol)

    def get_all_contracts(self) -> list[object]:
        return list(self.contracts.values())

    def close(self) -> None:
        self.close_calls += 1


def _contract(
    *,
    gateway_name: str = "SIM",
    min_volume: float = 1,
    stop_supported: bool = True,
) -> ContractData:
    return ContractData(
        gateway_name=gateway_name,
        symbol="AAPL",
        exchange=VnExchange.NASDAQ,
        name="Apple",
        product=Product.EQUITY,
        size=1,
        pricetick=0.01,
        min_volume=min_volume,
        stop_supported=stop_supported,
    )


def _transport(
    *,
    mode: VnPyTransportMode = VnPyTransportMode.PAPER,
    allow_live: bool = False,
    profile: VnPyGatewayProfile | None = None,
    contract: ContractData | None = None,
    owns_main_engine: bool = False,
) -> tuple[VnPyExecutionTransport, _FakeMainEngine]:
    engine = _FakeMainEngine(contract or _contract())
    transport = VnPyExecutionTransport(
        engine,
        gateway_name="SIM",
        mode=mode,
        allow_live=allow_live,
        profile=profile,
        owns_main_engine=owns_main_engine,
    )
    return transport, engine


def _intent(
    backend_name: str,
    *,
    intent_id: str = "vnpy-intent-001",
    quantity: str = "10",
    side: OrderSide = OrderSide.BUY,
    opens_short: bool = False,
    order_type: OrderType = OrderType.MARKET,
    time_in_force: TimeInForce = TimeInForce.DAY,
    limit_price: str | None = None,
) -> OrderIntent:
    return OrderIntent(
        intent_id=intent_id,
        instrument=InstrumentId(
            symbol="AAPL",
            market="US",
            exchange="NASDAQ",
            currency="USD",
        ),
        side=side,
        quantity=Decimal(quantity),
        order_type=order_type,
        created_at=NOW,
        limit_price=Decimal(limit_price) if limit_price is not None else None,
        time_in_force=time_in_force,
        opens_short=opens_short,
        broker_name=backend_name,
        account_label="main",
        run_id="run-vnpy-001",
    )


def _service(
    tmp_path: Path,
    transport: VnPyExecutionTransport,
) -> tuple[JournaledExecutionTransport, DurableExecutionJournal]:
    journal = DurableExecutionJournal(tmp_path / "vnpy-journal.sqlite3")
    return JournaledExecutionTransport(transport, journal), journal


def _submit(
    tmp_path: Path,
    transport: VnPyExecutionTransport,
    intent: OrderIntent | None = None,
) -> tuple[
    JournaledExecutionTransport,
    DurableExecutionJournal,
    OrderIntent,
    TransportOrderReference,
]:
    service, journal = _service(tmp_path, transport)
    actual_intent = intent or _intent(transport.discover_capabilities().backend_name)
    outcome = service.submit(
        actual_intent,
        idempotency_key=f"portfolio/main/{actual_intent.intent_id}",
        attempt_id=f"attempt-{actual_intent.intent_id}",
        occurred_at=NOW,
    )
    assert outcome.submission is not None
    assert outcome.submission.reference.broker_order_id is not None
    return service, journal, actual_intent, outcome.submission.reference


def test_shadow_blocks_send_at_capability_and_runtime_layers(tmp_path: Path) -> None:
    transport, engine = _transport(mode=VnPyTransportMode.SHADOW)
    capabilities = transport.discover_capabilities()
    intent = _intent(capabilities.backend_name)
    preview = transport.preview_order(intent)

    assert capabilities.supports_submit is False
    assert capabilities.supports_cancel is False
    assert isinstance(preview, VnPyOrderPreview)
    assert preview.order_type == "MARKET"
    service, journal = _service(tmp_path, transport)
    with pytest.raises(UnsupportedTransportCapabilityError, match="does not support submission"):
        service.submit(
            intent,
            idempotency_key="portfolio/main/shadow",
            attempt_id="attempt-shadow",
            occurred_at=NOW,
        )
    assert journal.replay().through_sequence == 0

    preparation = journal.prepare_submission(
        intent,
        idempotency_key="portfolio/main/shadow-direct",
        attempt_id="attempt-shadow-direct",
        occurred_at=NOW,
    )
    with pytest.raises(UnsupportedTransportCapabilityError, match="SHADOW mode forbids"):
        transport.submit(TransportSubmitRequest(intent=intent, preparation=preparation))
    assert engine.gateway.order_requests == []


def test_live_requires_explicit_gate_and_then_uses_fake_gateway(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="only valid in LIVE"):
        _transport(mode=VnPyTransportMode.PAPER, allow_live=True)

    blocked, blocked_engine = _transport(mode=VnPyTransportMode.LIVE)
    assert blocked.discover_capabilities().supports_submit is False
    blocked_service, blocked_journal = _service(tmp_path / "blocked", blocked)
    with pytest.raises(UnsupportedTransportCapabilityError):
        blocked_service.submit(
            _intent(blocked.discover_capabilities().backend_name, intent_id="live-blocked"),
            idempotency_key="portfolio/main/live-blocked",
            attempt_id="attempt-live-blocked",
            occurred_at=NOW,
        )
    assert blocked_journal.replay().through_sequence == 0
    assert blocked_engine.gateway.order_requests == []

    allowed, allowed_engine = _transport(mode=VnPyTransportMode.LIVE, allow_live=True)
    _submit(
        tmp_path / "allowed",
        allowed,
        _intent(allowed.discover_capabilities().backend_name, intent_id="live-allowed"),
    )
    assert len(allowed_engine.gateway.order_requests) == 1


def test_paper_transport_conforms_and_maps_real_vnpy_dtos(tmp_path: Path) -> None:
    transport, engine = _transport()
    capabilities = transport.discover_capabilities()
    assert isinstance(transport, ExecutionTransport)
    assert capabilities.supports_submit is True
    assert capabilities.supports_cancel is True
    assert capabilities.supports_event_poll is True
    assert capabilities.supports_query is False
    assert capabilities.supports_client_order_lookup is False
    assert "contract_count=1" in capabilities.notes

    service, journal, intent, reference = _submit(tmp_path, transport)
    request = engine.gateway.order_requests[-1]
    assert type(request) is OrderRequest
    assert request.symbol == "AAPL"
    assert request.exchange is VnExchange.NASDAQ
    assert request.direction is VnDirection.LONG
    assert request.type is VnOrderType.MARKET
    assert request.volume == 10
    assert request.reference == intent.intent_id
    assert journal.replay().intents[intent.intent_id].submission_state is SubmissionState.ACCEPTED

    accepted = OrderData(
        gateway_name="SIM",
        symbol="AAPL",
        exchange=VnExchange.NASDAQ,
        orderid="1",
        type=VnOrderType.MARKET,
        direction=VnDirection.LONG,
        volume=10,
        traded=0,
        status=Status.NOTTRADED,
        datetime=NOW,
        reference=intent.intent_id,
    )
    partial = OrderData(
        gateway_name="SIM",
        symbol="AAPL",
        exchange=VnExchange.NASDAQ,
        orderid="1",
        type=VnOrderType.MARKET,
        direction=VnDirection.LONG,
        volume=10,
        traded=4,
        status=Status.PARTTRADED,
        datetime=datetime(2026, 7, 13, 11, 2, tzinfo=timezone.utc),
        reference=intent.intent_id,
    )
    trade = TradeData(
        gateway_name="SIM",
        symbol="AAPL",
        exchange=VnExchange.NASDAQ,
        orderid="1",
        tradeid="trade-001",
        direction=VnDirection.LONG,
        price=190.5,
        volume=4,
        datetime=datetime(2026, 7, 13, 11, 1, tzinfo=timezone.utc),
    )
    engine.event_engine.emit(Event(EVENT_ORDER, partial))
    engine.event_engine.emit(Event(EVENT_TRADE, trade))
    engine.event_engine.emit(Event(EVENT_ORDER, accepted))  # stale/out of order
    engine.event_engine.emit(Event(EVENT_ORDER, partial))  # duplicate callback
    engine.event_engine.emit(Event(EVENT_TRADE, trade))  # duplicate fill

    batch = transport.poll(reference)
    assert len(batch.order_events) == 3
    assert len(batch.fills) == 2
    assert batch.order_events[0].event_id == batch.order_events[2].event_id
    assert batch.order_events[0].event_id != batch.order_events[1].event_id
    assert batch.fills[0].fill_id == batch.fills[1].fill_id
    lifecycle = service.record_batch(batch)

    assert reference.broker_order_id == "SIM.1"
    assert lifecycle.submission_state is SubmissionState.PARTIALLY_FILLED
    assert lifecycle.order_status is OrderStatus.PARTIALLY_FILLED
    assert lifecycle.filled_quantity == Decimal("4")
    assert tuple(fill.fill_id for fill in lifecycle.fills) == ("vnpy-trade:SIM.trade-001",)
    assert service.poll_and_record(reference) == lifecycle


def test_cancel_uses_real_cancel_request_and_query_fails_explicitly(tmp_path: Path) -> None:
    transport, engine = _transport()
    service, _, _, reference = _submit(tmp_path, transport)

    result = service.cancel_and_record(reference)
    assert result.accepted is True
    assert result.order_event is None
    request = engine.gateway.cancel_requests[-1]
    assert type(request) is CancelRequest
    assert request.orderid == "1"
    assert request.symbol == "AAPL"
    assert request.exchange is VnExchange.NASDAQ
    with pytest.raises(UnsupportedTransportCapabilityError, match="not a reliable broker query"):
        transport.query(reference)


@pytest.mark.parametrize(
    ("time_in_force", "expected"),
    [(TimeInForce.IOC, VnOrderType.FAK), (TimeInForce.FOK, VnOrderType.FOK)],
)
def test_limit_tif_maps_to_real_vnpy_order_type(
    tmp_path: Path,
    time_in_force: TimeInForce,
    expected: VnOrderType,
) -> None:
    transport, engine = _transport()
    backend = transport.discover_capabilities().backend_name
    intent = _intent(
        backend,
        intent_id=f"intent-{time_in_force.value.lower()}",
        order_type=OrderType.LIMIT,
        time_in_force=time_in_force,
        limit_price="191.25",
    )
    _submit(tmp_path, transport, intent)

    request = engine.gateway.order_requests[-1]
    assert request.type is expected
    assert request.price == 191.25


def test_contract_and_short_capabilities_fail_before_send(tmp_path: Path) -> None:
    lot_transport, lot_engine = _transport(contract=_contract(min_volume=100))
    lot_service, lot_journal = _service(tmp_path / "lot", lot_transport)
    with pytest.raises(SubmissionOutcomeUnknownError, match="min_volume"):
        lot_service.submit(
            _intent(lot_transport.discover_capabilities().backend_name, quantity="50"),
            idempotency_key="portfolio/main/bad-lot",
            attempt_id="attempt-bad-lot",
            occurred_at=NOW,
        )
    # Contract-specific checks happen inside the adapter after durable permit;
    # the conservative journal therefore requires reconciliation, but no send occurred.
    assert lot_journal.replay().intents["vnpy-intent-001"].requires_reconciliation is True
    assert lot_engine.gateway.order_requests == []

    short_transport, short_engine = _transport()
    short_service, short_journal = _service(tmp_path / "short", short_transport)
    with pytest.raises(ValueError, match="short-sale"):
        short_service.submit(
            _intent(
                short_transport.discover_capabilities().backend_name,
                side=OrderSide.SELL,
                opens_short=True,
            ),
            idempotency_key="portfolio/main/short",
            attempt_id="attempt-short",
            occurred_at=NOW,
        )
    assert short_journal.replay().through_sequence == 0
    assert short_engine.gateway.order_requests == []


def test_close_unregisters_handlers_and_respects_engine_ownership() -> None:
    transport, engine = _transport(owns_main_engine=True)
    assert len(engine.event_engine.handlers[EVENT_ORDER]) == 1
    assert len(engine.event_engine.handlers[EVENT_TRADE]) == 1

    transport.close()
    transport.close()

    assert engine.event_engine.handlers[EVENT_ORDER] == []
    assert engine.event_engine.handlers[EVENT_TRADE] == []
    assert engine.close_calls == 1
    with pytest.raises(ExecutionTransportError, match="closed"):
        transport.discover_capabilities()
