"""LongPort SDK dynamic import and optional-dependency guard.

The LongPort SDK is an optional dependency. We prefer ``longport``, fall back
to the older ``longbridge`` package, then to in-tree stubs so that the rest of
the package can be imported (and type-checked) without the extra installed.

The module-level state ``_LONGPORT_SDK_SOURCE`` / ``_LONGPORT_SDK_IMPORT_ERROR``
is *re-exported* by ``broker/longport.py`` so that tests can monkeypatch it on
the ``longport`` module; ``_ensure_longport_sdk_installed`` therefore reads the
value from the ``longport`` module rather than this one.
"""

# Deprecated compatibility: prefer longport, fall back to longbridge, then stubs.
try:  # pragma: no cover - depends on external package
    from longport.openapi import (
        Config,
        Market,
        OrderSide,
        OrderType,
        QuoteContext,
        TimeInForceType,
        TradeContext,
    )

    _LONGPORT_SDK_SOURCE = "longport"
    _LONGPORT_SDK_IMPORT_ERROR: ImportError | None = None
except ImportError as exc:  # pragma: no cover - executed when longport not available
    _LONGPORT_SDK_IMPORT_ERROR = exc
    try:  # pragma: no cover - depends on optional package
        from longbridge.openapi import (
            Config,
            Market,
            OrderSide,
            OrderType,
            QuoteContext,
            TimeInForceType,
            TradeContext,
        )

        _LONGPORT_SDK_SOURCE = "longbridge"
        _LONGPORT_SDK_IMPORT_ERROR = None
    except ImportError as fallback_exc:  # pragma: no cover - executed when neither SDK installed
        _LONGPORT_SDK_IMPORT_ERROR = fallback_exc
        from ._stubs import (
            Config,
            Market,
            OrderSide,
            OrderType,
            QuoteContext,
            TimeInForceType,
            TradeContext,
        )

        _LONGPORT_SDK_SOURCE = "stub"

from .base import BrokerImportError


def _ensure_longport_sdk_installed() -> None:
    """Raise a clear optional-dependency error when the SDK is unavailable.

    Reads the SDK state from the ``longport`` module so that tests which
    monkeypatch ``quant_execution_engine.broker.longport._LONGPORT_SDK_SOURCE``
    are honoured.
    """

    import quant_execution_engine.broker.longport as _lp_mod

    if _lp_mod._LONGPORT_SDK_SOURCE != "stub":
        return
    missing = getattr(_lp_mod._LONGPORT_SDK_IMPORT_ERROR, "name", None)
    if missing and missing not in {
        "longport",
        "longport.openapi",
        "longbridge",
        "longbridge.openapi",
    }:
        raise BrokerImportError(
            "longport import failed because dependency "
            f"'{missing}' is missing. Install/update it with: uv sync --extra longport"
        ) from _lp_mod._LONGPORT_SDK_IMPORT_ERROR
    raise BrokerImportError(
        "longport SDK is not installed. Install it with: uv sync --extra longport"
    ) from _lp_mod._LONGPORT_SDK_IMPORT_ERROR


__all__ = [
    "_LONGPORT_SDK_IMPORT_ERROR",
    "_LONGPORT_SDK_SOURCE",
    "Config",
    "Market",
    "OrderSide",
    "OrderType",
    "QuoteContext",
    "TimeInForceType",
    "TradeContext",
    "_ensure_longport_sdk_installed",
]
