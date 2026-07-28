"""State doctor issue detectors (consistency checks over local state)."""

from __future__ import annotations

from ._state_aggregates import _derive_parent_aggregate, _StateIndexes
from ._state_models import StateDoctorIssue
from .execution import OPEN_BROKER_STATUSES, TERMINAL_BROKER_STATUSES, ExecutionState


def _child_reference_issues(
    state: ExecutionState,
    indexes: _StateIndexes,
) -> list[StateDoctorIssue]:
    issues: list[StateDoctorIssue] = []
    for child in state.child_orders:
        if child.parent_order_id not in indexes.parents_by_id:
            issues.append(
                StateDoctorIssue(
                    severity="ERROR",
                    code="ORPHAN_CHILD",
                    message=(f"child {child.child_order_id} has no parent {child.parent_order_id}"),
                )
            )
        if child.broker_order_id and child.broker_order_id not in indexes.broker_orders_by_id:
            issues.append(
                StateDoctorIssue(
                    severity="WARN",
                    code="MISSING_BROKER_ORDER",
                    message=(
                        f"child {child.child_order_id} references missing broker order "
                        f"{child.broker_order_id}"
                    ),
                )
            )
    return issues


def _parent_integrity_issues(
    state: ExecutionState,
    indexes: _StateIndexes,
) -> list[StateDoctorIssue]:
    issues: list[StateDoctorIssue] = []
    for parent in state.parent_orders:
        if parent.intent_id not in indexes.intents_by_id:
            issues.append(
                StateDoctorIssue(
                    severity="ERROR",
                    code="ORPHAN_PARENT_INTENT",
                    message=f"parent {parent.parent_order_id} has no intent {parent.intent_id}",
                )
            )
        child_records = indexes.child_records_by_parent.get(parent.parent_order_id, [])
        if not child_records:
            issues.append(
                StateDoctorIssue(
                    severity="WARN",
                    code="PARENT_WITHOUT_CHILD",
                    message=f"parent {parent.parent_order_id} has no child order attempts",
                )
            )
        if float(parent.filled_quantity or 0.0) > float(parent.requested_quantity or 0.0):
            issues.append(
                StateDoctorIssue(
                    severity="ERROR",
                    code="PARENT_OVERFILLED",
                    message=(
                        f"parent {parent.parent_order_id} filled {parent.filled_quantity:g} "
                        f"> requested {parent.requested_quantity:g}"
                    ),
                )
            )
        if float(parent.remaining_quantity or 0.0) < 0:
            issues.append(
                StateDoctorIssue(
                    severity="ERROR",
                    code="NEGATIVE_REMAINING",
                    message=f"parent {parent.parent_order_id} has negative remaining quantity",
                )
            )
        latest_status = max((child.status for child in child_records), default=parent.status)
        if (
            parent.status == "PARTIALLY_FILLED"
            and float(parent.remaining_quantity or 0.0) > 0
            and latest_status not in OPEN_BROKER_STATUSES
            and parent.metadata.get("manual_resolution") != "accepted_partial"
        ):
            issues.append(
                StateDoctorIssue(
                    severity="WARN",
                    code="PARTIAL_FILL_NEEDS_OPERATOR",
                    message=(
                        f"parent {parent.parent_order_id} is partially filled with no "
                        "open child; consider cancel-rest, resume-remaining, or "
                        "accept-partial"
                    ),
                )
            )
    return issues


def _orphan_broker_order_issues(
    state: ExecutionState,
    indexes: _StateIndexes,
) -> list[StateDoctorIssue]:
    issues: list[StateDoctorIssue] = []
    for broker_order in state.broker_orders:
        if broker_order.broker_order_id in indexes.referenced_broker_order_ids:
            continue
        severity = "WARN" if broker_order.status in TERMINAL_BROKER_STATUSES else "ERROR"
        code = (
            "ORPHAN_TERMINAL_BROKER_ORDER"
            if broker_order.status in TERMINAL_BROKER_STATUSES
            else "ORPHAN_OPEN_BROKER_ORDER"
        )
        issues.append(
            StateDoctorIssue(
                severity=severity,
                code=code,
                message=(
                    f"broker order {broker_order.broker_order_id} "
                    f"({broker_order.status}) is not referenced by any child order"
                ),
            )
        )
    return issues


def _parent_aggregate_issues(
    state: ExecutionState,
    indexes: _StateIndexes,
) -> list[StateDoctorIssue]:
    issues: list[StateDoctorIssue] = []
    for parent in state.parent_orders:
        expected = _derive_parent_aggregate(
            state=state,
            parent=parent,
            child_orders=indexes.child_records_by_parent.get(parent.parent_order_id, []),
            broker_orders_by_id=indexes.broker_orders_by_id,
        )
        if (
            abs(float(parent.filled_quantity or 0.0) - expected.filled_quantity) > 1e-9
            or abs(float(parent.remaining_quantity or 0.0) - expected.remaining_quantity) > 1e-9
        ):
            issues.append(
                StateDoctorIssue(
                    severity="WARN",
                    code="PARENT_AGGREGATE_MISMATCH",
                    message=(
                        f"parent {parent.parent_order_id} stores filled/remaining "
                        f"{float(parent.filled_quantity or 0.0):g}/"
                        f"{float(parent.remaining_quantity or 0.0):g} but local "
                        f"child/fill state implies {expected.filled_quantity:g}/"
                        f"{expected.remaining_quantity:g}"
                    ),
                )
            )
        if str(parent.status) != expected.status:
            issues.append(
                StateDoctorIssue(
                    severity="WARN",
                    code="PARENT_STATUS_MISMATCH",
                    message=(
                        f"parent {parent.parent_order_id} has status {parent.status} "
                        f"but local child/fill state implies {expected.status}"
                    ),
                )
            )
    return issues


def _fill_event_issues(state: ExecutionState) -> list[StateDoctorIssue]:
    from collections import Counter

    issues: list[StateDoctorIssue] = []
    fill_counts = Counter(fill.fill_id for fill in state.fill_events)
    for fill_id, count in sorted(fill_counts.items()):
        if count <= 1:
            continue
        issues.append(
            StateDoctorIssue(
                severity="WARN",
                code="DUPLICATE_FILL_ID",
                message=f"fill id {fill_id} appears {count} times",
            )
        )

    child_order_ids = {
        child.broker_order_id for child in state.child_orders if child.broker_order_id
    }
    parent_order_ids = {parent.parent_order_id for parent in state.parent_orders}
    for fill in state.fill_events:
        if fill.parent_order_id in parent_order_ids or fill.broker_order_id in child_order_ids:
            continue
        issues.append(
            StateDoctorIssue(
                severity="WARN",
                code="ORPHAN_FILL_EVENT",
                message=(
                    f"fill {fill.fill_id} references parent {fill.parent_order_id} / "
                    f"broker order {fill.broker_order_id} but no tracked order exists"
                ),
            )
        )
    return issues


def _kill_switch_issues(state: ExecutionState) -> list[StateDoctorIssue]:
    if not state.kill_switch_active or state.consecutive_failures > 0:
        return []
    return [
        StateDoctorIssue(
            severity="WARN",
            code="STUCK_KILL_SWITCH",
            message="local kill switch is active with no recorded consecutive failures",
        )
    ]
