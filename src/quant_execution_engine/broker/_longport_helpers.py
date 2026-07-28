"""Private helper functions for the LongPort broker implementation.

These are pure, side-effect-light helpers that were previously defined at
module scope in ``broker/longport.py``. They are grouped here to keep the
public module small; the ``longport`` module re-exports the ones that external
callers rely on.
"""

import os
from typing import Any, cast

from ..fx import to_usd
from ..logging import get_logger
from ._longport_sdk import (
    Config,
    Market,
    QuoteContext,
    TradeContext,
)
from .longport_credentials import resolve_longport_runtime_value
from .longport_support import (
    BrokerLimits,
    getenv_both,
)

logger = get_logger(__name__)


def _market_enum(m: str) -> Market:
    return {
        "US": Market.US,
        "HK": Market.HK,
        "CN": Market.CN,
        "SG": Market.SG,
    }[m]


def _coerce_float(value: str | None, default: float = 0.0) -> float:
    try:
        return float(str(value)) if value is not None else default
    except Exception:
        return default


def _coerce_int(value: str | None, default: int = 0) -> int:
    try:
        return int(float(str(value))) if value is not None else default
    except Exception:
        return default


def _default_broker_limits_from_env() -> BrokerLimits:
    # LONGBRIDGE_* limit names are deprecated compatibility fallbacks.
    max_notional_env = getenv_both(
        "LONGPORT_MAX_NOTIONAL_PER_ORDER",
        "LONGBRIDGE_MAX_NOTIONAL_PER_ORDER",
        "0",
    )
    max_qty_env = getenv_both(
        "LONGPORT_MAX_QTY_PER_ORDER",
        "LONGBRIDGE_MAX_QTY_PER_ORDER",
        "0",
    )
    tw_start = getenv_both(
        "LONGPORT_TRADING_WINDOW_START",
        "LONGBRIDGE_TRADING_WINDOW_START",
        "09:30",
    )
    tw_end = getenv_both(
        "LONGPORT_TRADING_WINDOW_END",
        "LONGBRIDGE_TRADING_WINDOW_END",
        "16:00",
    )
    return BrokerLimits(
        max_notional_per_order=_coerce_float(max_notional_env, 0.0),
        max_qty_per_order=_coerce_int(max_qty_env, 0),
        trading_window_start=str(tw_start or "09:30"),
        trading_window_end=str(tw_end or "16:00"),
    )


def _extended_hours_enabled(env_name: str) -> bool:
    # LONGBRIDGE_ENABLE_OVERNIGHT is a deprecated compatibility fallback.
    enable_overnight, _overnight_source = resolve_longport_runtime_value(
        ("LONGPORT_ENABLE_OVERNIGHT", "LONGBRIDGE_ENABLE_OVERNIGHT"),
        env_name=env_name,
        default="false",
    )
    return str(enable_overnight).strip().lower() in {"1", "true", "yes", "y"}


class _LazyContext:
    def __init__(self, factory):
        self._factory = factory
        self._ctx = None

    def _ensure(self):
        if self._ctx is None:
            self._ctx = self._factory()
        return self._ctx

    def __getattr__(self, name):
        return getattr(self._ensure(), name)


def _make_longport_context_factory(region: str | None, kind: str):
    def _factory():
        tried: list[str] = []
        for rg in [region, "us", "hk", "sg"]:
            if not rg or rg in tried:
                continue
            tried.append(rg)
            os.environ["LONGPORT_REGION"] = rg
            try:
                cfg = cast(Any, Config.from_env())
                return QuoteContext(cfg) if kind == "quote" else TradeContext(cfg)
            except Exception as e:  # Defer raising until all options tried
                msg = str(e).lower()
                if "timeout" in msg or "connect" in msg or "dns" in msg:
                    continue
                raise
        raise RuntimeError("无法初始化 LongPort 上下文：network/region configuration error")

    return _factory


def _field(item: object, name: str, default=None):
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _cash_snapshot_from_asset(
    asset: object,
) -> tuple[float, float | None, str | None]:
    assets_seq = asset if isinstance(asset, (list, tuple)) else [asset]
    totals: dict[str, float] = {}
    picked_net_assets: float | None = None
    picked_base_ccy: str | None = None

    for account_balance in assets_seq:
        ci_list = (
            _field(account_balance, "cash_infos") or _field(account_balance, "cash_info") or []
        )
        for ci in ci_list:
            ccy = str(_field(ci, "currency", "") or _field(ci, "ccy", "")).upper()
            raw_amt = (
                _field(ci, "available_cash")
                or _field(ci, "cash")
                or _field(ci, "withdraw_cash", 0.0)
            )
            try:
                amt = float(raw_amt or 0.0)
            except Exception:
                amt = 0.0
            if not ccy:
                continue
            totals[ccy] = totals.get(ccy, 0.0) + amt

        if picked_net_assets is None:
            net_assets = _field(account_balance, "net_assets")
            if net_assets is not None:
                try:
                    picked_net_assets = float(net_assets)
                except Exception:
                    picked_net_assets = None
        if picked_base_ccy is None:
            picked_base_ccy = (
                str(
                    _field(account_balance, "currency", "")
                    or _field(account_balance, "base_currency", "")
                ).upper()
                or None
            )

    if totals:
        logger.debug("现金分币种: " + ", ".join(f"{k}={v:.2f}" for k, v in totals.items()))

    cash_usd = totals.get("USD", 0.0)
    if cash_usd == 0.0:
        cash_usd = _converted_cash_usd_from_totals(totals)
    if cash_usd == 0.0:
        cash_usd = _cash_usd_from_top_level_fields(asset, picked_base_ccy)
    if cash_usd == 0.0 and totals and any(k != "USD" for k in totals):
        logger.debug("未找到USD现金，检测到非USD余额；如需折算，请配置FX或启用USD子账户。")

    return cash_usd, picked_net_assets, picked_base_ccy


def _converted_cash_usd_from_totals(totals: dict[str, float]) -> float:
    if not totals:
        return 0.0
    total_conv = 0.0
    any_conv = False
    for ccy, amt in totals.items():
        if ccy == "USD":
            continue
        conv = to_usd(amt, ccy)
        if conv is not None:
            total_conv += float(conv)
            any_conv = True
    if any_conv:
        logger.debug(f"按汇率折算非USD现金合计: {total_conv:.2f} USD")
        return total_conv
    return 0.0


def _cash_usd_from_top_level_fields(asset: object, base_ccy: str | None) -> float:
    for name in ("available_cash", "cash", "withdraw_cash", "total_cash"):
        value = _field(asset, name)
        if value is None:
            continue
        try:
            raw = float(value)
        except Exception:
            continue
        if raw == 0.0:
            continue
        base = (base_ccy or "").upper() if base_ccy else None
        if base and base != "USD":
            converted = to_usd(raw, base)
            if converted is not None:
                cash_usd = float(converted)
                logger.debug(f"使用{base}字段{name}={raw:.2f}折算USD={cash_usd:.2f}")
                return cash_usd
        elif base == "USD":
            logger.debug(f"使用USD字段{name}={raw:.2f}")
            return raw
    return 0.0


def _push_stock_position(
    pos_map: dict[str, int],
    symbol: object,
    quantity: object,
    market: object | None = None,
) -> None:
    if symbol is None or quantity is None:
        return
    try:
        qty = int(float(str(quantity)))
    except Exception:
        return
    normalized_symbol = str(symbol).upper()
    if "." not in normalized_symbol and market:
        normalized_symbol = f"{normalized_symbol}.{str(market).upper()}"
    pos_map[normalized_symbol] = pos_map.get(normalized_symbol, 0) + qty


def _stock_position_map_from_response(response: object) -> dict[str, int]:
    groups = _field(response, "list") or _field(response, "channels")
    if groups is None:
        groups = response

    pos_map: dict[str, int] = {}
    if not isinstance(groups, list):
        return pos_map
    for group in groups:
        stock_info = _field(group, "stock_info")
        if stock_info is not None:
            for item in stock_info:
                _push_stock_position(
                    pos_map,
                    _field(item, "symbol"),
                    _field(item, "quantity"),
                    _field(item, "market"),
                )
            continue

        positions = _field(group, "positions")
        if positions is not None:
            for item in positions:
                _push_stock_position(
                    pos_map,
                    _field(item, "symbol"),
                    _field(item, "quantity"),
                    _field(item, "market"),
                )
            continue

        _push_stock_position(
            pos_map,
            _field(group, "symbol"),
            _field(group, "quantity"),
            _field(group, "market"),
        )
    return pos_map


__all__ = [
    "_LazyContext",
    "_cash_snapshot_from_asset",
    "_cash_usd_from_top_level_fields",
    "_coerce_float",
    "_coerce_int",
    "_converted_cash_usd_from_totals",
    "_default_broker_limits_from_env",
    "_extended_hours_enabled",
    "_field",
    "_make_longport_context_factory",
    "_market_enum",
    "_push_stock_position",
    "_stock_position_map_from_response",
]
