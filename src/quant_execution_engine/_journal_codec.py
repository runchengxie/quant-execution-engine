# pyright: strict
"""Canonical payload and snapshot codecs for the execution journal."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import cast

from ._journal_domain import (
    ExecutionJournalState,
    IntentLifecycle,
    JournalCorruptionError,
    ReconciliationEvidence,
    SubmissionState,
)
from .domain import Fill, OrderEvent, OrderIntent, OrderStatus
from .serialization import (
    fill_from_v2,
    fill_to_v2,
    order_event_from_v2,
    order_event_to_v2,
    order_intent_from_v2,
    order_intent_to_v2,
)

_SNAPSHOT_SCHEMA_VERSION = 1


def _json_value(value: object) -> object:
    if isinstance(value, Mapping):
        source = cast(Mapping[object, object], value)
        return {str(key): _json_value(item) for key, item in source.items()}
    if isinstance(value, (list, tuple)):
        sequence = cast(list[object] | tuple[object, ...], value)
        return [_json_value(item) for item in sequence]
    return value


def canonical_json(value: Mapping[str, object]) -> str:
    """Serialize a mapping to byte-stable compact JSON."""

    return json.dumps(
        _json_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise JournalCorruptionError(f"{label} must be a JSON object")
    source = cast(Mapping[object, object], value)
    result: dict[str, object] = {}
    for key, item in source.items():
        if not isinstance(key, str):
            raise JournalCorruptionError(f"{label} keys must be strings")
        result[key] = item
    return result


def parse_json(value: str, label: str) -> Mapping[str, object]:
    """Parse a journal payload and normalize malformed JSON as corruption."""

    try:
        decoded = cast(object, json.loads(value))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise JournalCorruptionError(f"{label} contains invalid JSON") from exc
    return _mapping(decoded, label)


def _required_string(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise JournalCorruptionError(f"{key} must be a non-empty string")
    return value.strip()


def _optional_string(payload: Mapping[str, object], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise JournalCorruptionError(f"{key} must be a string or null")
    return value.strip() or None


def _required_int(payload: Mapping[str, object], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise JournalCorruptionError(f"{key} must be an integer")
    return value


def datetime_to_json(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("journal timestamps must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def datetime_from_json(value: object, field_name: str) -> datetime:
    if not isinstance(value, str):
        raise JournalCorruptionError(f"{field_name} must be an ISO-8601 string")
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise JournalCorruptionError(f"{field_name} is not a valid ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise JournalCorruptionError(f"{field_name} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _decimal_to_json(value: Decimal | None) -> str | None:
    if value is None:
        return None
    normalized = value.normalize()
    if normalized == normalized.to_integral():
        return format(normalized, "f")
    return format(normalized, "f").rstrip("0").rstrip(".")


def _decimal_from_json(value: object, field_name: str) -> Decimal | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise JournalCorruptionError(f"{field_name} must be a decimal string")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise JournalCorruptionError(f"{field_name} is not a valid decimal") from exc
    if not parsed.is_finite():
        raise JournalCorruptionError(f"{field_name} must be finite")
    return parsed


def _required_decimal_from_json(value: object, field_name: str) -> Decimal:
    parsed = _decimal_from_json(value, field_name)
    if parsed is None:
        raise JournalCorruptionError(f"{field_name} cannot be null")
    return parsed


def intent_payload(intent: OrderIntent, idempotency_key: str) -> str:
    return canonical_json(
        {
            "schema_version": 1,
            "kind": "intent_recorded",
            "idempotency_key": idempotency_key,
            "intent": order_intent_to_v2(intent),
        }
    )


def intent_from_payload(value: str) -> tuple[OrderIntent, str]:
    payload = parse_json(value, "intent payload")
    intent_value = payload.get("intent")
    try:
        intent = order_intent_from_v2(intent_value)
    except (TypeError, ValueError) as exc:
        raise JournalCorruptionError("intent payload contains an invalid order intent") from exc
    return intent, _required_string(payload, "idempotency_key")


def submission_payload(attempt_id: str, message: str | None = None) -> str:
    return canonical_json(
        {
            "schema_version": 1,
            "kind": "submission_attempt",
            "attempt_id": attempt_id,
            "message": message,
        }
    )


def submission_from_payload(value: str) -> tuple[str, str | None]:
    payload = parse_json(value, "submission payload")
    return _required_string(payload, "attempt_id"), _optional_string(payload, "message")


def order_event_payload(event: OrderEvent) -> str:
    return canonical_json(order_event_to_v2(event))


def order_event_from_payload(value: str) -> OrderEvent:
    try:
        return order_event_from_v2(parse_json(value, "order event payload"))
    except (TypeError, ValueError) as exc:
        raise JournalCorruptionError("invalid order event payload") from exc


def fill_payload(fill: Fill) -> str:
    return canonical_json(fill_to_v2(fill))


def fill_from_payload(value: str) -> Fill:
    try:
        return fill_from_v2(parse_json(value, "fill payload"))
    except (TypeError, ValueError) as exc:
        raise JournalCorruptionError("invalid fill payload") from exc


def evidence_to_mapping(evidence: ReconciliationEvidence) -> dict[str, object]:
    return {
        "schema_version": 1,
        "kind": "reconciliation_evidence",
        "evidence_id": evidence.evidence_id,
        "intent_id": evidence.intent_id,
        "observed_at": datetime_to_json(evidence.observed_at),
        "source": evidence.source,
        "observed_status": evidence.observed_status.value,
        "broker_order_id": evidence.broker_order_id,
        "observed_filled_quantity": _decimal_to_json(evidence.observed_filled_quantity),
        "observed_remaining_quantity": _decimal_to_json(evidence.observed_remaining_quantity),
        "message": evidence.message,
        "metadata": evidence.metadata,
    }


def evidence_payload(evidence: ReconciliationEvidence) -> str:
    return canonical_json(evidence_to_mapping(evidence))


def evidence_from_mapping(value: object) -> ReconciliationEvidence:
    payload = _mapping(value, "reconciliation evidence")
    status_raw = _required_string(payload, "observed_status")
    try:
        status = OrderStatus(status_raw)
    except ValueError as exc:
        raise JournalCorruptionError(f"unknown reconciliation status {status_raw!r}") from exc
    metadata_value = payload.get("metadata", {})
    metadata = _mapping(metadata_value, "reconciliation metadata")
    try:
        return ReconciliationEvidence(
            evidence_id=_required_string(payload, "evidence_id"),
            intent_id=_required_string(payload, "intent_id"),
            observed_at=datetime_from_json(payload.get("observed_at"), "observed_at"),
            source=_required_string(payload, "source"),
            observed_status=status,
            broker_order_id=_optional_string(payload, "broker_order_id"),
            observed_filled_quantity=_decimal_from_json(
                payload.get("observed_filled_quantity"), "observed_filled_quantity"
            ),
            observed_remaining_quantity=_decimal_from_json(
                payload.get("observed_remaining_quantity"), "observed_remaining_quantity"
            ),
            message=_optional_string(payload, "message"),
            metadata=metadata,
        )
    except (TypeError, ValueError) as exc:
        raise JournalCorruptionError("invalid reconciliation evidence") from exc


def evidence_from_payload(value: str) -> ReconciliationEvidence:
    return evidence_from_mapping(parse_json(value, "reconciliation evidence payload"))


def _lifecycle_to_mapping(lifecycle: IntentLifecycle) -> dict[str, object]:
    return {
        "intent": order_intent_to_v2(lifecycle.intent),
        "idempotency_key": lifecycle.idempotency_key,
        "submission_state": lifecycle.submission_state.value,
        "order_status": lifecycle.order_status.value if lifecycle.order_status else None,
        "broker_order_id": lifecycle.broker_order_id,
        "filled_quantity": _decimal_to_json(lifecycle.filled_quantity),
        "remaining_quantity": _decimal_to_json(lifecycle.remaining_quantity),
        "average_fill_price": _decimal_to_json(lifecycle.average_fill_price),
        "last_sequence": lifecycle.last_sequence,
        "submission_attempt_ids": list(lifecycle.submission_attempt_ids),
        "order_event_ids": list(lifecycle.order_event_ids),
        "fills": [fill_to_v2(fill) for fill in lifecycle.fills],
        "reconciliation_evidence": [
            evidence_to_mapping(item) for item in lifecycle.reconciliation_evidence
        ],
        "uncertainty_messages": list(lifecycle.uncertainty_messages),
    }


def state_to_json(state: ExecutionJournalState) -> str:
    return canonical_json(
        {
            "schema_version": _SNAPSHOT_SCHEMA_VERSION,
            "kind": "execution_journal_state",
            "through_sequence": state.through_sequence,
            "intents": [
                _lifecycle_to_mapping(state.intents[intent_id])
                for intent_id in sorted(state.intents)
            ],
        }
    )


def _string_tuple(value: object, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise JournalCorruptionError(f"{field_name} must be an array")
    sequence = cast(list[object], value)
    if not all(isinstance(item, str) for item in sequence):
        raise JournalCorruptionError(f"{field_name} entries must be strings")
    return tuple(cast(list[str], sequence))


def _lifecycle_from_mapping(value: object) -> IntentLifecycle:
    payload = _mapping(value, "snapshot lifecycle")
    try:
        intent = order_intent_from_v2(payload.get("intent"))
        submission_state = SubmissionState(_required_string(payload, "submission_state"))
        order_status_raw = _optional_string(payload, "order_status")
        order_status = OrderStatus(order_status_raw) if order_status_raw is not None else None
        fills_raw = payload.get("fills", [])
        evidence_raw = payload.get("reconciliation_evidence", [])
        if not isinstance(fills_raw, list) or not isinstance(evidence_raw, list):
            raise JournalCorruptionError("snapshot fills and evidence must be arrays")
        return IntentLifecycle(
            intent=intent,
            idempotency_key=_required_string(payload, "idempotency_key"),
            submission_state=submission_state,
            order_status=order_status,
            broker_order_id=_optional_string(payload, "broker_order_id"),
            filled_quantity=_required_decimal_from_json(
                payload.get("filled_quantity"), "filled_quantity"
            ),
            remaining_quantity=_required_decimal_from_json(
                payload.get("remaining_quantity"), "remaining_quantity"
            ),
            average_fill_price=_decimal_from_json(
                payload.get("average_fill_price"), "average_fill_price"
            ),
            last_sequence=_required_int(payload, "last_sequence"),
            submission_attempt_ids=_string_tuple(
                payload.get("submission_attempt_ids", []), "submission_attempt_ids"
            ),
            order_event_ids=_string_tuple(payload.get("order_event_ids", []), "order_event_ids"),
            fills=tuple(fill_from_v2(item) for item in cast(list[object], fills_raw)),
            reconciliation_evidence=tuple(
                evidence_from_mapping(item) for item in cast(list[object], evidence_raw)
            ),
            uncertainty_messages=_string_tuple(
                payload.get("uncertainty_messages", []), "uncertainty_messages"
            ),
        )
    except JournalCorruptionError:
        raise
    except (TypeError, ValueError) as exc:
        raise JournalCorruptionError("snapshot contains an invalid lifecycle") from exc


def state_from_json(value: str) -> ExecutionJournalState:
    payload = parse_json(value, "journal snapshot")
    if payload.get("schema_version") != _SNAPSHOT_SCHEMA_VERSION:
        raise JournalCorruptionError("unsupported journal snapshot schema_version")
    if payload.get("kind") != "execution_journal_state":
        raise JournalCorruptionError("invalid journal snapshot kind")
    through_sequence = _required_int(payload, "through_sequence")
    raw_intents = payload.get("intents")
    if not isinstance(raw_intents, list):
        raise JournalCorruptionError("snapshot intents must be an array")
    intents: dict[str, IntentLifecycle] = {}
    for raw in cast(list[object], raw_intents):
        lifecycle = _lifecycle_from_mapping(raw)
        intent_id = lifecycle.intent.intent_id
        if intent_id in intents:
            raise JournalCorruptionError(f"duplicate intent {intent_id!r} in snapshot")
        intents[intent_id] = lifecycle
    return ExecutionJournalState(through_sequence=through_sequence, intents=intents)
