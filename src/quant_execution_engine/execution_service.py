"""Execution lifecycle service and reconcile coordinator."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

from .broker.base import (
    BrokerAdapter,
    BrokerFillRecord,
    BrokerOrderRecord,
    BrokerOrderRequest,
    BrokerReconcileReport,
    ResolvedBrokerAccount,
    UnsupportedBrokerOperationError,
    utc_now_iso,
)
from .execution_state import (
    DEFAULT_EXCEPTION_STATUSES,
    FAILURE_BROKER_STATUSES,
    OPEN_BROKER_STATUSES,
    STALE_RETRY_EXCLUDED_STATUSES,
    SUCCESS_BROKER_STATUSES,
    TERMINAL_BROKER_STATUSES,
    ChildOrder,
    ExecutionAcceptPartialResult,
    ExecutionBulkCancelResult,
    ExecutionCancelResult,
    ExecutionExceptionRecord,
    ExecutionFillEvent,
    ExecutionOrderTrace,
    ExecutionReconcileDelta,
    ExecutionReconcileResult,
    ExecutionRepriceResult,
    ExecutionResumeRemainingResult,
    ExecutionRetryResult,
    ExecutionStaleRetryResult,
    ExecutionState,
    ExecutionStateStore,
    ExecutionTrackedOrder,
    OrderIntent,
    ParentOrder,
)
from .execution_helpers import (
    broker_order_is_open,
    build_reconcile_deltas,
    find_parent_for_fill,
    find_tracked_broker_order,
    load_account_state,
    require_latest_child_attempt,
    require_partial_fill_quantities,
    resolve_tracked_order_context,
)
from .logging import get_logger
from .execution_service_recovery import OrderLifecycleRecoveryMixin
from .models import Order
from .risk import RiskDecision, RiskGateChain, get_kill_switch_config, is_manual_kill_switch_active

logger = get_logger(__name__)


def _intent_limit_price(order: Order) -> float | None:
    if str(order.order_type).upper() != "LIMIT":
        return None
    return float(order.price) if order.price is not None else None


class OrderLifecycleService(OrderLifecycleRecoveryMixin):
    """Submission, idempotency, and reconcile coordinator."""

    def __init__(
        self,
        adapter: BrokerAdapter,
        *,
        state_store: ExecutionStateStore | None = None,
        risk_chain: RiskGateChain | None = None,
    ) -> None:
        self.adapter = adapter
        self.state_store = state_store or ExecutionStateStore()
        self.risk_chain = risk_chain or RiskGateChain()
        self.last_reconcile_report: BrokerReconcileReport | None = None

    def execute_orders(
        self,
        orders: list[Order],
        *,
        account_label: str,
        dry_run: bool,
        target_source: str | None = None,
        target_asof: str | None = None,
        target_input_path: str | None = None,
    ) -> list[Order]:
        if not orders:
            return []

        account = self.adapter.resolve_account(account_label)
        state = self.state_store.load(self.adapter.backend_name, account.label)
        state.broker_name = self.adapter.backend_name
        state.account_label = account.label
        state = self._apply_manual_kill_switch(state)
        if not dry_run:
            state = self._reconcile_state(state, account)
            market_data = self._load_market_data(orders)
        else:
            market_data = {}

        executed_orders: list[Order] = []
        for order in orders:
            intent = self._build_intent(
                order,
                account=account,
                target_source=target_source,
                target_asof=target_asof,
                target_input_path=target_input_path,
            )
            parent = self._ensure_parent(state, intent)
            child = self._ensure_child(state, parent, intent, order)
            order.intent_id = intent.intent_id
            order.parent_order_id = parent.parent_order_id
            order.child_order_id = child.child_order_id
            order.broker_name = self.adapter.backend_name
            order.account_label = account.label

            if dry_run:
                order.status = "DRY_RUN"
                order.order_id = f"dry_run_{intent.intent_id[:12]}"
                order.remaining_quantity = float(order.quantity)
                executed_orders.append(order)
                continue

            if state.kill_switch_active:
                self._mark_tracked_order_blocked(
                    parent,
                    child,
                    reason=state.kill_switch_reason or "kill switch active",
                )
                self._mark_order_blocked(order, reason=state.kill_switch_reason or "kill switch active")
                executed_orders.append(order)
                continue

            decisions = self.risk_chain.evaluate(order, quote=market_data.get(order.symbol))
            order.risk_decisions = [decision.to_payload() for decision in decisions]
            blocked = next((decision for decision in decisions if decision.outcome == "BLOCK"), None)
            if blocked is not None:
                self._mark_tracked_order_blocked(parent, child, reason=blocked.reason)
                self._mark_order_blocked(order, reason=blocked.reason)
                executed_orders.append(order)
                continue

            existing = self._get_existing_open_broker_order(state, intent.intent_id)
            if existing is not None:
                self._apply_broker_record(order, existing, child=child)
                executed_orders.append(order)
                continue

            request = BrokerOrderRequest(
                symbol=order.symbol,
                quantity=float(order.quantity),
                side=order.side,
                order_type=order.order_type,
                limit_price=order.price if order.order_type.upper() == "LIMIT" else None,
                client_order_id=child.child_order_id,
                account=account,
            )
            try:
                broker_order = self.adapter.submit_order(request)
                child.broker_order_id = broker_order.broker_order_id
                child.client_order_id = broker_order.client_order_id or child.child_order_id
                child.status = broker_order.status
                child.updated_at = utc_now_iso()
                self._upsert_broker_order(state, broker_order)
                try:
                    self._record_fill_events(state, intent, parent, broker_order, account)
                except Exception as exc:
                    logger.warning(
                        "Fill lookup failed after submit for %s (%s): %s",
                        order.symbol,
                        broker_order.broker_order_id,
                        exc,
                    )
                self._apply_broker_record(order, broker_order, child=child)
                state.consecutive_failures = 0
                state.kill_switch_active = False
                state.kill_switch_reason = None
            except Exception as exc:
                state.consecutive_failures += 1
                self._apply_auto_kill_switch(state)
                self._mark_tracked_order_failed(parent, child, message=str(exc))
                order.status = "FAILED"
                order.error_message = str(exc)
                order.remaining_quantity = float(order.quantity)
                logger.error("Broker submit failed for %s: %s", order.symbol, exc)
            executed_orders.append(order)

        self.state_store.save(state)
        return executed_orders

    def reconcile(
        self,
        *,
        account_label: str,
    ) -> ExecutionReconcileResult:
        """Run a manual reconcile pass and persist the merged state."""

        account = self.adapter.resolve_account(account_label)
        state = self.state_store.load(self.adapter.backend_name, account.label)
        state.broker_name = self.adapter.backend_name
        state.account_label = account.label
        state = self._apply_manual_kill_switch(state)
        before_orders = {
            broker_order.broker_order_id: broker_order for broker_order in state.broker_orders
        }
        before_fill_counts = Counter(fill.broker_order_id for fill in state.fill_events if fill.broker_order_id)
        before_fills = len(state.fill_events)
        report, refreshed_orders = self._fetch_and_merge_reconcile_report(state, account)
        changed_orders = build_reconcile_deltas(
            before_orders=before_orders,
            after_orders=state.broker_orders,
            before_fill_counts=before_fill_counts,
            fill_events=state.fill_events,
        )
        state_path = self.state_store.save(state)
        return ExecutionReconcileResult(
            report=report,
            state=state,
            state_path=state_path,
            new_fill_events=max(0, len(state.fill_events) - before_fills),
            refreshed_orders=refreshed_orders,
            changed_orders=changed_orders,
        )

    def cancel_order(
        self,
        *,
        account_label: str,
        order_ref: str,
    ) -> ExecutionCancelResult:
        """Cancel a tracked order by broker_order_id, client_order_id, or child_order_id."""

        account = self.adapter.resolve_account(account_label)
        state = self.state_store.load(self.adapter.backend_name, account.label)
        state.broker_name = self.adapter.backend_name
        state.account_label = account.label
        target = find_tracked_broker_order(state, order_ref)
        if target is None:
            raise ValueError(
                f"tracked order not found for ref '{order_ref}' in {self.adapter.backend_name}/{account.label}"
            )
        outcome = self._cancel_tracked_broker_order(
            state=state,
            account=account,
            target=target,
            order_ref=order_ref,
        )
        outcome.state_path = self.state_store.save(state)
        return outcome

    def cancel_all_open_orders(
        self,
        *,
        account_label: str,
    ) -> ExecutionBulkCancelResult:
        """Cancel all locally tracked open broker orders for an account."""

        account = self.adapter.resolve_account(account_label)
        state = self.state_store.load(self.adapter.backend_name, account.label)
        state.broker_name = self.adapter.backend_name
        state.account_label = account.label
        targets = sorted(
            (
                broker_order
                for broker_order in state.broker_orders
                if broker_order.status in OPEN_BROKER_STATUSES
            ),
            key=lambda record: (record.updated_at, record.submitted_at, record.broker_order_id),
            reverse=True,
        )

        warnings: list[str] = []
        results: list[ExecutionCancelResult] = []
        for target in targets:
            try:
                outcome = self._cancel_tracked_broker_order(
                    state=state,
                    account=account,
                    target=target,
                    order_ref=target.broker_order_id,
                )
            except Exception as exc:
                message = f"{target.broker_order_id}: {exc}"
                warnings.append(message)
                logger.warning(
                    "Bulk cancel failed for %s (%s/%s): %s",
                    target.broker_order_id,
                    self.adapter.backend_name,
                    account.label,
                    exc,
                )
                continue
            results.append(outcome)

        state_path = (
            self.state_store.save(state)
            if results
            else self.state_store.path_for(self.adapter.backend_name, account.label)
        )
        for outcome in results:
            outcome.state_path = state_path
        return ExecutionBulkCancelResult(
            broker_name=self.adapter.backend_name,
            account_label=account.label,
            state_path=state_path,
            targeted_orders=len(targets),
            results=results,
            warnings=warnings,
        )

    def get_tracked_order(
        self,
        *,
        account_label: str,
        order_ref: str,
    ) -> ExecutionTrackedOrder:
        """Return tracked order details from local execution state."""

        context = resolve_tracked_order_context(
            self.adapter,
            self.state_store,
            account_label,
            order_ref,
        )
        account = context.account
        state = context.state
        child = context.child
        parent = context.parent
        intent = context.intent
        broker_order = context.broker_order
        fills: list[ExecutionFillEvent] = []
        if broker_order is not None:
            fills.extend(
                fill
                for fill in state.fill_events
                if fill.broker_order_id == broker_order.broker_order_id
            )
        elif parent is not None:
            fills.extend(
                fill
                for fill in state.fill_events
                if fill.parent_order_id == parent.parent_order_id
            )
        state_path = self.state_store.path_for(self.adapter.backend_name, account.label)
        return ExecutionTrackedOrder(
            broker_name=self.adapter.backend_name,
            account_label=account.label,
            order_ref=order_ref,
            state_path=state_path,
            intent=intent,
            parent=parent,
            child=child,
            broker_order=broker_order,
            fill_events=fills,
        )

    def get_order_trace(
        self,
        *,
        account_label: str,
        order_ref: str,
    ) -> ExecutionOrderTrace:
        """Return a merged local and broker-side trace for one tracked order."""

        context = resolve_tracked_order_context(
            self.adapter,
            self.state_store,
            account_label,
            order_ref,
        )
        account = context.account
        state = context.state
        child = context.child
        parent = context.parent
        intent = context.intent
        broker_order = context.broker_order

        if parent is not None:
            child_orders = sorted(
                [
                    candidate
                    for candidate in state.child_orders
                    if candidate.parent_order_id == parent.parent_order_id
                ],
                key=lambda candidate: (
                    candidate.attempt,
                    candidate.created_at,
                    candidate.updated_at,
                    candidate.child_order_id,
                ),
            )
        elif child is not None:
            child_orders = [child]
        else:
            child_orders = []

        broker_order_ids: list[str] = []
        for candidate in child_orders:
            if candidate.broker_order_id and candidate.broker_order_id not in broker_order_ids:
                broker_order_ids.append(candidate.broker_order_id)
        if (
            broker_order is not None
            and broker_order.broker_order_id
            and broker_order.broker_order_id not in broker_order_ids
        ):
            broker_order_ids.append(broker_order.broker_order_id)

        tracked_broker_orders = sorted(
            [
                record
                for record in state.broker_orders
                if record.broker_order_id in broker_order_ids
            ],
            key=lambda record: (record.submitted_at, record.updated_at, record.broker_order_id),
        )

        if parent is not None:
            fill_events = sorted(
                [
                    fill
                    for fill in state.fill_events
                    if fill.parent_order_id == parent.parent_order_id
                ],
                key=lambda fill: (fill.filled_at, fill.fill_id),
            )
        else:
            fill_events = sorted(
                [
                    fill
                    for fill in state.fill_events
                    if fill.broker_order_id in broker_order_ids
                ],
                key=lambda fill: (fill.filled_at, fill.fill_id),
            )

        broker_history_orders, broker_history_fills, warnings = self._load_broker_history_trace(
            account=account,
            broker_order_ids=broker_order_ids,
        )

        state_path = self.state_store.path_for(self.adapter.backend_name, account.label)
        return ExecutionOrderTrace(
            broker_name=self.adapter.backend_name,
            account_label=account.label,
            order_ref=order_ref,
            state_path=state_path,
            intent=intent,
            parent=parent,
            child=child,
            broker_order=broker_order,
            child_orders=child_orders,
            tracked_broker_orders=tracked_broker_orders,
            fill_events=fill_events,
            broker_history_orders=broker_history_orders,
            broker_history_fills=broker_history_fills,
            warnings=warnings,
        )

    def list_exception_orders(
        self,
        *,
        account_label: str,
        statuses: set[str] | None = None,
    ) -> list[ExecutionExceptionRecord]:
        """Return local exception records for tracked orders."""

        account = self.adapter.resolve_account(account_label)
        state = self.state_store.load(self.adapter.backend_name, account.label)
        normalized_statuses = {
            str(status).strip().upper()
            for status in (statuses or DEFAULT_EXCEPTION_STATUSES)
            if str(status).strip()
        }
        broker_orders_by_id = {
            broker_order.broker_order_id: broker_order
            for broker_order in state.broker_orders
            if broker_order.broker_order_id
        }
        results: list[ExecutionExceptionRecord] = []

        for parent in state.parent_orders:
            children = [
                child for child in state.child_orders if child.parent_order_id == parent.parent_order_id
            ]
            if not children:
                continue
            latest_child = sorted(children, key=lambda child: child.attempt)[-1]
            broker_order = (
                broker_orders_by_id.get(latest_child.broker_order_id)
                if latest_child.broker_order_id
                else None
            )
            status = broker_order.status if broker_order is not None else latest_child.status
            if status not in normalized_statuses:
                continue
            results.append(
                ExecutionExceptionRecord(
                    broker_name=self.adapter.backend_name,
                    account_label=account.label,
                    symbol=parent.symbol,
                    side=parent.side,
                    status=status,
                    parent_order_id=parent.parent_order_id,
                    child_order_id=latest_child.child_order_id,
                    broker_order_id=broker_order.broker_order_id if broker_order is not None else None,
                    client_order_id=broker_order.client_order_id if broker_order is not None else latest_child.client_order_id,
                    source="broker" if broker_order is not None else "local",
                    message=broker_order.message if broker_order is not None else latest_child.message,
                    filled_quantity=(
                        float(broker_order.filled_quantity or 0.0)
                        if broker_order is not None
                        else float(parent.filled_quantity or 0.0)
                    ),
                    remaining_quantity=(
                        broker_order.remaining_quantity
                        if broker_order is not None
                        else float(parent.remaining_quantity or 0.0)
                    ),
                    updated_at=(
                        broker_order.updated_at
                        if broker_order is not None
                        else latest_child.updated_at
                    ),
                )
            )

        return sorted(
            results,
            key=lambda item: (item.updated_at or "", item.parent_order_id),
            reverse=True,
        )

    def _load_broker_history_trace(
        self,
        *,
        account: ResolvedBrokerAccount,
        broker_order_ids: list[str],
    ) -> tuple[list[BrokerOrderRecord], list[BrokerFillRecord], list[str]]:
        warnings: list[str] = []
        broker_history_orders: list[BrokerOrderRecord] = []
        broker_history_fills: list[BrokerFillRecord] = []
        if not broker_order_ids:
            return broker_history_orders, broker_history_fills, warnings

        if self.adapter.capabilities.supports_order_history:
            for broker_order_id in broker_order_ids:
                try:
                    broker_history_orders.extend(
                        self.adapter.list_order_history(account, broker_order_id=broker_order_id)
                    )
                except UnsupportedBrokerOperationError as exc:
                    warnings.append(f"broker-side order history unavailable: {exc}")
                    break
                except Exception as exc:
                    warnings.append(
                        f"failed to load broker-side order history for {broker_order_id}: {exc}"
                    )
        else:
            warnings.append(
                f"{self.adapter.backend_name} does not support broker-side order history"
            )

        if self.adapter.capabilities.supports_fill_history:
            for broker_order_id in broker_order_ids:
                try:
                    broker_history_fills.extend(
                        self.adapter.list_fill_history(account, broker_order_id=broker_order_id)
                    )
                except UnsupportedBrokerOperationError as exc:
                    warnings.append(f"broker-side fill history unavailable: {exc}")
                    break
                except Exception as exc:
                    warnings.append(
                        f"failed to load broker-side fill history for {broker_order_id}: {exc}"
                    )
        else:
            warnings.append(
                f"{self.adapter.backend_name} does not support broker-side fill history"
            )

        unique_orders: dict[str, BrokerOrderRecord] = {}
        for record in broker_history_orders:
            unique_orders[record.broker_order_id] = record
        unique_fills: dict[str, BrokerFillRecord] = {}
        for record in broker_history_fills:
            unique_fills[record.fill_id] = record

        return (
            sorted(
                unique_orders.values(),
                key=lambda record: (record.submitted_at, record.updated_at, record.broker_order_id),
            ),
            sorted(
                unique_fills.values(),
                key=lambda record: (record.filled_at, record.broker_order_id, record.fill_id),
            ),
            warnings,
        )
