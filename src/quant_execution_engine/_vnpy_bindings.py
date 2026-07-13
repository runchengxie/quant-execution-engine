# pyright: strict
"""Lazy, leaf-only access to vn.py runtime types.

No module outside the vn.py adapter imports vn.py.  This module converts SDK
objects into immutable primitive snapshots before qexec domain mapping.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from importlib import import_module
from types import MappingProxyType, ModuleType
from typing import Protocol, cast


class VnPyImportError(RuntimeError):
    """Raised when the optional vn.py runtime is unavailable or incompatible."""


class _OrderRequestFactory(Protocol):
    def __call__(
        self,
        *,
        symbol: str,
        exchange: object,
        direction: object,
        type: object,
        volume: float,
        price: float,
        offset: object,
        reference: str,
    ) -> object: ...


class _CancelRequestFactory(Protocol):
    def __call__(
        self,
        *,
        orderid: str,
        symbol: str,
        exchange: object,
    ) -> object: ...


@dataclass(frozen=True, slots=True)
class VnPyBindings:
    """Validated constructors, enum members and event names from vn.py."""

    order_request_factory: _OrderRequestFactory
    cancel_request_factory: _CancelRequestFactory
    order_data_type: type[object]
    trade_data_type: type[object]
    contract_data_type: type[object]
    exchanges: Mapping[str, object]
    directions: Mapping[str, object]
    order_types: Mapping[str, object]
    offset_none: object
    event_order: str
    event_trade: str


@dataclass(frozen=True, slots=True)
class VnPyContractSnapshot:
    symbol: str
    exchange_name: str
    gateway_name: str
    product_name: str
    min_volume: float
    stop_supported: bool

    @property
    def vt_symbol(self) -> str:
        return f"{self.symbol}.{self.exchange_name}"


@dataclass(frozen=True, slots=True)
class VnPyOrderSnapshot:
    vt_orderid: str
    orderid: str
    symbol: str
    exchange_name: str
    gateway_name: str
    direction_name: str | None
    order_type_name: str
    volume: float
    traded: float
    price: float
    status_name: str
    occurred_at: datetime | None
    reference: str


@dataclass(frozen=True, slots=True)
class VnPyTradeSnapshot:
    vt_orderid: str
    vt_tradeid: str
    tradeid: str
    symbol: str
    exchange_name: str
    gateway_name: str
    direction_name: str | None
    volume: float
    price: float
    occurred_at: datetime | None


def _required_attribute(container: object, name: str) -> object:
    value: object = getattr(container, name, None)
    if value is None:
        raise VnPyImportError(f"vn.py runtime is missing required attribute {name!r}")
    return value


def _required_type(module: ModuleType, name: str) -> type[object]:
    value = _required_attribute(module, name)
    if not isinstance(value, type):
        raise VnPyImportError(f"vn.py attribute {name!r} is not a type")
    return value


def _enum_members(enum_type: object, enum_name: str) -> Mapping[str, object]:
    if not isinstance(enum_type, type):
        raise VnPyImportError(f"vn.py {enum_name} is not an enum type")
    try:
        values = tuple(cast(Iterable[object], enum_type))
    except TypeError as exc:
        raise VnPyImportError(f"vn.py {enum_name} is not iterable") from exc
    members: dict[str, object] = {}
    for value in values:
        name = enum_member_name(value)
        members[name] = value
    if not members:
        raise VnPyImportError(f"vn.py {enum_name} has no members")
    return MappingProxyType(members)


def load_vnpy_bindings() -> VnPyBindings:
    """Import and validate vn.py only when constructing its adapter."""

    try:
        constants = import_module("vnpy.trader.constant")
        objects = import_module("vnpy.trader.object")
        events = import_module("vnpy.trader.event")
    except ImportError as exc:
        raise VnPyImportError(
            "vn.py is not installed. Install this optional transport with: uv sync --extra vnpy"
        ) from exc

    exchanges = _enum_members(_required_attribute(constants, "Exchange"), "Exchange")
    directions = _enum_members(_required_attribute(constants, "Direction"), "Direction")
    order_types = _enum_members(_required_attribute(constants, "OrderType"), "OrderType")
    offsets = _enum_members(_required_attribute(constants, "Offset"), "Offset")
    offset_none = offsets.get("NONE")
    if offset_none is None:
        raise VnPyImportError("vn.py Offset.NONE is unavailable")
    event_order = _required_attribute(events, "EVENT_ORDER")
    event_trade = _required_attribute(events, "EVENT_TRADE")
    if not isinstance(event_order, str) or not isinstance(event_trade, str):
        raise VnPyImportError("vn.py order/trade event names must be strings")

    return VnPyBindings(
        order_request_factory=cast(
            _OrderRequestFactory,
            _required_type(objects, "OrderRequest"),
        ),
        cancel_request_factory=cast(
            _CancelRequestFactory,
            _required_type(objects, "CancelRequest"),
        ),
        order_data_type=_required_type(objects, "OrderData"),
        trade_data_type=_required_type(objects, "TradeData"),
        contract_data_type=_required_type(objects, "ContractData"),
        exchanges=exchanges,
        directions=directions,
        order_types=order_types,
        offset_none=offset_none,
        event_order=event_order,
        event_trade=event_trade,
    )


def enum_member_name(value: object) -> str:
    name: object = getattr(value, "name", None)
    if not isinstance(name, str) or not name:
        raise VnPyImportError("vn.py enum member has no stable name")
    return name


def _required_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise VnPyImportError(f"vn.py {field_name} must be a non-empty string")
    return value.strip()


def _optional_enum_name(value: object) -> str | None:
    if value is None:
        return None
    return enum_member_name(value)


def _number(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise VnPyImportError(f"vn.py {field_name} must be numeric")
    return float(value)


def _optional_datetime(value: object, field_name: str) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, datetime):
        raise VnPyImportError(f"vn.py {field_name} must be datetime or None")
    return value


def contract_snapshot(bindings: VnPyBindings, value: object) -> VnPyContractSnapshot:
    if not isinstance(value, bindings.contract_data_type):
        raise VnPyImportError("expected vn.py ContractData")
    return VnPyContractSnapshot(
        symbol=_required_string(getattr(value, "symbol", None), "contract.symbol"),
        exchange_name=enum_member_name(getattr(value, "exchange", None)),
        gateway_name=_required_string(
            getattr(value, "gateway_name", None),
            "contract.gateway_name",
        ),
        product_name=enum_member_name(getattr(value, "product", None)),
        min_volume=_number(getattr(value, "min_volume", None), "contract.min_volume"),
        stop_supported=bool(getattr(value, "stop_supported", False)),
    )


def order_snapshot(bindings: VnPyBindings, value: object) -> VnPyOrderSnapshot:
    if not isinstance(value, bindings.order_data_type):
        raise VnPyImportError("expected vn.py OrderData")
    return VnPyOrderSnapshot(
        vt_orderid=_required_string(getattr(value, "vt_orderid", None), "order.vt_orderid"),
        orderid=_required_string(getattr(value, "orderid", None), "order.orderid"),
        symbol=_required_string(getattr(value, "symbol", None), "order.symbol"),
        exchange_name=enum_member_name(getattr(value, "exchange", None)),
        gateway_name=_required_string(
            getattr(value, "gateway_name", None),
            "order.gateway_name",
        ),
        direction_name=_optional_enum_name(getattr(value, "direction", None)),
        order_type_name=enum_member_name(getattr(value, "type", None)),
        volume=_number(getattr(value, "volume", None), "order.volume"),
        traded=_number(getattr(value, "traded", None), "order.traded"),
        price=_number(getattr(value, "price", None), "order.price"),
        status_name=enum_member_name(getattr(value, "status", None)),
        occurred_at=_optional_datetime(getattr(value, "datetime", None), "order.datetime"),
        reference=str(getattr(value, "reference", "") or "").strip(),
    )


def trade_snapshot(bindings: VnPyBindings, value: object) -> VnPyTradeSnapshot:
    if not isinstance(value, bindings.trade_data_type):
        raise VnPyImportError("expected vn.py TradeData")
    return VnPyTradeSnapshot(
        vt_orderid=_required_string(getattr(value, "vt_orderid", None), "trade.vt_orderid"),
        vt_tradeid=_required_string(getattr(value, "vt_tradeid", None), "trade.vt_tradeid"),
        tradeid=_required_string(getattr(value, "tradeid", None), "trade.tradeid"),
        symbol=_required_string(getattr(value, "symbol", None), "trade.symbol"),
        exchange_name=enum_member_name(getattr(value, "exchange", None)),
        gateway_name=_required_string(
            getattr(value, "gateway_name", None),
            "trade.gateway_name",
        ),
        direction_name=_optional_enum_name(getattr(value, "direction", None)),
        volume=_number(getattr(value, "volume", None), "trade.volume"),
        price=_number(getattr(value, "price", None), "trade.price"),
        occurred_at=_optional_datetime(getattr(value, "datetime", None), "trade.datetime"),
    )


def make_order_request(
    bindings: VnPyBindings,
    *,
    symbol: str,
    exchange_name: str,
    direction_name: str,
    order_type_name: str,
    volume: float,
    price: float,
    reference: str,
) -> object:
    try:
        exchange = bindings.exchanges[exchange_name]
        direction = bindings.directions[direction_name]
        order_type = bindings.order_types[order_type_name]
    except KeyError as exc:
        raise VnPyImportError(f"vn.py enum mapping is unavailable: {exc.args[0]}") from exc
    return bindings.order_request_factory(
        symbol=symbol,
        exchange=exchange,
        direction=direction,
        type=order_type,
        volume=volume,
        price=price,
        offset=bindings.offset_none,
        reference=reference,
    )


def make_cancel_request(
    bindings: VnPyBindings,
    *,
    orderid: str,
    symbol: str,
    exchange_name: str,
) -> object:
    try:
        exchange = bindings.exchanges[exchange_name]
    except KeyError as exc:
        raise VnPyImportError(f"vn.py exchange mapping is unavailable: {exchange_name}") from exc
    return bindings.cancel_request_factory(
        orderid=orderid,
        symbol=symbol,
        exchange=exchange,
    )


__all__ = [
    "VnPyBindings",
    "VnPyContractSnapshot",
    "VnPyImportError",
    "VnPyOrderSnapshot",
    "VnPyTradeSnapshot",
    "contract_snapshot",
    "load_vnpy_bindings",
    "make_cancel_request",
    "make_order_request",
    "order_snapshot",
    "trade_snapshot",
]
