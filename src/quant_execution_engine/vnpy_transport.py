# pyright: strict
"""Optional vn.py Gateway/OMS bridge for the typed execution transport."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone, tzinfo
from decimal import Decimal
from threading import RLock
from typing import Protocol, cast

from ._vnpy_bindings import (
    VnPyBindings,
    VnPyImportError,
    VnPyOrderSnapshot,
    VnPyTradeSnapshot,
    load_vnpy_bindings,
    order_snapshot,
    trade_snapshot,
)
from ._vnpy_mapper import (
    VnPyContractStore,
    VnPyGatewayProfile,
    VnPyOrderPreview,
    VnPyTransportMode,
    VnPyValueMapper,
)
from .domain import ExecutionEventType, Fill, OrderEvent, OrderIntent, OrderStatus
from .transport import (
    ExecutionTransportError,
    TransportCancellation,
    TransportCapabilities,
    TransportEventBatch,
    TransportMappingError,
    TransportOrderReference,
    TransportSubmission,
    TransportSubmitRequest,
    UnsupportedTransportCapabilityError,
)


class _EventHandler(Protocol):
    def __call__(self, event: object) -> None: ...


class _EventEngine(Protocol):
    def register(self, event_type: str, handler: _EventHandler) -> None: ...

    def unregister(self, event_type: str, handler: _EventHandler) -> None: ...


class _MainEngine(VnPyContractStore, Protocol):
    event_engine: _EventEngine

    def send_order(self, request: object, gateway_name: str) -> str: ...

    def cancel_order(self, request: object, gateway_name: str) -> None: ...

    def close(self) -> None: ...


def _submit_event_id(gateway_name: str, broker_order_id: str, intent_id: str) -> str:
    digest = hashlib.sha256(f"{gateway_name}\0{broker_order_id}\0{intent_id}".encode()).hexdigest()[
        :24
    ]
    return f"vnpy-submit-{digest}"


class VnPyExecutionTransport:
    """Bridge qexec intents and journal facts to a vn.py MainEngine/Gateway.

    vn.py provides Gateway dispatch, an event engine, and an in-memory OMS.
    qexec remains the owner of approval, policy, preflight, durable
    idempotency, reconciliation, and audit evidence.
    """

    def __init__(
        self,
        main_engine: object,
        *,
        gateway_name: str,
        mode: VnPyTransportMode = VnPyTransportMode.SHADOW,
        allow_live: bool = False,
        backend_name: str | None = None,
        profile: VnPyGatewayProfile | None = None,
        naive_timezone: tzinfo = timezone.utc,
        register_events: bool = True,
        owns_main_engine: bool = False,
    ) -> None:
        gateway = gateway_name.strip()
        if not gateway:
            raise ValueError("gateway_name cannot be empty")
        if not isinstance(cast(object, mode), VnPyTransportMode):
            raise TypeError("mode must be VnPyTransportMode")
        if allow_live and mode is not VnPyTransportMode.LIVE:
            raise ValueError("allow_live is only valid in LIVE mode")
        timezone_probe = datetime(2000, 1, 1).replace(tzinfo=naive_timezone)
        if timezone_probe.utcoffset() is None:
            raise ValueError("naive_timezone must define a UTC offset")
        self._engine = cast(_MainEngine, main_engine)
        self._gateway_name = gateway
        self._mode = mode
        self._allow_live = allow_live
        self._backend_name = (
            backend_name.strip()
            if backend_name is not None
            else f"vnpy-{gateway.lower()}-{mode.value.lower()}"
        )
        if not self._backend_name:
            raise ValueError("backend_name cannot be empty")
        self._profile = profile or VnPyGatewayProfile()
        self._bindings: VnPyBindings = load_vnpy_bindings()
        self._mapper = VnPyValueMapper(
            self._bindings,
            gateway_name=self._gateway_name,
            backend_name=self._backend_name,
            profile=self._profile,
            naive_timezone=naive_timezone,
        )
        self._owns_main_engine = owns_main_engine
        self._registered = False
        self._closed = False
        self._lock = RLock()
        self._by_client: dict[str, TransportOrderReference] = {}
        self._by_order: dict[str, TransportOrderReference] = {}
        self._intent_created_at: dict[str, datetime] = {}
        self._order_events: list[OrderEvent] = []
        self._fills: list[Fill] = []
        self._unmatched_trades: list[VnPyTradeSnapshot] = []
        self._order_handler: _EventHandler = self._handle_order_event
        self._trade_handler: _EventHandler = self._handle_trade_event
        if register_events:
            self._engine.event_engine.register(self._bindings.event_order, self._order_handler)
            self._engine.event_engine.register(self._bindings.event_trade, self._trade_handler)
            self._registered = True

    def _ensure_open(self) -> None:
        if self._closed:
            raise ExecutionTransportError("vn.py transport is closed")

    def discover_capabilities(self) -> TransportCapabilities:
        self._ensure_open()
        mutation_allowed = self._mode is VnPyTransportMode.PAPER or (
            self._mode is VnPyTransportMode.LIVE and self._allow_live
        )
        notes = (
            f"mode={self._mode.value.lower()}",
            f"gateway={self._gateway_name}",
            f"live_gate={'allowed' if self._allow_live else 'blocked'}",
            "contract_source=vnpy-oms-cache",
            f"contract_count={self._mapper.contract_count(self._engine)}",
            "contract_required=true",
            "query=unsupported-oms-cache-is-not-broker-query",
            "tif=encoded-in-vnpy-order-type",
        )
        return TransportCapabilities(
            backend_name=self._backend_name,
            execution=self._profile.execution_capabilities(),
            supports_submit=mutation_allowed,
            supports_cancel=mutation_allowed,
            supports_query=False,
            supports_event_poll=True,
            supports_fill_poll=True,
            supports_client_order_lookup=False,
            notes=notes,
        )

    def _assert_mutation_allowed(self, operation: str) -> None:
        if self._mode is VnPyTransportMode.SHADOW:
            raise UnsupportedTransportCapabilityError(
                f"vn.py SHADOW mode forbids {operation} at runtime"
            )
        if self._mode is VnPyTransportMode.LIVE and not self._allow_live:
            raise UnsupportedTransportCapabilityError(
                f"vn.py LIVE mode requires explicit allow_live=True for {operation}"
            )

    def preview_order(
        self, intent: OrderIntent, *, reference: str | None = None
    ) -> VnPyOrderPreview:
        """Validate and preview mapping without constructing or sending an SDK DTO."""

        self._ensure_open()
        return self._mapper.preview_order(
            self._engine,
            self.discover_capabilities(),
            intent,
            reference=reference,
        )

    def submit(self, request: TransportSubmitRequest) -> TransportSubmission:
        self._ensure_open()
        self._assert_mutation_allowed("send_order")
        preview = self.preview_order(request.intent, reference=request.client_order_id)
        preliminary = TransportOrderReference(
            intent_id=request.intent.intent_id,
            instrument=request.intent.instrument,
            account_label=request.intent.account_label,
            client_order_id=request.client_order_id,
            side=request.intent.side,
            quantity=request.intent.quantity,
        )
        with self._lock:
            self._by_client[preview.reference] = preliminary
            self._intent_created_at[request.intent.intent_id] = request.intent.created_at
        vt_orderid = self._engine.send_order(
            self._mapper.order_request(preview),
            self._gateway_name,
        )
        if not vt_orderid.strip():
            raise TransportMappingError("vn.py send_order returned an empty order ID")
        reference = TransportOrderReference(
            intent_id=preliminary.intent_id,
            instrument=preliminary.instrument,
            account_label=preliminary.account_label,
            broker_order_id=vt_orderid,
            client_order_id=preliminary.client_order_id,
            side=preliminary.side,
            quantity=preliminary.quantity,
        )
        with self._lock:
            self._by_client[preview.reference] = reference
            self._by_order[vt_orderid] = reference
            self._reprocess_unmatched_trades()
        event = OrderEvent(
            event_id=_submit_event_id(
                self._gateway_name,
                vt_orderid,
                request.intent.intent_id,
            ),
            event_type=ExecutionEventType.ORDER_SUBMITTED,
            occurred_at=request.intent.created_at,
            instrument=request.intent.instrument,
            status=OrderStatus.PENDING,
            broker_name=self._backend_name,
            account_label=request.intent.account_label,
            broker_order_id=vt_orderid,
            intent_id=request.intent.intent_id,
            client_order_id=preview.reference,
            side=request.intent.side,
            quantity=request.intent.quantity,
            filled_quantity=Decimal("0"),
            remaining_quantity=request.intent.quantity,
            metadata={
                "source": "vnpy.send_order",
                "gateway_name": self._gateway_name,
                "mode": self._mode.value,
            },
        )
        return TransportSubmission(reference=reference, order_event=event)

    @staticmethod
    def _event_data(event: object) -> object:
        data: object = getattr(event, "data", None)
        if data is None:
            raise TransportMappingError("vn.py event has no data")
        return data

    def _handle_order_event(self, event: object) -> None:
        self.ingest_order_data(self._event_data(event))

    def _handle_trade_event(self, event: object) -> None:
        self.ingest_trade_data(self._event_data(event))

    def _reference_for_order(
        self,
        snapshot: VnPyOrderSnapshot,
    ) -> TransportOrderReference | None:
        reference = self._by_order.get(snapshot.vt_orderid)
        if reference is None and snapshot.reference:
            reference = self._by_client.get(snapshot.reference)
        if reference is None:
            return None
        resolved = TransportOrderReference(
            intent_id=reference.intent_id,
            instrument=reference.instrument,
            account_label=reference.account_label,
            broker_order_id=snapshot.vt_orderid,
            client_order_id=snapshot.reference or reference.client_order_id,
            side=reference.side,
            quantity=reference.quantity,
        )
        self._by_order[snapshot.vt_orderid] = resolved
        if resolved.client_order_id is not None:
            self._by_client[resolved.client_order_id] = resolved
        return resolved

    def _intent_time(self, intent_id: str) -> datetime:
        return self._intent_created_at.get(
            intent_id,
            datetime(1970, 1, 1, tzinfo=timezone.utc),
        )

    def ingest_order_data(self, value: object) -> None:
        """Normalize one real vn.py OrderData callback into the local queue."""

        self._ensure_open()
        snapshot = order_snapshot(self._bindings, value)
        if snapshot.gateway_name != self._gateway_name:
            return
        with self._lock:
            reference = self._reference_for_order(snapshot)
            if reference is None:
                return
            self._order_events.append(
                self._mapper.map_order(
                    snapshot,
                    reference,
                    fallback_time=self._intent_time(reference.intent_id),
                )
            )
            self._reprocess_unmatched_trades()

    def ingest_trade_data(self, value: object) -> None:
        """Normalize one real vn.py TradeData callback into the local queue."""

        self._ensure_open()
        snapshot = trade_snapshot(self._bindings, value)
        if snapshot.gateway_name != self._gateway_name:
            return
        with self._lock:
            reference = self._by_order.get(snapshot.vt_orderid)
            if reference is None:
                if snapshot not in self._unmatched_trades:
                    self._unmatched_trades.append(snapshot)
                return
            self._fills.append(
                self._mapper.map_trade(
                    snapshot,
                    reference,
                    fallback_time=self._intent_time(reference.intent_id),
                )
            )

    def _reprocess_unmatched_trades(self) -> None:
        remaining: list[VnPyTradeSnapshot] = []
        for snapshot in self._unmatched_trades:
            reference = self._by_order.get(snapshot.vt_orderid)
            if reference is None:
                remaining.append(snapshot)
                continue
            self._fills.append(
                self._mapper.map_trade(
                    snapshot,
                    reference,
                    fallback_time=self._intent_time(reference.intent_id),
                )
            )
        self._unmatched_trades = remaining

    def poll(self, reference: TransportOrderReference) -> TransportEventBatch:
        self._ensure_open()
        with self._lock:
            events = tuple(
                event for event in self._order_events if event.intent_id == reference.intent_id
            )
            fills = tuple(fill for fill in self._fills if fill.intent_id == reference.intent_id)
            self._order_events = [
                event for event in self._order_events if event.intent_id != reference.intent_id
            ]
            self._fills = [fill for fill in self._fills if fill.intent_id != reference.intent_id]
        return TransportEventBatch(reference=reference, order_events=events, fills=fills)

    def query(self, reference: TransportOrderReference) -> TransportEventBatch:
        self._ensure_open()
        raise UnsupportedTransportCapabilityError(
            "vn.py MainEngine/OMS is an in-memory callback cache, not a reliable broker query API"
        )

    def cancel(self, reference: TransportOrderReference) -> TransportCancellation:
        self._ensure_open()
        self._assert_mutation_allowed("cancel_order")
        request = self._mapper.cancel_request(self._engine, reference)
        self._engine.cancel_order(request, self._gateway_name)
        return TransportCancellation(reference=reference, accepted=True)

    def close(self) -> None:
        if self._closed:
            return
        if self._registered:
            self._engine.event_engine.unregister(self._bindings.event_order, self._order_handler)
            self._engine.event_engine.unregister(self._bindings.event_trade, self._trade_handler)
            self._registered = False
        if self._owns_main_engine:
            self._engine.close()
        self._closed = True


__all__ = [
    "VnPyExecutionTransport",
    "VnPyGatewayProfile",
    "VnPyImportError",
    "VnPyOrderPreview",
    "VnPyTransportMode",
]
