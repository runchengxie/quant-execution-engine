"""State inspection and maintenance helpers (public facade).

The public surface (the ``State*`` dataclasses and
:class:`StateMaintenanceService`) is preserved here. The implementation lives
in the focused submodules (``_state_models`` / ``_state_aggregates`` /
``_state_doctor`` / ``_state_prune``); this file re-imports those helpers and
keeps :class:`StateMaintenanceService` so external imports keep working
unchanged.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from ._state_aggregates import _build_state_indexes, _recompute_parent_aggregates
from ._state_doctor import (
    _child_reference_issues,
    _fill_event_issues,
    _kill_switch_issues,
    _orphan_broker_order_issues,
    _parent_aggregate_issues,
    _parent_integrity_issues,
)
from ._state_models import (
    TERMINAL_PARENT_STATUSES,
    StateDoctorIssue,
    StateDoctorResult,
    StatePruneResult,
    StateRepairResult,
)
from ._state_prune import (
    _build_prune_plan,
    _dedupe_fill_events,
    _drop_orphan_fill_events,
    _drop_orphan_terminal_broker_orders,
)
from .execution import ExecutionStateStore

if TYPE_CHECKING:
    from .execution_state import ExecutionStateStore as ExecutionStateStoreType

__all__ = [
    "TERMINAL_PARENT_STATUSES",
    "StateDoctorIssue",
    "StateDoctorResult",
    "StateMaintenanceService",
    "StatePruneResult",
    "StateRepairResult",
]


class StateMaintenanceService:
    """Inspect and maintain local execution state files."""

    def __init__(self, *, state_store: ExecutionStateStoreType | None = None) -> None:
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
            result.orphan_terminal_broker_orders_removed = _drop_orphan_terminal_broker_orders(
                state
            )

        if recompute_parent_aggregates:
            result.parent_aggregates_recomputed = _recompute_parent_aggregates(state)

        result.state_path = self.state_store.save(state)
        return result
