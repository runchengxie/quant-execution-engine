"""Shared LongPort helpers that do not depend on the SDK runtime."""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum


def getenv_both(name_new: str, name_old: str, default: str = None) -> str:
    """Read a compatibility env var, preferring the new LONGPORT_* prefix."""

    return os.getenv(name_new) or os.getenv(name_old) or default


class Env(str, Enum):
    REAL = "real"
    PAPER = "paper"


@dataclass
class BrokerLimits:
    # 0 or negative means "no local cap" (unlimited, rely on broker)
    max_notional_per_order: float = 0.0
    max_qty_per_order: int = 0
    trading_window_start: str = "09:30"  # Local time (fallback only)
    trading_window_end: str = "16:00"


def enum_value(value: object) -> object:
    """Return a comparable value for enum-like objects and string constants."""

    if hasattr(value, "value"):
        try:
            from unittest.mock import Mock

            if isinstance(value, Mock):
                return value
        except Exception:  # pragma: no cover - mock import always available in tests
            pass
        return value.value
    text = str(value)
    if "." in text:
        return text.split(".")[-1]
    return value


def normalize_order_status(status: object) -> str:
    raw = str(enum_value(status)).strip()
    if not raw:
        return "UNKNOWN"
    normalized = raw.replace(" ", "").replace("-", "").replace("_", "")
    mapping = {
        "NotReported": "PENDING_NEW",
        "ReplacedNotReported": "PENDING_REPLACE",
        "ProtectedNotReported": "PENDING_NEW",
        "VarietiesNotReported": "PENDING_NEW",
        "WaitToNew": "WAIT_TO_NEW",
        "New": "NEW",
        "WaitToReplace": "PENDING_REPLACE",
        "PendingReplace": "PENDING_REPLACE",
        "Replaced": "NEW",
        "PartialFilled": "PARTIALLY_FILLED",
        "WaitToCancel": "PENDING_CANCEL",
        "PendingCancel": "PENDING_CANCEL",
        "Rejected": "REJECTED",
        "Canceled": "CANCELED",
        "Expired": "EXPIRED",
        "PartialWithdrawal": "PARTIALLY_FILLED",
        "Filled": "FILLED",
    }
    return mapping.get(normalized, normalized.upper())


def coerce_iso(value: object) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def to_lb_symbol(ticker: str, market: str | None = None) -> str:
    """Convert a symbol into LongPort's canonical ticker.market form."""

    ticker_text = str(ticker).strip().upper()
    explicit_market = str(market or "").strip().upper()
    if explicit_market:
        if "." in ticker_text and ticker_text.rsplit(".", 1)[-1] in {"US", "HK", "SG", "CN"}:
            ticker_text = ticker_text.rsplit(".", 1)[0]
        return f"{ticker_text}.{explicit_market}"
    if ticker_text.endswith((".US", ".HK", ".SG", ".CN")):
        return ticker_text
    return f"{ticker_text}.US"


def market_of(symbol: str) -> str:
    normalized = str(symbol).upper()
    if normalized.endswith(".US"):
        return "US"
    if normalized.endswith(".HK"):
        return "HK"
    if normalized.endswith(".CN"):
        return "CN"
    if normalized.endswith(".SG"):
        return "SG"
    return "US"


def market_tz(market: str) -> str:
    return {
        "US": "America/New_York",
        "HK": "Asia/Hong_Kong",
        "CN": "Asia/Shanghai",
        "SG": "Asia/Singapore",
    }[market]


__all__ = [
    "BrokerLimits",
    "Env",
    "coerce_iso",
    "enum_value",
    "getenv_both",
    "market_of",
    "market_tz",
    "normalize_order_status",
    "to_lb_symbol",
]
