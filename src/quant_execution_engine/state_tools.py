"""State inspection and maintenance helpers."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .execution import (
    OPEN_BROKER_STATUSES,
    TERMINAL_BROKER_STATUSES,
    ExecutionState,
    ExecutionStateStore,
)
from .broker.base import utc_now_iso
from .execution_state import ParentOrder


TERMINAL_PARENT_STATUSES = TERMINAL_BROKER_STATUSES | {
    "BLOCKED",
    "FILLED",
    "ACCEPTED_PARTIAL",
}


@dataclass(slots=True)
class StateDoctorIssue:
    """Single state consistency finding."""

    severity: str
    code: str
    message: str


@dataclass(slots=True)
class StateDoctorResult:
    """State inspection summary."""

    broker_name: str
    account_label: str
    state_path: Path
    issues: list[StateDoctorIssue] = field(default_factory=list)


@dataclass(slots=True)
class StatePruneResult:
    """State prune summary."""

    broker_name: str
    account_label: str
    state_path: Path
    older_than_days: int
    apply: bool
    parent_orders_removed: int = 0
    child_orders_removed: int = 0
    broker_orders_removed: int = 0
    fill_events_removed: int = 0
    intents_removed: int = 0


@dataclass(slots=True)
class StateRepairResult:
    """State repair summary."""

    broker_name: str
    account_label: str
    state_path: Path
    cleared_kill_switch: bool = False
    duplicate_fills_removed: int = 0
    orphan_fills_removed: int = 0
    orphan_terminal_broker_orders_removed: int = 0
    parent_aggregates_recomputed: int = 0


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = str(value).strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass(slots=True)
class _ExpectedParentAggregate:
    filled_quantity: float
    remaining_quantity: float
    status: str


def _latest_child_status(
    *,
    parent: ParentOrder,
    child_orders: list,
    broker_orders_by_id: dict[str, object],
) -> str:
    latest_child = max(
        child_orders,
        key=lambda child: (
            child.attempt,
            child.updated_at or "",
            child.created_at or "",
            child.child_order_id,
        ),
        default=None,
    )
    if latest_child is None:
        return parent.status
    if latest_child.broker_order_id and latest_child.broker_order_id in broker_orders_by_id:
        return str(broker_orders_by_id[latest_child.broker_order_id].status)
    return str(latest_child.status)


def _derive_parent_aggregate(
    *,
    state: ExecutionState,
    parent: ParentOrder,
    child_orders: list,
    broker_orders_by_id: dict[str, object],
) -> _ExpectedParentAggregate:
    child_broker_order_ids = {
        child.broker_order_id for child in child_orders if child.broker_order_id
    }
    fill_quantity_by_broker_order = Counter()
    unmatched_parent_fill_quantity = 0.0
    for fill in state.fill_events:
        if fill.parent_order_id != parent.parent_order_id:
            continue
        if fill.broker_order_id in child_broker_order_ids:
            fill_quantity_by_broker_order[fill.broker_order_id] += float(fill.quantity or 0.0)
        else:
            unmatched_parent_fill_quantity += float(fill.quantity or 0.0)

    total_filled_quantity = float(unmatched_parent_fill_quantity)
    has_open_child = False
    for child in child_orders:
        broker_order = (
            broker_orders_by_id.get(child.broker_order_id) if child.broker_order_id else None
        )
        child_status = (
            str(broker_order.status)
            if broker_order is not None
            else str(child.status or "")
        ).upper()
        if child_status in OPEN_BROKER_STATUSES:
            has_open_child = True
        broker_filled_quantity = (
            float(broker_order.filled_quantity or 0.0) if broker_order is not None else 0.0
        )
        fill_filled_quantity = (
            float(fill_quantity_by_broker_order.get(child.broker_order_id, 0.0))
            if child.broker_order_id
            else 0.0
        )
        total_filled_quantity += max(broker_filled_quantity, fill_filled_quantity)

    requested_quantity = float(parent.requested_quantity or 0.0)
    remaining_quantity = max(0.0, requested_quantity - total_filled_quantity)
    manual_resolution = str(parent.metadata.get("manual_resolution") or "").strip().lower()
    latest_status = _latest_child_status(
        parent=parent,
        child_orders=child_orders,
        broker_orders_by_id=broker_orders_by_id,
    )
    if manual_resolution == "accepted_partial":
        status = "ACCEPTED_PARTIAL"
    elif requested_quantity > 0 and total_filled_quantity >= requested_quantity:
        status = "FILLED"
    elif total_filled_quantity > 0:
        status = "PARTIALLY_FILLED"
    elif has_open_child:
        status = "PENDING"
    else:
        status = latest_status or parent.status
    return _ExpectedParentAggregate(
        filled_quantity=float(total_filled_quantity),
        remaining_quantity=float(remaining_quantity),
        status=str(status),
    )


def _parent_aggregate_mismatch(
    parent: ParentOrder,
    expected: _ExpectedParentAggregate,
) -> bool:
    return (
        abs(float(parent.filled_quantity or 0.0) - expected.filled_quantity) > 1e-9
        or abs(float(parent.remaining_quantity or 0.0) - expected.remaining_quantity) > 1e-9
        or str(parent.status) != expected.status
    )


@dataclass(slots=True)
class _StateIndexes:
    parents_by_id: dict[str, ParentOrder]
    intents_by_id: dict[str, object]
    child_records_by_parent: dict[str, list]
    referenced_broker_order_ids: set[str]
    broker_orders_by_id: dict[str, object]


def _build_state_indexes(state: ExecutionState) -> _StateIndexes:
    child_records_by_parent: dict[str, list] = {}
    referenced_broker_order_ids: set[str] = set()
    for child in state.child_orders:
        child_records_by_parent.setdefault(child.parent_order_id, []).append(child)
        if child.broker_order_id:
            referenced_broker_order_ids.add(child.broker_order_id)
    return _StateIndexes(
        parents_by_id={parent.parent_order_id: parent for parent in state.parent_orders},
        intents_by_id={intent.intent_id: intent for intent in state.intents},
        child_records_by_parent=child_records_by_parent,
        referenced_broker_order_ids=referenced_broker_order_ids,
        broker_orders_by_id={
            broker_order.broker_order_id: broker_order
            for broker_order in state.broker_orders
        },
    )


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
                    message=(
                        f"child {child.child_order_id} has no parent "
                        f"{child.parent_order_id}"
                    ),
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
            or abs(float(parent.remaining_quantity or 0.0) - expected.remaining_quantity)
            > 1e-9
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
        if (
            fill.parent_order_id in parent_order_ids
            or fill.broker_order_id in child_order_ids
        ):
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


@dataclass(slots=True)
class _PrunePlan:
    parent_order_ids: set[str]
    child_order_ids: set[str]
    broker_order_ids: set[str]
    fill_ids: set[str]
    intent_ids: set[str]
    child_count: int


def _build_prune_plan(state: ExecutionState, cutoff: datetime) -> _PrunePlan:
    prunable_parent_ids = {
        parent.parent_order_id
        for parent in state.parent_orders
        if parent.status in TERMINAL_PARENT_STATUSES
        and (_parse_timestamp(parent.updated_at) or datetime.min.replace(tzinfo=timezone.utc))
        <= cutoff
    }
    prunable_children = [
        child
        for child in state.child_orders
        if child.parent_order_id in prunable_parent_ids
    ]
    prunable_broker_order_ids = {
        child.broker_order_id for child in prunable_children if child.broker_order_id
    }
    remaining_parent_intents = {
        parent.intent_id
        for parent in state.parent_orders
        if parent.parent_order_id not in prunable_parent_ids
    }
    return _PrunePlan(
        parent_order_ids=prunable_parent_ids,
        child_order_ids={child.child_order_id for child in prunable_children},
        broker_order_ids=prunable_broker_order_ids,
        fill_ids={
            fill.fill_id
            for fill in state.fill_events
            if fill.parent_order_id in prunable_parent_ids
            or fill.broker_order_id in prunable_broker_order_ids
        },
        intent_ids={
            parent.intent_id
            for parent in state.parent_orders
            if parent.parent_order_id in prunable_parent_ids
            and parent.intent_id not in remaining_parent_intents
        },
        child_count=len(prunable_children),
    )


def _dedupe_fill_events(state: ExecutionState) -> int:
    seen: set[str] = set()
    deduped = []
    removed = 0
    for fill in state.fill_events:
        if fill.fill_id in seen:
            removed += 1
            continue
        seen.add(fill.fill_id)
        deduped.append(fill)
    state.fill_events = deduped
    return removed


def _drop_orphan_fill_events(state: ExecutionState) -> int:
    parent_order_ids = {parent.parent_order_id for parent in state.parent_orders}
    broker_order_ids = {
        child.broker_order_id for child in state.child_orders if child.broker_order_id
    }
    kept = []
    removed = 0
    for fill in state.fill_events:
        if fill.parent_order_id in parent_order_ids or fill.broker_order_id in broker_order_ids:
            kept.append(fill)
            continue
        removed += 1
    state.fill_events = kept
    return removed


def _drop_orphan_terminal_broker_orders(state: ExecutionState) -> int:
    referenced = {
        child.broker_order_id for child in state.child_orders if child.broker_order_id
    }
    kept = []
    removed = 0
    for broker_order in state.broker_orders:
        if (
            broker_order.broker_order_id not in referenced
            and broker_order.status in TERMINAL_BROKER_STATUSES
        ):
            removed += 1
            continue
        kept.append(broker_order)
    state.broker_orders = kept
    return removed


def _recompute_parent_aggregates(state: ExecutionState) -> int:
    indexes = _build_state_indexes(state)
    repaired = 0
    for parent in state.parent_orders:
        expected = _derive_parent_aggregate(
            state=state,
            parent=parent,
            child_orders=indexes.child_records_by_parent.get(parent.parent_order_id, []),
            broker_orders_by_id=indexes.broker_orders_by_id,
        )
        if not _parent_aggregate_mismatch(parent, expected):
            continue
        parent.filled_quantity = expected.filled_quantity
        parent.remaining_quantity = expected.remaining_quantity
        parent.status = expected.status
        parent.updated_at = utc_now_iso()
        repaired += 1
    return repaired


class StateMaintenanceService:
    """Inspect and maintain local execution state files."""

    def __init__(self, *, state_store: ExecutionStateStore | None = None) -> None:
        self.state_store = state_store or ExecutionStateStore()

    def doctor(self, *, broker_name: str, account_label: str) -> StateDoctorResult:
        state = self.state_store.load(broker_name, account_label)
        state_path = self.state_store.path_for(broker_name, account_label)
        indexes = _build_state_indexes(state)
        issues = [
            *_child_reference_issues(state, indexes),
            *_parent_integrity_issues(state, indexes),
            *_orphan_broker_order_issues(state, indexes),
            *_parent_aggregate_issues(state, indexes),
            *_fill_event_issues(state),
            *_kill_switch_issues(state),
        ]
        if not issues:
            issues.append(
                StateDoctorIssue(
                    severity="INFO",
                    code="STATE_OK",
                    message="no consistency issues were detected in the local execution state",
                )
            )

        return StateDoctorResult(
            broker_name=broker_name,
            account_label=account_label,
            state_path=state_path,
            issues=issues,
        )

    def prune(
        self,
        *,
        broker_name: str,
        account_label: str,
        older_than_days: int,
        apply: bool,
    ) -> StatePruneResult:
        if older_than_days <= 0:
            raise ValueError("older_than_days must be greater than 0")

        state = self.state_store.load(broker_name, account_label)
        state_path = self.state_store.path_for(broker_name, account_label)
        cutoff = datetime.now(timezone.utc) - timedelta(days=int(older_than_days))
        plan = _build_prune_plan(state, cutoff)

        result = StatePruneResult(
            broker_name=broker_name,
            account_label=account_label,
            state_path=state_path,
            older_than_days=int(older_than_days),
            apply=apply,
            parent_orders_removed=len(plan.parent_order_ids),
            child_orders_removed=plan.child_count,
            broker_orders_removed=len(plan.broker_order_ids),
            fill_events_removed=len(plan.fill_ids),
            intents_removed=len(plan.intent_ids),
        )
        if not apply or not plan.parent_order_ids:
            return result

        state.parent_orders = [
            parent
            for parent in state.parent_orders
            if parent.parent_order_id not in plan.parent_order_ids
        ]
        state.child_orders = [
            child
            for child in state.child_orders
            if child.child_order_id not in plan.child_order_ids
        ]
        state.broker_orders = [
            broker_order
            for broker_order in state.broker_orders
            if broker_order.broker_order_id not in plan.broker_order_ids
        ]
        state.fill_events = [
            fill for fill in state.fill_events if fill.fill_id not in plan.fill_ids
        ]
        state.intents = [
            intent for intent in state.intents if intent.intent_id not in plan.intent_ids
        ]
        result.state_path = self.state_store.save(state)
        return result

    def repair(
        self,
        *,
        broker_name: str,
        account_label: str,
        clear_kill_switch: bool,
        dedupe_fills: bool,
        drop_orphan_fills: bool,
        drop_orphan_terminal_broker_orders: bool,
        recompute_parent_aggregates: bool,
    ) -> StateRepairResult:
        if not any(
            (
                clear_kill_switch,
                dedupe_fills,
                drop_orphan_fills,
                drop_orphan_terminal_broker_orders,
                recompute_parent_aggregates,
            )
        ):
            raise ValueError("select at least one repair action")

        state = self.state_store.load(broker_name, account_label)
        state_path = self.state_store.path_for(broker_name, account_label)
        result = StateRepairResult(
            broker_name=broker_name,
            account_label=account_label,
            state_path=state_path,
        )

        if clear_kill_switch and state.kill_switch_active:
            state.kill_switch_active = False
            state.kill_switch_reason = None
            state.consecutive_failures = 0
            result.cleared_kill_switch = True

        if dedupe_fills:
            result.duplicate_fills_removed = _dedupe_fill_events(state)

        if drop_orphan_fills:
            result.orphan_fills_removed = _drop_orphan_fill_events(state)

        if drop_orphan_terminal_broker_orders:
            result.orphan_terminal_broker_orders_removed = (
                _drop_orphan_terminal_broker_orders(state)
            )

        if recompute_parent_aggregates:
            result.parent_aggregates_recomputed = _recompute_parent_aggregates(state)

        result.state_path = self.state_store.save(state)
        return result
