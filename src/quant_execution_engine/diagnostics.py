"""Operator-facing broker diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class BrokerDiagnostic:
    """Normalized operator-facing diagnostic."""

    severity: str
    code: str
    summary: str
    action_hint: str | None = None


@dataclass(slots=True)
class _MessageDiagnosticTemplate:
    code: str
    summary: str
    action_hint: str


_REJECTION_TEMPLATES: tuple[tuple[tuple[str, ...], _MessageDiagnosticTemplate], ...] = (
    (
        (
            "insufficient funds",
            "insufficient cash",
            "insufficient buying power",
            "buying power",
            "margin",
            "not enough cash",
        ),
        _MessageDiagnosticTemplate(
            code="BROKER_REJECTED_FUNDS",
            summary="broker rejected the order because account buying power/cash was insufficient",
            action_hint="Reduce order size, free cash or buying power, then retry.",
        ),
    ),
    (
        (
            "market is closed",
            "outside market hours",
            "outside regular trading hours",
            "trading session",
            "overnight",
            "after hours",
            "before hours",
            "done_for_day",
        ),
        _MessageDiagnosticTemplate(
            code="BROKER_REJECTED_SESSION",
            summary="broker rejected the order because the requested trading session is unavailable",
            action_hint="Review market session, overnight/extended-hours flags, and time-in-force before retrying.",
        ),
    ),
    (
        (
            "invalid symbol",
            "unknown symbol",
            "symbol not found",
            "instrument not found",
            "not tradable",
            "delisted",
            "halted",
        ),
        _MessageDiagnosticTemplate(
            code="BROKER_REJECTED_SYMBOL",
            summary="broker rejected the order because the symbol or instrument is not tradable",
            action_hint="Confirm symbol mapping, market suffix, and broker tradability before retrying.",
        ),
    ),
    (
        (
            "lot size",
            "board lot",
            "minimum quantity",
            "min qty",
            "tick size",
            "price increment",
            "invalid limit price",
            "invalid quantity",
            "fractional",
        ),
        _MessageDiagnosticTemplate(
            code="BROKER_REJECTED_SIZE_OR_PRICE",
            summary="broker rejected the order because quantity, lot size, or price rules were violated",
            action_hint="Adjust quantity/price to the broker's lot-size and price-increment rules, then retry.",
        ),
    ),
    (
        (
            "permission",
            "not allowed",
            "trading disabled",
            "account restricted",
            "region",
            "compliance",
            "forbidden",
            "unauthorized",
        ),
        _MessageDiagnosticTemplate(
            code="BROKER_REJECTED_PERMISSION",
            summary="broker rejected the order because the account or region is not permitted to place it",
            action_hint="Check account permissions, region/session settings, and broker-side restrictions before retrying.",
        ),
    ),
    (
        (
            "short",
            "locate",
            "borrow",
            "easy to borrow",
        ),
        _MessageDiagnosticTemplate(
            code="BROKER_REJECTED_SHORT_LOCATE",
            summary="broker rejected the order because short inventory or locate requirements were not satisfied",
            action_hint="Confirm short-selling eligibility or switch to a non-short order before retrying.",
        ),
    ),
)

_GENERIC_WARNING_TEMPLATES: tuple[tuple[tuple[str, ...], _MessageDiagnosticTemplate], ...] = (
    (
        (
            "timed out",
            "timeout",
            "temporarily unavailable",
            "connection reset",
            "connection refused",
            "network",
            "dns",
            "socket",
            "tls",
            "ssl",
            "host unreachable",
        ),
        _MessageDiagnosticTemplate(
            code="BROKER_NETWORK_WARNING",
            summary="broker/API communication failed because of a network or transient connectivity issue",
            action_hint="Retry after confirming network reachability and broker/API health.",
        ),
    ),
    (
        (
            "rate limit",
            "too many requests",
            "429",
        ),
        _MessageDiagnosticTemplate(
            code="BROKER_RATE_LIMIT_WARNING",
            summary="broker/API warning indicates a rate limit or throttling condition",
            action_hint="Back off and retry later, or reduce request frequency.",
        ),
    ),
    (
        (
            "permission",
            "credential",
            "entitlement",
            "region",
            "unauthorized",
            "forbidden",
            "401",
            "403",
        ),
        _MessageDiagnosticTemplate(
            code="BROKER_CONFIGURATION_WARNING",
            summary="broker/API warning indicates a credential, permission, or regional configuration issue",
            action_hint="Verify credentials, region, and market-data/account entitlements before retrying.",
        ),
    ),
)


def _extract_raw_code(raw: dict[str, Any] | None) -> str | None:
    if not raw:
        return None
    for key in ("reject_code", "error_code", "code", "status_code"):
        value = raw.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def _message_parts(message: str | None, raw_code: str | None, raw: dict[str, Any] | None) -> list[str]:
    parts: list[str] = []
    for value in (
        message,
        raw_code,
        raw.get("reason") if raw else None,
        raw.get("reject_reason") if raw else None,
        raw.get("detail") if raw else None,
        raw.get("error") if raw else None,
        raw.get("message") if raw else None,
        raw.get("msg") if raw else None,
    ):
        text = str(value or "").strip()
        if text and text not in parts:
            parts.append(text)
    return parts


def _diagnostic_from_templates(
    text: str,
    templates: tuple[tuple[tuple[str, ...], _MessageDiagnosticTemplate], ...],
    *,
    severity: str,
    preferred_summary: str | None,
) -> BrokerDiagnostic | None:
    lowered = str(text or "").strip().lower()
    if not lowered:
        return None
    for keywords, template in templates:
        if any(keyword in lowered for keyword in keywords):
            return BrokerDiagnostic(
                severity=severity,
                code=template.code,
                summary=preferred_summary or template.summary,
                action_hint=template.action_hint,
            )
    return None


def diagnose_order_issue(record: Any) -> BrokerDiagnostic | None:
    """Return a normalized diagnostic for a broker/local order record."""

    if record is None:
        return None
    status = str(getattr(record, "status", "") or "").strip().upper()
    if not status:
        return None
    message = str(getattr(record, "message", "") or "").strip() or None
    raw = getattr(record, "raw", None)
    filled_quantity = float(getattr(record, "filled_quantity", 0.0) or 0.0)
    remaining_quantity = getattr(record, "remaining_quantity", None)
    remaining = None if remaining_quantity is None else float(remaining_quantity)
    raw_code = _extract_raw_code(raw if isinstance(raw, dict) else None)
    raw_parts = _message_parts(message, raw_code, raw if isinstance(raw, dict) else None)
    classification_text = " | ".join(raw_parts)

    if status == "BLOCKED":
        return BrokerDiagnostic(
            severity="ERROR",
            code=raw_code or "RISK_BLOCKED",
            summary=message or "execution risk gate blocked submission",
            action_hint="Adjust size, price, spread/impact thresholds, or clear the kill switch before retrying.",
        )
    if status == "FAILED":
        return BrokerDiagnostic(
            severity="ERROR",
            code=raw_code or "SUBMIT_FAILED",
            summary=message or "broker submission failed before an accepted order state was recorded",
            action_hint="Run reconcile to confirm broker state, then fix the submit error before retrying.",
        )
    if status == "REJECTED":
        rejection = _diagnostic_from_templates(
            classification_text,
            _REJECTION_TEMPLATES,
            severity="ERROR",
            preferred_summary=message,
        )
        if rejection is not None:
            return rejection
        return BrokerDiagnostic(
            severity="ERROR",
            code=raw_code or "BROKER_REJECTED",
            summary=message or "broker rejected the order",
            action_hint="Inspect broker message/raw payload, correct the order parameters, then retry.",
        )
    if status == "EXPIRED":
        return BrokerDiagnostic(
            severity="WARNING",
            code=raw_code or "ORDER_EXPIRED",
            summary=message or "broker expired the order",
            action_hint="Review session/time-in-force constraints before retrying.",
        )
    if status in {"PENDING_CANCEL", "WAIT_TO_CANCEL"}:
        return BrokerDiagnostic(
            severity="WARNING",
            code=raw_code or "CANCEL_PENDING",
            summary=message or "cancel request is pending at the broker",
            action_hint="Wait for broker acknowledgement or run reconcile before retrying/repricing.",
        )
    if status == "PARTIALLY_FILLED":
        return BrokerDiagnostic(
            severity="WARNING",
            code=raw_code or "PARTIAL_FILL",
            summary=message or "order is partially filled and still requires operator action",
            action_hint="Use cancel-rest, resume-remaining, or accept-partial depending on the remaining intent.",
        )
    if status == "CANCELED" and filled_quantity > 0 and (remaining is None or remaining > 0):
        return BrokerDiagnostic(
            severity="WARNING",
            code=raw_code or "PARTIAL_REMAINDER_CANCELED",
            summary=message or "remaining quantity was canceled after a partial fill",
            action_hint="Use resume-remaining to continue the order, or accept-partial to close it locally.",
        )
    return None


def diagnose_warning_message(message: str) -> BrokerDiagnostic:
    """Normalize free-form reconcile/cancel warnings."""

    text = str(message or "").strip()
    lowered = text.lower()
    if lowered.startswith("failed to refresh tracked order"):
        return BrokerDiagnostic(
            severity="WARNING",
            code="ORDER_REFRESH_FAILED",
            summary=text,
            action_hint="Retry reconcile or inspect the broker directly if the order state stays stale.",
        )
    if lowered.startswith("failed to load fills for tracked order"):
        return BrokerDiagnostic(
            severity="WARNING",
            code="FILL_LOOKUP_FAILED",
            summary=text,
            action_hint="Run reconcile again later; late fills may still be recoverable.",
        )
    if lowered.startswith("cancel submitted but post-cancel refresh failed"):
        return BrokerDiagnostic(
            severity="WARNING",
            code="POST_CANCEL_REFRESH_FAILED",
            summary=text,
            action_hint="Run reconcile before taking further action on the order.",
        )
    if lowered.startswith("order already in terminal state"):
        return BrokerDiagnostic(
            severity="INFO",
            code="ALREADY_TERMINAL",
            summary=text,
            action_hint="No broker mutation is required; inspect tracked order detail if needed.",
        )
    if "skipped stale retry" in lowered:
        return BrokerDiagnostic(
            severity="INFO",
            code="STALE_RETRY_SKIPPED",
            summary=text,
            action_hint="Inspect the tracked order timestamps/status before retrying manually.",
        )
    heuristic = _diagnostic_from_templates(
        text,
        _GENERIC_WARNING_TEMPLATES,
        severity="WARNING",
        preferred_summary=text,
    )
    if heuristic is not None:
        return heuristic
    return BrokerDiagnostic(
        severity="WARNING",
        code="BROKER_WARNING",
        summary=text,
        action_hint=None,
    )
