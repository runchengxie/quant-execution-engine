# pyright: strict
"""Pure qexec/vn.py value mapping behind the optional transport."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone, tzinfo
from decimal import Decimal
from enum import Enum
from typing import Protocol

from ._vnpy_bindings import (
    VnPyBindings,
    VnPyContractSnapshot,
    VnPyOrderSnapshot,
    VnPyTradeSnapshot,
    contract_snapshot,
    make_cancel_request,
    make_order_request,
)
from .domain import (
    ExecutionCapabilities,
    ExecutionEventType,
    Fill,
    InstrumentId,
    OrderEvent,
    OrderIntent,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
    validate_order_intent_capabilities,
)
from .transport import (
    TransportCapabilities,
    TransportMappingError,
    TransportOrderReference,
    validate_transport_route,
)


class VnPyTransportMode(str, Enum):
    """Mutation modes exposed explicitly by the vn.py bridge."""

    SHADOW = "SHADOW"
    PAPER = "PAPER"
    LIVE = "LIVE"


def _default_order_types() -> frozenset[OrderType]:
    return frozenset({OrderType.MARKET, OrderType.LIMIT})


def _default_time_in_force() -> frozenset[TimeInForce]:
    return frozenset({TimeInForce.DAY, TimeInForce.IOC, TimeInForce.FOK})


def _default_products() -> frozenset[str]:
    return frozenset({"EQUITY", "ETF", "FUND"})


@dataclass(frozen=True, slots=True)
class VnPyGatewayProfile:
    """Capabilities deliberately asserted for one configured Gateway."""

    supports_short: bool = False
    supports_fractional: bool = False
    supported_order_types: frozenset[OrderType] = field(default_factory=_default_order_types)
    supported_time_in_force: frozenset[TimeInForce] = field(default_factory=_default_time_in_force)
    supported_products: frozenset[str] = field(default_factory=_default_products)

    def __post_init__(self) -> None:
        if not self.supported_order_types:
            raise ValueError("supported_order_types cannot be empty")
        if not self.supported_time_in_force:
            raise ValueError("supported_time_in_force cannot be empty")
        impossible_order_types = self.supported_order_types - {
            OrderType.MARKET,
            OrderType.LIMIT,
            OrderType.STOP,
        }
        if impossible_order_types:
            names = ", ".join(sorted(item.value for item in impossible_order_types))
            raise ValueError(f"vn.py common OrderRequest cannot map order types: {names}")
        impossible_tif = self.supported_time_in_force - {
            TimeInForce.DAY,
            TimeInForce.IOC,
            TimeInForce.FOK,
        }
        if impossible_tif:
            names = ", ".join(sorted(item.value for item in impossible_tif))
            raise ValueError(f"vn.py common OrderRequest cannot map time in force: {names}")
        products = frozenset(
            item.strip().upper() for item in self.supported_products if item.strip()
        )
        if not products:
            raise ValueError("supported_products cannot be empty")
        object.__setattr__(self, "supported_products", products)

    def execution_capabilities(self) -> ExecutionCapabilities:
        return ExecutionCapabilities(
            supports_short=self.supports_short,
            supports_fractional=self.supports_fractional,
            supported_order_types=self.supported_order_types,
            supported_time_in_force=self.supported_time_in_force,
        )


@dataclass(frozen=True, slots=True)
class VnPyOrderPreview:
    """Framework-neutral preview; the actual vn.py DTO stays inside the adapter."""

    symbol: str
    exchange: str
    direction: str
    order_type: str
    volume: Decimal
    price: Decimal
    reference: str
    gateway_name: str
    contract_product: str
    contract_min_volume: Decimal


class VnPyContractStore(Protocol):
    def get_contract(self, vt_symbol: str) -> object | None: ...

    def get_all_contracts(self) -> list[object]: ...


_EXCHANGE_ALIASES = {
    "SH": "SSE",
    "XSHG": "SSE",
    "SSE": "SSE",
    "SZ": "SZSE",
    "XSHE": "SZSE",
    "SZSE": "SZSE",
    "BJ": "BSE",
    "BSE": "BSE",
}

_STATUS_MAP: dict[str, tuple[OrderStatus, ExecutionEventType]] = {
    "SUBMITTING": (OrderStatus.PENDING, ExecutionEventType.ORDER_SUBMITTED),
    "NOTTRADED": (OrderStatus.ACCEPTED, ExecutionEventType.ORDER_ACKNOWLEDGED),
    "PARTTRADED": (OrderStatus.PARTIALLY_FILLED, ExecutionEventType.PARTIALLY_FILLED),
    "ALLTRADED": (OrderStatus.FILLED, ExecutionEventType.FILLED),
    "CANCELLED": (OrderStatus.CANCELLED, ExecutionEventType.CANCELLED),
    "REJECTED": (OrderStatus.REJECTED, ExecutionEventType.REJECTED),
}


def _stable_id(prefix: str, values: tuple[object, ...]) -> str:
    payload = json.dumps(values, ensure_ascii=True, separators=(",", ":"), default=str)
    digest = hashlib.sha256(payload.encode()).hexdigest()[:24]
    return f"{prefix}-{digest}"


class VnPyValueMapper:
    """Map values without owning Gateway, queue, journal, or policy state."""

    def __init__(
        self,
        bindings: VnPyBindings,
        *,
        gateway_name: str,
        backend_name: str,
        profile: VnPyGatewayProfile,
        naive_timezone: tzinfo,
    ) -> None:
        self.bindings = bindings
        self.gateway_name = gateway_name
        self.backend_name = backend_name
        self.profile = profile
        self.naive_timezone = naive_timezone

    def contract_count(self, store: VnPyContractStore) -> int:
        count = 0
        for raw in store.get_all_contracts():
            snapshot = contract_snapshot(self.bindings, raw)
            if snapshot.gateway_name == self.gateway_name:
                count += 1
        return count

    @staticmethod
    def _exchange_name(instrument: InstrumentId) -> str | None:
        if instrument.exchange is None:
            return None
        normalized = instrument.exchange.strip().upper()
        return _EXCHANGE_ALIASES.get(normalized, normalized)

    def resolve_contract(
        self,
        store: VnPyContractStore,
        instrument: InstrumentId,
    ) -> VnPyContractSnapshot:
        explicit_exchange = self._exchange_name(instrument)
        contract: VnPyContractSnapshot
        if explicit_exchange is not None:
            raw = store.get_contract(f"{instrument.symbol}.{explicit_exchange}")
            if raw is None:
                raise TransportMappingError(
                    f"vn.py OMS has no contract {instrument.symbol}.{explicit_exchange}"
                )
            contract = contract_snapshot(self.bindings, raw)
        else:
            candidates = [
                snapshot
                for raw in store.get_all_contracts()
                if (snapshot := contract_snapshot(self.bindings, raw)).symbol == instrument.symbol
                and snapshot.gateway_name == self.gateway_name
            ]
            if not candidates:
                raise TransportMappingError(
                    f"vn.py OMS has no contract for symbol {instrument.symbol!r}"
                )
            if len(candidates) > 1:
                raise TransportMappingError(
                    f"vn.py contract for {instrument.symbol!r} is ambiguous; set exchange"
                )
            contract = next(iter(candidates))
        if contract.gateway_name != self.gateway_name:
            raise TransportMappingError(
                f"contract belongs to gateway {contract.gateway_name!r}, not {self.gateway_name!r}"
            )
        if contract.product_name not in self.profile.supported_products:
            raise TransportMappingError(
                f"vn.py contract product {contract.product_name} is not enabled"
            )
        if contract.min_volume <= 0:
            raise TransportMappingError("vn.py contract min_volume must be positive")
        return contract

    @staticmethod
    def _vnpy_order_type(intent: OrderIntent, contract: VnPyContractSnapshot) -> str:
        if intent.time_in_force is TimeInForce.IOC:
            if intent.order_type is not OrderType.LIMIT:
                raise TransportMappingError("vn.py IOC mapping requires a LIMIT intent")
            return "FAK"
        if intent.time_in_force is TimeInForce.FOK:
            if intent.order_type is not OrderType.LIMIT:
                raise TransportMappingError("vn.py FOK mapping requires a LIMIT intent")
            return "FOK"
        if intent.time_in_force is not TimeInForce.DAY:
            raise TransportMappingError(
                f"vn.py common OrderRequest cannot represent TIF {intent.time_in_force.value}"
            )
        if intent.order_type is OrderType.STOP:
            if not contract.stop_supported:
                raise TransportMappingError("vn.py contract does not support STOP orders")
            return "STOP"
        mapped = {OrderType.MARKET: "MARKET", OrderType.LIMIT: "LIMIT"}.get(intent.order_type)
        if mapped is None:
            raise TransportMappingError(
                f"vn.py common OrderRequest cannot map order type {intent.order_type.value}"
            )
        return mapped

    @staticmethod
    def _price(intent: OrderIntent) -> Decimal:
        if intent.order_type is OrderType.LIMIT:
            if intent.limit_price is None:
                raise TransportMappingError("LIMIT intent is missing limit_price")
            return intent.limit_price
        if intent.order_type is OrderType.STOP:
            if intent.stop_price is None:
                raise TransportMappingError("STOP intent is missing stop_price")
            return intent.stop_price
        return Decimal("0")

    def preview_order(
        self,
        store: VnPyContractStore,
        capabilities: TransportCapabilities,
        intent: OrderIntent,
        *,
        reference: str | None = None,
    ) -> VnPyOrderPreview:
        validate_transport_route(intent, capabilities)
        validate_order_intent_capabilities(intent, capabilities.execution)
        contract = self.resolve_contract(store, intent.instrument)
        increment = Decimal(str(contract.min_volume))
        if intent.quantity % increment != 0:
            raise TransportMappingError(
                f"quantity {intent.quantity} does not align to contract min_volume {increment}"
            )
        return VnPyOrderPreview(
            symbol=contract.symbol,
            exchange=contract.exchange_name,
            direction="LONG" if intent.side is OrderSide.BUY else "SHORT",
            order_type=self._vnpy_order_type(intent, contract),
            volume=intent.quantity,
            price=self._price(intent),
            reference=(reference or intent.intent_id).strip(),
            gateway_name=self.gateway_name,
            contract_product=contract.product_name,
            contract_min_volume=increment,
        )

    def order_request(self, preview: VnPyOrderPreview) -> object:
        return make_order_request(
            self.bindings,
            symbol=preview.symbol,
            exchange_name=preview.exchange,
            direction_name=preview.direction,
            order_type_name=preview.order_type,
            volume=float(preview.volume),
            price=float(preview.price),
            reference=preview.reference,
        )

    def cancel_request(
        self,
        store: VnPyContractStore,
        reference: TransportOrderReference,
    ) -> object:
        if reference.broker_order_id is None:
            raise TransportMappingError("vn.py cancellation requires broker_order_id")
        contract = self.resolve_contract(store, reference.instrument)
        prefix = f"{self.gateway_name}."
        orderid = (
            reference.broker_order_id[len(prefix) :]
            if reference.broker_order_id.startswith(prefix)
            else reference.broker_order_id
        )
        return make_cancel_request(
            self.bindings,
            orderid=orderid,
            symbol=contract.symbol,
            exchange_name=contract.exchange_name,
        )

    def _aware_time(self, value: datetime | None, fallback: datetime) -> datetime:
        result = value or fallback
        if result.tzinfo is None or result.utcoffset() is None:
            result = result.replace(tzinfo=self.naive_timezone)
        return result.astimezone(timezone.utc)

    @staticmethod
    def _side(direction_name: str | None, fallback: OrderSide | None) -> OrderSide | None:
        return {"LONG": OrderSide.BUY, "SHORT": OrderSide.SELL}.get(
            direction_name or "",
            fallback,
        )

    def map_order(
        self,
        snapshot: VnPyOrderSnapshot,
        reference: TransportOrderReference,
        *,
        fallback_time: datetime,
    ) -> OrderEvent:
        if snapshot.gateway_name != self.gateway_name:
            raise TransportMappingError("vn.py order callback came from another gateway")
        if snapshot.symbol != reference.instrument.symbol:
            raise TransportMappingError("vn.py order symbol does not match tracked intent")
        status, event_type = _STATUS_MAP.get(
            snapshot.status_name,
            (OrderStatus.UNKNOWN, ExecutionEventType.ORDER_UPDATED),
        )
        quantity = reference.quantity or Decimal(str(snapshot.volume))
        filled = Decimal(str(snapshot.traded))
        remaining = max(Decimal("0"), quantity - filled)
        event_id = _stable_id(
            "vnpy-order-event",
            (
                snapshot.gateway_name,
                snapshot.vt_orderid,
                snapshot.status_name,
                snapshot.volume,
                snapshot.traded,
                snapshot.price,
                snapshot.occurred_at,
                snapshot.reference,
            ),
        )
        return OrderEvent(
            event_id=event_id,
            event_type=event_type,
            occurred_at=self._aware_time(snapshot.occurred_at, fallback_time),
            instrument=reference.instrument,
            status=status,
            broker_name=self.backend_name,
            account_label=reference.account_label,
            broker_order_id=snapshot.vt_orderid,
            intent_id=reference.intent_id,
            client_order_id=snapshot.reference or reference.client_order_id,
            side=self._side(snapshot.direction_name, reference.side),
            quantity=quantity,
            filled_quantity=filled,
            remaining_quantity=remaining,
            metadata={
                "source": "vnpy.OrderData",
                "gateway_name": snapshot.gateway_name,
                "vnpy_status": snapshot.status_name,
                "vnpy_order_type": snapshot.order_type_name,
                "timestamp_source": (
                    "OrderData.datetime"
                    if snapshot.occurred_at is not None
                    else "intent.created_at"
                ),
            },
        )

    def map_trade(
        self,
        snapshot: VnPyTradeSnapshot,
        reference: TransportOrderReference,
        *,
        fallback_time: datetime,
    ) -> Fill:
        if snapshot.gateway_name != self.gateway_name:
            raise TransportMappingError("vn.py trade callback came from another gateway")
        if snapshot.symbol != reference.instrument.symbol:
            raise TransportMappingError("vn.py trade symbol does not match tracked intent")
        return Fill(
            fill_id=f"vnpy-trade:{snapshot.vt_tradeid}",
            broker_order_id=snapshot.vt_orderid,
            instrument=reference.instrument,
            quantity=Decimal(str(snapshot.volume)),
            price=Decimal(str(snapshot.price)),
            filled_at=self._aware_time(snapshot.occurred_at, fallback_time),
            broker_name=self.backend_name,
            account_label=reference.account_label,
            intent_id=reference.intent_id,
            side=self._side(snapshot.direction_name, reference.side),
            metadata={
                "source": "vnpy.TradeData",
                "gateway_name": snapshot.gateway_name,
                "timestamp_source": (
                    "TradeData.datetime"
                    if snapshot.occurred_at is not None
                    else "intent.created_at"
                ),
            },
        )


__all__ = [
    "VnPyContractStore",
    "VnPyGatewayProfile",
    "VnPyOrderPreview",
    "VnPyTransportMode",
    "VnPyValueMapper",
]
