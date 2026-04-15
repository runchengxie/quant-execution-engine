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


def _extract_raw_code(raw: dict[str, Any] | None) -> str | None:
    if not raw:
        return None
    for key in ("reject_code", "error_code", "code", "status_code"):
        value = raw.get(key)
        if value not in (None, ""):
            return str(value)
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
    return BrokerDiagnostic(
        severity="WARNING",
        code="BROKER_WARNING",
        summary=text,
        action_hint=None,
    )
