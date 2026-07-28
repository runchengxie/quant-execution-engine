"""LongPort broker implementation (public facade).

This module keeps the public surface that the rest of the codebase and the
test-suite import from ``quant_execution_engine.broker.longport``:

* SDK symbols (``Config``, ``Market``, ``OrderType``, ``OrderSide``,
  ``TimeInForceType``, ``QuoteContext``, ``TradeContext``) — re-exported so
  that ``monkeypatch``-ing them on this module (as the tests do) still affects
  :class:`LongPortClient` behaviour.
* The optional-SDK guard state (``_LONGPORT_SDK_SOURCE``,
  ``_LONGPORT_SDK_IMPORT_ERROR``) — re-exported so tests can monkeypatch it.
* :func:`get_config`, :class:`LongPortClient`, and the support re-exports
  (``getenv_both``, ``_to_lb_symbol``, ``BrokerLimits``).

The actual implementation lives in ``_longport_sdk`` / ``_longport_helpers`` /
``_longport_client``; this file is a thin, import-order-clean shell.
"""

from ._longport_client import LongPortClient
from ._longport_helpers import (
    _cash_snapshot_from_asset,
    _cash_usd_from_top_level_fields,
    _coerce_float,
    _coerce_int,
    _converted_cash_usd_from_totals,
    _default_broker_limits_from_env,
    _extended_hours_enabled,
    _field,
    _LazyContext,
    _make_longport_context_factory,
    _market_enum,
    _push_stock_position,
    _stock_position_map_from_response,
)
from ._longport_sdk import (
    _LONGPORT_SDK_IMPORT_ERROR,
    _LONGPORT_SDK_SOURCE,
    Config,
    Market,
    OrderSide,
    OrderType,
    QuoteContext,
    TimeInForceType,
    TradeContext,
    _ensure_longport_sdk_installed,
)
from .longport_support import (
    BrokerLimits,
    getenv_both,
)
from .longport_support import (
    market_of as _market_of,
)
from .longport_support import (
    market_tz as _market_tz,
)
from .longport_support import (
    to_lb_symbol as _to_lb_symbol,
)

__all__ = [
    "_LONGPORT_SDK_IMPORT_ERROR",
    "_LONGPORT_SDK_SOURCE",
    "BrokerLimits",
    "Config",
    "LongPortClient",
    "Market",
    "OrderSide",
    "OrderType",
    "QuoteContext",
    "TimeInForceType",
    "TradeContext",
    "_LazyContext",
    "_cash_snapshot_from_asset",
    "_cash_usd_from_top_level_fields",
    "_coerce_float",
    "_coerce_int",
    "_converted_cash_usd_from_totals",
    "_default_broker_limits_from_env",
    "_ensure_longport_sdk_installed",
    "_extended_hours_enabled",
    "_field",
    "_make_longport_context_factory",
    "_market_enum",
    "_market_of",
    "_market_tz",
    "_push_stock_position",
    "_stock_position_map_from_response",
    "_to_lb_symbol",
    "get_config",
    "getenv_both",
]


def get_config():
    """Return LongPort configuration based on environment variables.

    Compatible with direct calls in tests, equivalent to Config.from_env().
    """
    return Config.from_env()
