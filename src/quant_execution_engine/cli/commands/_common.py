"""Shared helpers for the execution-engine CLI command handlers."""

from __future__ import annotations

from ...execution import (
    DEFAULT_EXCEPTION_STATUSES,
    FAILURE_BROKER_STATUSES,
    OPEN_BROKER_STATUSES,
    SUCCESS_BROKER_STATUSES,
    TERMINAL_BROKER_STATUSES,
)

_BROKER_STATUS_GROUPS: dict[str, set[str]] = {
    "OPEN": set(OPEN_BROKER_STATUSES),
    "TERMINAL": set(TERMINAL_BROKER_STATUSES),
    "FAILURE": set(FAILURE_BROKER_STATUSES),
    "SUCCESS": set(SUCCESS_BROKER_STATUSES),
    "EXCEPTION": {
        "PARTIALLY_FILLED",
        "PENDING_CANCEL",
        "WAIT_TO_CANCEL",
        "REJECTED",
        "EXPIRED",
        "FAILED",
    },
}
_EXCEPTION_STATUS_GROUPS: dict[str, set[str]] = {
    "DEFAULT": set(DEFAULT_EXCEPTION_STATUSES),
    "ALL": set(DEFAULT_EXCEPTION_STATUSES),
    "OPEN": {"PARTIALLY_FILLED", "PENDING_CANCEL", "WAIT_TO_CANCEL"},
    "FAILURE": {"BLOCKED", "FAILED", "REJECTED", "EXPIRED"},
}


def _close_broker_adapter(adapter: object | None) -> None:
    close_fn = getattr(adapter, "close", None)
    if callable(close_fn):
        close_fn()


def _resolve_broker_status_filter(raw: str | None) -> set[str] | None:
    if raw is None:
        return None
    normalized = [part.strip().upper().replace("-", "_") for part in raw.split(",") if part.strip()]
    if not normalized:
        return None
    allowed: set[str] = set()
    for part in normalized:
        if part in {"ALL", "*"}:
            return None
        allowed.update(_BROKER_STATUS_GROUPS.get(part, {part}))
    return allowed


def _resolve_exception_status_filter(raw: str | None) -> set[str]:
    if raw is None:
        return set(DEFAULT_EXCEPTION_STATUSES)
    normalized = [part.strip().upper().replace("-", "_") for part in raw.split(",") if part.strip()]
    if not normalized:
        return set(DEFAULT_EXCEPTION_STATUSES)
    allowed: set[str] = set()
    for part in normalized:
        allowed.update(_EXCEPTION_STATUS_GROUPS.get(part, {part}))
    return allowed


def _resolve_symbol_filter(raw: str | None) -> set[str] | None:
    if raw is None:
        return None
    normalized = {part.strip().upper() for part in raw.split(",") if part.strip()}
    return normalized or None


def _resolve_identifier_filter(raw: str | None) -> set[str] | None:
    if raw is None:
        return None
    normalized = {part.strip() for part in raw.split(",") if part.strip()}
    return normalized or None


def _symbol_matches_filter(symbol: str, allowed: set[str] | None) -> bool:
    if allowed is None:
        return True
    normalized = str(symbol).strip().upper()
    base = normalized.rsplit(".", 1)[0] if "." in normalized else normalized
    return normalized in allowed or base in allowed


def _format_filter_summary(
    *,
    status_filter: str | None,
    symbol_filter: str | None,
    broker_order_id_filter: str | None = None,
) -> str:
    parts: list[str] = []
    if status_filter:
        parts.append(f"status={status_filter}")
    if symbol_filter:
        parts.append(f"symbol={symbol_filter}")
    if broker_order_id_filter:
        parts.append(f"order_id={broker_order_id_filter}")
    return ", ".join(parts) if parts else "none"
