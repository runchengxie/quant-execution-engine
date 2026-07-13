# pyright: strict
"""Deterministic recovery evidence contract and offline fault-matrix entrypoint."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import cast

from .domain import OrderStatus
from .execution_journal import SubmissionState

RECOVERY_MATRIX_SCHEMA = "execution_recovery_matrix.v1"
RECOVERY_SCENARIO_IDS = (
    "accepted_but_timeout",
    "duplicate_submission",
    "duplicate_callback",
    "out_of_order_callback",
    "partial_fill_restart",
    "cancel_fill_race",
    "reconnect_replay",
    "position_drift",
)

_TOP_LEVEL_KEYS = frozenset({"schema", "mode", "deterministic", "live_broker_access", "scenarios"})
_SCENARIO_KEYS = frozenset({"id", "status", "expected_state", "reconciliation"})
_EXPECTED_STATE_KEYS = frozenset(
    {
        "submission_state",
        "order_status",
        "broker_order_id",
        "filled_quantity",
        "remaining_quantity",
        "submission_attempt_count",
        "order_event_count",
        "fill_count",
        "journal_sequence",
        "transport_submit_calls",
        "idempotent_retry_blocked",
        "state_monotonic",
    }
)
_RECONCILIATION_KEYS = frozenset(
    {
        "status",
        "result",
        "action",
        "evidence_count",
        "kill_switch",
        "position_drift",
    }
)


class RecoveryMatrixError(RuntimeError):
    """Base error for recovery-matrix generation and validation."""


class RecoveryMatrixValidationError(RecoveryMatrixError):
    """Raised when a recovery evidence payload violates the v1 contract."""


class RecoveryMatrixInvariantError(RecoveryMatrixError):
    """Raised when an offline fault scenario does not reach its expected state."""


class RecoveryMatrixMode(str, Enum):
    """Evidence mode; both variants remain offline and deterministic."""

    SHADOW = "shadow"
    PAPER = "paper"


def _mapping(value: object, path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise RecoveryMatrixValidationError(f"{path} must be an object")
    raw = cast(Mapping[object, object], value)
    if any(not isinstance(key, str) for key in raw):
        raise RecoveryMatrixValidationError(f"{path} keys must be strings")
    return cast(Mapping[str, object], raw)


def _exact_keys(value: Mapping[str, object], expected: frozenset[str], path: str) -> None:
    actual = frozenset(value)
    if actual == expected:
        return
    missing = ", ".join(sorted(expected - actual)) or "none"
    extra = ", ".join(sorted(actual - expected)) or "none"
    raise RecoveryMatrixValidationError(f"{path} keys differ; missing={missing}; extra={extra}")


def _string(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RecoveryMatrixValidationError(f"{path} must be a non-empty string")
    return value.strip()


def _integer(value: object, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RecoveryMatrixValidationError(f"{path} must be a non-negative integer")
    return value


def _boolean(value: object, path: str) -> bool:
    if not isinstance(value, bool):
        raise RecoveryMatrixValidationError(f"{path} must be a boolean")
    return value


def _optional_string(value: object, path: str) -> str | None:
    if value is None:
        return None
    return _string(value, path)


def _decimal_string(value: object, path: str, *, signed: bool = False) -> str:
    normalized = _string(value, path)
    try:
        parsed = Decimal(normalized)
    except InvalidOperation as exc:
        raise RecoveryMatrixValidationError(f"{path} must be a decimal string") from exc
    if not parsed.is_finite() or (not signed and parsed < 0):
        qualifier = "finite" if signed else "finite and non-negative"
        raise RecoveryMatrixValidationError(f"{path} must be {qualifier}")
    canonical = "0" if parsed == 0 else format(parsed.normalize(), "f")
    if "." in canonical:
        canonical = canonical.rstrip("0").rstrip(".")
    if canonical in {"", "-"}:  # pragma: no cover - Decimal normalization guard
        canonical = "0"
    if canonical != normalized:
        raise RecoveryMatrixValidationError(f"{path} must use canonical Decimal text")
    return normalized


def _validated_expected_state(value: object, path: str) -> Mapping[str, object]:
    payload = _mapping(value, path)
    _exact_keys(payload, _EXPECTED_STATE_KEYS, path)
    submission_state = _string(payload["submission_state"], f"{path}.submission_state")
    order_status = _optional_string(payload["order_status"], f"{path}.order_status")
    try:
        SubmissionState(submission_state)
    except ValueError as exc:
        raise RecoveryMatrixValidationError(
            f"{path}.submission_state is not a qexec SubmissionState"
        ) from exc
    if order_status is not None:
        try:
            OrderStatus(order_status)
        except ValueError as exc:
            raise RecoveryMatrixValidationError(
                f"{path}.order_status is not a qexec OrderStatus"
            ) from exc
    broker_order_id = _optional_string(payload["broker_order_id"], f"{path}.broker_order_id")
    result: dict[str, object] = {
        "submission_state": submission_state,
        "order_status": order_status,
        "broker_order_id": broker_order_id,
        "filled_quantity": _decimal_string(payload["filled_quantity"], f"{path}.filled_quantity"),
        "remaining_quantity": _decimal_string(
            payload["remaining_quantity"], f"{path}.remaining_quantity"
        ),
        "submission_attempt_count": _integer(
            payload["submission_attempt_count"], f"{path}.submission_attempt_count"
        ),
        "order_event_count": _integer(payload["order_event_count"], f"{path}.order_event_count"),
        "fill_count": _integer(payload["fill_count"], f"{path}.fill_count"),
        "journal_sequence": _integer(payload["journal_sequence"], f"{path}.journal_sequence"),
        "transport_submit_calls": _integer(
            payload["transport_submit_calls"], f"{path}.transport_submit_calls"
        ),
        "idempotent_retry_blocked": _boolean(
            payload["idempotent_retry_blocked"], f"{path}.idempotent_retry_blocked"
        ),
        "state_monotonic": _boolean(payload["state_monotonic"], f"{path}.state_monotonic"),
    }
    if result["submission_attempt_count"] != 1:
        raise RecoveryMatrixValidationError(f"{path}.submission_attempt_count must be 1")
    if result["transport_submit_calls"] != 1:
        raise RecoveryMatrixValidationError(f"{path}.transport_submit_calls must be 1")
    if result["idempotent_retry_blocked"] is not True:
        raise RecoveryMatrixValidationError(f"{path}.idempotent_retry_blocked must be true")
    if result["state_monotonic"] is not True:
        raise RecoveryMatrixValidationError(f"{path}.state_monotonic must be true")
    return MappingProxyType(result)


def _validated_reconciliation(value: object, path: str) -> Mapping[str, object]:
    payload = _mapping(value, path)
    _exact_keys(payload, _RECONCILIATION_KEYS, path)
    status = _string(payload["status"], f"{path}.status")
    if status not in {"resolved", "manual_intervention_required"}:
        raise RecoveryMatrixValidationError(f"{path}.status is unsupported: {status!r}")
    drift_value = payload["position_drift"]
    position_drift = (
        None
        if drift_value is None
        else _decimal_string(drift_value, f"{path}.position_drift", signed=True)
    )
    return MappingProxyType(
        {
            "status": status,
            "result": _string(payload["result"], f"{path}.result"),
            "action": _string(payload["action"], f"{path}.action"),
            "evidence_count": _integer(payload["evidence_count"], f"{path}.evidence_count"),
            "kill_switch": _boolean(payload["kill_switch"], f"{path}.kill_switch"),
            "position_drift": position_drift,
        }
    )


@dataclass(frozen=True, slots=True)
class RecoveryScenarioResult:
    """One successfully verified deterministic fault scenario."""

    id: str
    expected_state: Mapping[str, object]
    reconciliation: Mapping[str, object]
    status: str = "passed"

    def __post_init__(self) -> None:
        scenario_id = _string(self.id, "scenario.id")
        if scenario_id not in RECOVERY_SCENARIO_IDS:
            raise RecoveryMatrixValidationError(f"unknown recovery scenario: {scenario_id}")
        if self.status != "passed":
            raise RecoveryMatrixValidationError("scenario.status must be 'passed'")
        object.__setattr__(self, "id", scenario_id)
        object.__setattr__(
            self,
            "expected_state",
            _validated_expected_state(
                self.expected_state, f"scenario[{scenario_id}].expected_state"
            ),
        )
        object.__setattr__(
            self,
            "reconciliation",
            _validated_reconciliation(
                self.reconciliation,
                f"scenario[{scenario_id}].reconciliation",
            ),
        )

    def to_payload(self) -> dict[str, object]:
        return {
            "id": self.id,
            "status": self.status,
            "expected_state": dict(self.expected_state),
            "reconciliation": dict(self.reconciliation),
        }


@dataclass(frozen=True, slots=True)
class ExecutionRecoveryMatrix:
    """Strict v1 recovery evidence with no environment-dependent fields."""

    mode: RecoveryMatrixMode
    scenarios: tuple[RecoveryScenarioResult, ...]
    schema: str = field(default=RECOVERY_MATRIX_SCHEMA, init=False)
    deterministic: bool = field(default=True, init=False)
    live_broker_access: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if not isinstance(cast(object, self.mode), RecoveryMatrixMode):
            raise TypeError("mode must be RecoveryMatrixMode")
        scenario_ids = tuple(item.id for item in self.scenarios)
        if scenario_ids != RECOVERY_SCENARIO_IDS:
            raise RecoveryMatrixValidationError(
                "scenarios must contain the complete canonical recovery matrix in order"
            )

    def to_payload(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "mode": self.mode.value,
            "deterministic": self.deterministic,
            "live_broker_access": self.live_broker_access,
            "scenarios": [item.to_payload() for item in self.scenarios],
        }


def execution_recovery_matrix_bytes(matrix: ExecutionRecoveryMatrix) -> bytes:
    """Return canonical UTF-8 JSON bytes with one stable trailing newline."""

    rendered = json.dumps(
        matrix.to_payload(),
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
        allow_nan=False,
    )
    return f"{rendered}\n".encode()


def validate_execution_recovery_matrix_payload(value: object) -> ExecutionRecoveryMatrix:
    """Strictly validate and normalize a decoded v1 recovery matrix."""

    payload = _mapping(value, "matrix")
    _exact_keys(payload, _TOP_LEVEL_KEYS, "matrix")
    if payload["schema"] != RECOVERY_MATRIX_SCHEMA:
        raise RecoveryMatrixValidationError(f"matrix.schema must be {RECOVERY_MATRIX_SCHEMA!r}")
    if _boolean(payload["deterministic"], "matrix.deterministic") is not True:
        raise RecoveryMatrixValidationError("matrix.deterministic must be true")
    if _boolean(payload["live_broker_access"], "matrix.live_broker_access") is not False:
        raise RecoveryMatrixValidationError("matrix.live_broker_access must be false")
    try:
        mode = RecoveryMatrixMode(_string(payload["mode"], "matrix.mode"))
    except ValueError as exc:
        raise RecoveryMatrixValidationError("matrix.mode must be shadow or paper") from exc
    raw_scenarios = payload["scenarios"]
    if not isinstance(raw_scenarios, list):
        raise RecoveryMatrixValidationError("matrix.scenarios must be an array")
    scenarios: list[RecoveryScenarioResult] = []
    for index, raw_scenario in enumerate(cast(list[object], raw_scenarios)):
        scenario = _mapping(raw_scenario, f"matrix.scenarios[{index}]")
        _exact_keys(scenario, _SCENARIO_KEYS, f"matrix.scenarios[{index}]")
        scenarios.append(
            RecoveryScenarioResult(
                id=_string(scenario["id"], f"matrix.scenarios[{index}].id"),
                status=_string(scenario["status"], f"matrix.scenarios[{index}].status"),
                expected_state=_mapping(
                    scenario["expected_state"],
                    f"matrix.scenarios[{index}].expected_state",
                ),
                reconciliation=_mapping(
                    scenario["reconciliation"],
                    f"matrix.scenarios[{index}].reconciliation",
                ),
            )
        )
    return ExecutionRecoveryMatrix(mode=mode, scenarios=tuple(scenarios))


def load_execution_recovery_matrix_bytes(value: bytes) -> ExecutionRecoveryMatrix:
    """Decode strict UTF-8 JSON evidence and reject malformed input."""

    try:
        decoded = value.decode("utf-8")
        payload: object = json.loads(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RecoveryMatrixValidationError("recovery matrix is not valid UTF-8 JSON") from exc
    return validate_execution_recovery_matrix_payload(payload)


def run_execution_recovery_matrix(
    *,
    mode: RecoveryMatrixMode = RecoveryMatrixMode.SHADOW,
    workspace: Path | None = None,
) -> ExecutionRecoveryMatrix:
    """Run all offline scenarios, optionally retaining local SQLite journals."""

    if not isinstance(cast(object, mode), RecoveryMatrixMode):
        raise TypeError("mode must be RecoveryMatrixMode")
    from ._recovery_fault_harness import run_fault_scenarios

    return ExecutionRecoveryMatrix(
        mode=mode,
        scenarios=run_fault_scenarios(mode=mode, workspace=workspace),
    )


def write_execution_recovery_matrix(
    output_path: str | Path,
    *,
    mode: RecoveryMatrixMode = RecoveryMatrixMode.SHADOW,
    workspace: Path | None = None,
) -> ExecutionRecoveryMatrix:
    """Atomically write canonical recovery evidence and return its model."""

    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    matrix = run_execution_recovery_matrix(mode=mode, workspace=workspace)
    temporary = destination.with_name(f".{destination.name}.tmp")
    try:
        temporary.write_bytes(execution_recovery_matrix_bytes(matrix))
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return matrix


__all__ = [
    "ExecutionRecoveryMatrix",
    "RECOVERY_MATRIX_SCHEMA",
    "RECOVERY_SCENARIO_IDS",
    "RecoveryMatrixError",
    "RecoveryMatrixInvariantError",
    "RecoveryMatrixMode",
    "RecoveryMatrixValidationError",
    "RecoveryScenarioResult",
    "execution_recovery_matrix_bytes",
    "load_execution_recovery_matrix_bytes",
    "run_execution_recovery_matrix",
    "validate_execution_recovery_matrix_payload",
    "write_execution_recovery_matrix",
]
