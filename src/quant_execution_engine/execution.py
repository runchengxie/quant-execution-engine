"""Execution lifecycle service and reconcile coordinator."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

from .broker.base import (
    BrokerAdapter,
    BrokerOrderRecord,
    BrokerOrderRequest,
    BrokerReconcileReport,
    ResolvedBrokerAccount,
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
    build_reconcile_deltas,
    find_parent_for_fill,
    find_tracked_broker_order,
    resolve_tracked_order,
)
from .logging import get_logger
from .models import Order
from .risk import RiskDecision, RiskGateChain, get_kill_switch_config, is_manual_kill_switch_active

logger = get_logger(__name__)


def _intent_limit_price(order: Order) -> float | None:
    if str(order.order_type).upper() != "LIMIT":
        return None
    return float(order.price) if order.price is not None else None


class OrderLifecycleService:
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

        account = self.adapter.resolve_account(account_label)
        state = self.state_store.load(self.adapter.backend_name, account.label)
        resolved = resolve_tracked_order(state, order_ref)
        if resolved is None:
            raise ValueError(
                f"tracked order not found for ref '{order_ref}' in {self.adapter.backend_name}/{account.label}"
            )
        child, parent, intent, broker_order = resolved
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

    def retry_order(
        self,
        *,
        account_label: str,
        order_ref: str,
    ) -> ExecutionRetryResult:
        """Retry a zero-fill failed or canceled tracked order."""

        tracked = self.get_tracked_order(account_label=account_label, order_ref=order_ref)
        if tracked.child is None or tracked.parent is None or tracked.intent is None:
            raise ValueError("tracked order is incomplete and cannot be retried")

        broker_status = tracked.broker_order.status if tracked.broker_order is not None else tracked.child.status
        if broker_status in OPEN_BROKER_STATUSES:
            raise ValueError(f"tracked order is still open: {broker_status}")
        if tracked.parent.filled_quantity > 0:
            raise ValueError("retry for partially filled orders is not supported yet")
        if broker_status not in FAILURE_BROKER_STATUSES and tracked.child.status != "FAILED":
            raise ValueError(
                f"retry only supports failed/canceled/rejected/expired orders, got: {broker_status}"
            )

        quantity = float(tracked.intent.quantity)
        if not quantity.is_integer():
            raise ValueError("retry currently only supports integer-share tracked orders")

        order = Order(
            symbol=tracked.intent.symbol,
            quantity=int(quantity),
            side=tracked.intent.side,
            price=tracked.intent.limit_price,
            order_type=tracked.intent.order_type,
        )
        retried = self.execute_orders(
            [order],
            account_label=account_label,
            dry_run=False,
            target_source=tracked.intent.target_source,
            target_asof=tracked.intent.target_asof,
            target_input_path=tracked.intent.target_input_path,
        )[0]
        state_path = self.state_store.path_for(self.adapter.backend_name, tracked.account_label)
        return ExecutionRetryResult(
            broker_name=self.adapter.backend_name,
            account_label=tracked.account_label,
            order_ref=order_ref,
            new_child_order_id=str(retried.child_order_id),
            broker_order_id=retried.broker_order_id,
            broker_status=retried.broker_status,
            state_path=state_path,
            warnings=[],
        )

    def cancel_remaining_order(
        self,
        *,
        account_label: str,
        order_ref: str,
    ) -> ExecutionCancelResult:
        """Cancel the open remainder of a partially filled tracked order."""

        tracked = self.get_tracked_order(account_label=account_label, order_ref=order_ref)
        if tracked.parent is None or tracked.broker_order is None:
            raise ValueError("tracked order is incomplete and cannot cancel the remaining quantity")
        if float(tracked.parent.filled_quantity or 0.0) <= 0 or float(
            tracked.parent.remaining_quantity or 0.0
        ) <= 0:
            raise ValueError("cancel-rest only applies to partially filled tracked orders")
        if tracked.broker_order.status not in OPEN_BROKER_STATUSES:
            raise ValueError(
                f"cancel-rest only supports open tracked broker orders, got: {tracked.broker_order.status}"
            )
        return self.cancel_order(account_label=account_label, order_ref=order_ref)

    def resume_remaining_order(
        self,
        *,
        account_label: str,
        order_ref: str,
    ) -> ExecutionResumeRemainingResult:
        """Submit a new child attempt for the remaining quantity after a partial fill."""

        account = self.adapter.resolve_account(account_label)
        state = self.state_store.load(self.adapter.backend_name, account.label)
        state.broker_name = self.adapter.backend_name
        state.account_label = account.label
        resolved = resolve_tracked_order(state, order_ref)
        if resolved is None:
            raise ValueError(
                f"tracked order not found for ref '{order_ref}' in {self.adapter.backend_name}/{account.label}"
            )
        child, parent, intent, broker_order = resolved
        if child is None or parent is None or intent is None:
            raise ValueError("tracked order is incomplete and cannot resume remaining quantity")
        if parent.metadata.get("manual_resolution") == "accepted_partial":
            raise ValueError("remaining quantity was already accepted locally; resume is disabled")
        if float(parent.filled_quantity or 0.0) <= 0 or float(parent.remaining_quantity or 0.0) <= 0:
            raise ValueError("resume-remaining only applies to partially filled tracked orders")
        if broker_order is not None and broker_order.status in OPEN_BROKER_STATUSES:
            raise ValueError(
                "tracked broker order is still open; cancel the remaining quantity before resubmitting it"
            )

        quantity = float(parent.remaining_quantity or 0.0)
        if not quantity.is_integer():
            raise ValueError("resume-remaining currently only supports integer-share tracked orders")

        order = Order(
            symbol=intent.symbol,
            quantity=int(quantity),
            side=intent.side,
            price=intent.limit_price,
            order_type=intent.order_type,
        )
        new_child = self._ensure_child(state, parent, intent, order)
        parent.metadata["last_resume_remaining_at"] = utc_now_iso()
        warnings: list[str] = []
        new_broker_order_id, broker_status = self._submit_child_attempt(
            state=state,
            parent=parent,
            intent=intent,
            child=new_child,
            account=account,
            order=order,
            warnings=warnings,
            failure_prefix="resume submit failed",
        )
        state_path = self.state_store.save(state)
        return ExecutionResumeRemainingResult(
            broker_name=self.adapter.backend_name,
            account_label=account.label,
            order_ref=order_ref,
            submitted_quantity=float(order.quantity),
            new_child_order_id=new_child.child_order_id,
            broker_order_id=new_broker_order_id,
            broker_status=broker_status,
            state_path=state_path,
            warnings=warnings,
        )

    def accept_partial_fill(
        self,
        *,
        account_label: str,
        order_ref: str,
    ) -> ExecutionAcceptPartialResult:
        """Accept a partial fill locally and stop expecting the remaining quantity."""

        account = self.adapter.resolve_account(account_label)
        state = self.state_store.load(self.adapter.backend_name, account.label)
        state.broker_name = self.adapter.backend_name
        state.account_label = account.label
        resolved = resolve_tracked_order(state, order_ref)
        if resolved is None:
            raise ValueError(
                f"tracked order not found for ref '{order_ref}' in {self.adapter.backend_name}/{account.label}"
            )
        child, parent, _intent, broker_order = resolved
        if child is None or parent is None:
            raise ValueError("tracked order is incomplete and cannot accept a partial fill")
        if float(parent.filled_quantity or 0.0) <= 0 or float(parent.remaining_quantity or 0.0) <= 0:
            raise ValueError("accept-partial only applies to partially filled tracked orders")
        if broker_order is not None and broker_order.status in OPEN_BROKER_STATUSES:
            raise ValueError(
                "tracked broker order is still open; cancel the remaining quantity before accepting the partial fill"
            )

        accepted_filled = float(parent.filled_quantity or 0.0)
        abandoned_remaining = float(parent.remaining_quantity or 0.0)
        resolved_at = utc_now_iso()
        parent.status = "ACCEPTED_PARTIAL"
        parent.updated_at = resolved_at
        parent.metadata["manual_resolution"] = "accepted_partial"
        parent.metadata["manual_resolution_at"] = resolved_at
        parent.metadata["accepted_filled_quantity"] = accepted_filled
        parent.metadata["abandoned_remaining_quantity"] = abandoned_remaining
        state_path = self.state_store.save(state)
        return ExecutionAcceptPartialResult(
            broker_name=self.adapter.backend_name,
            account_label=account.label,
            order_ref=order_ref,
            parent_order_id=parent.parent_order_id,
            accepted_filled_quantity=accepted_filled,
            abandoned_remaining_quantity=abandoned_remaining,
            state_path=state_path,
            warnings=[],
        )

    def _submit_child_attempt(
        self,
        *,
        state: ExecutionState,
        parent: ParentOrder,
        intent: OrderIntent,
        child: ChildOrder,
        account: ResolvedBrokerAccount,
        order: Order,
        warnings: list[str],
        failure_prefix: str,
    ) -> tuple[str | None, str | None]:
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
            child.message = broker_order.message
            child.updated_at = utc_now_iso()
            self._upsert_broker_order(state, broker_order)
            try:
                self._record_fill_events(state, intent, parent, broker_order, account)
            except Exception as exc:
                warnings.append(
                    f"fill lookup failed after submit for {broker_order.broker_order_id}: {exc}"
                )
            state.consecutive_failures = 0
            state.kill_switch_active = False
            state.kill_switch_reason = None
            return broker_order.broker_order_id, broker_order.status
        except Exception as exc:
            state.consecutive_failures += 1
            self._apply_auto_kill_switch(state)
            self._mark_tracked_order_failed(parent, child, message=str(exc))
            warnings.append(f"{failure_prefix}: {exc}")
            return None, child.status

    def reprice_order(
        self,
        *,
        account_label: str,
        order_ref: str,
        limit_price: float,
    ) -> ExecutionRepriceResult:
        """Cancel and resubmit a tracked open limit order at a new price."""

        if limit_price <= 0:
            raise ValueError("limit_price must be greater than 0")

        account = self.adapter.resolve_account(account_label)
        state = self.state_store.load(self.adapter.backend_name, account.label)
        state.broker_name = self.adapter.backend_name
        state.account_label = account.label
        resolved = resolve_tracked_order(state, order_ref)
        if resolved is None:
            raise ValueError(
                f"tracked order not found for ref '{order_ref}' in {self.adapter.backend_name}/{account.label}"
            )
        child, parent, intent, broker_order = resolved
        if child is None or parent is None or intent is None or broker_order is None:
            raise ValueError("tracked order is incomplete and cannot be repriced")
        if str(intent.order_type).upper() != "LIMIT":
            raise ValueError("reprice only supports tracked LIMIT orders")
        if broker_order.status not in OPEN_BROKER_STATUSES:
            raise ValueError(f"tracked order is not open: {broker_order.status}")
        if broker_order.status in STALE_RETRY_EXCLUDED_STATUSES:
            raise ValueError(f"tracked order is already pending cancel: {broker_order.status}")
        if float(parent.filled_quantity or 0.0) > 0 or float(broker_order.filled_quantity or 0.0) > 0:
            raise ValueError("reprice for partially filled orders is not supported yet")

        current_limit = float(intent.limit_price or 0.0)
        next_limit = float(limit_price)
        if current_limit > 0 and current_limit == next_limit:
            raise ValueError("new limit_price must differ from the current tracked limit price")

        cancel_outcome = self._cancel_tracked_broker_order(
            state=state,
            account=account,
            target=broker_order,
            order_ref=order_ref,
        )
        warnings = list(cancel_outcome.warnings)
        new_child_order_id: str | None = None
        new_broker_order_id: str | None = None
        broker_status: str | None = None

        if cancel_outcome.status == "CANCELED":
            remaining_quantity = broker_order.remaining_quantity
            if remaining_quantity is None:
                remaining_quantity = float(parent.remaining_quantity or 0.0)
            quantity = float(remaining_quantity or 0.0)
            if quantity <= 0:
                warnings.append("replacement skipped because tracked remaining_quantity is 0")
            elif not quantity.is_integer():
                warnings.append("replacement skipped because fractional tracked quantity is not supported yet")
            else:
                intent.limit_price = next_limit
                intent.metadata["last_reprice_at"] = utc_now_iso()
                intent.metadata["last_reprice_from_limit_price"] = current_limit or None
                order = Order(
                    symbol=intent.symbol,
                    quantity=int(quantity),
                    side=intent.side,
                    price=next_limit,
                    order_type="LIMIT",
                )
                replacement_child = self._ensure_child(state, parent, intent, order)
                new_child_order_id = replacement_child.child_order_id
                new_broker_order_id, broker_status = self._submit_child_attempt(
                    state=state,
                    parent=parent,
                    intent=intent,
                    child=replacement_child,
                    account=account,
                    order=order,
                    warnings=warnings,
                    failure_prefix="replacement submit failed",
                )
        else:
            warnings.append(
                f"replacement skipped because cancel completed with status {cancel_outcome.status}"
            )

        state_path = self.state_store.save(state)
        return ExecutionRepriceResult(
            broker_name=self.adapter.backend_name,
            account_label=account.label,
            order_ref=order_ref,
            old_broker_order_id=broker_order.broker_order_id,
            cancel_status=cancel_outcome.status,
            old_limit_price=(current_limit or None),
            new_limit_price=next_limit,
            new_child_order_id=new_child_order_id,
            broker_order_id=new_broker_order_id,
            broker_status=broker_status,
            state_path=state_path,
            warnings=warnings,
        )

    def retry_stale_orders(
        self,
        *,
        account_label: str,
        older_than_minutes: int,
    ) -> ExecutionStaleRetryResult:
        """Cancel and retry locally tracked stale open orders with zero fills."""

        if older_than_minutes <= 0:
            raise ValueError("older_than_minutes must be greater than 0")

        account = self.adapter.resolve_account(account_label)
        state = self.state_store.load(self.adapter.backend_name, account.label)
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=int(older_than_minutes))
        warnings: list[str] = []
        targets = sorted(
            self._find_stale_retry_targets(state, cutoff=cutoff, warnings=warnings),
            key=lambda record: (
                self._timestamp_for_stale_retry(record) or datetime.min.replace(tzinfo=timezone.utc),
                record.broker_order_id,
            ),
        )

        cancel_results: list[ExecutionCancelResult] = []
        retry_results: list[ExecutionRetryResult] = []
        for target in targets:
            try:
                cancel_outcome = self.cancel_order(
                    account_label=account.label,
                    order_ref=target.broker_order_id,
                )
            except Exception as exc:
                message = f"{target.broker_order_id}: cancel failed: {exc}"
                warnings.append(message)
                logger.warning(
                    "Stale retry cancel failed for %s (%s/%s): %s",
                    target.broker_order_id,
                    self.adapter.backend_name,
                    account.label,
                    exc,
                )
                continue
            cancel_results.append(cancel_outcome)
            if cancel_outcome.status != "CANCELED":
                warnings.append(
                    f"{target.broker_order_id}: skipped retry because post-cancel status is {cancel_outcome.status}"
                )
                continue
            try:
                retry_outcome = self.retry_order(
                    account_label=account.label,
                    order_ref=target.broker_order_id,
                )
            except Exception as exc:
                message = f"{target.broker_order_id}: retry failed: {exc}"
                warnings.append(message)
                logger.warning(
                    "Stale retry submit failed for %s (%s/%s): %s",
                    target.broker_order_id,
                    self.adapter.backend_name,
                    account.label,
                    exc,
                )
                continue
            retry_results.append(retry_outcome)

        return ExecutionStaleRetryResult(
            broker_name=self.adapter.backend_name,
            account_label=account.label,
            state_path=self.state_store.path_for(self.adapter.backend_name, account.label),
            older_than_minutes=int(older_than_minutes),
            targeted_orders=len(targets),
            cancel_results=cancel_results,
            retry_results=retry_results,
            warnings=warnings,
        )

    def _build_intent(
        self,
        order: Order,
        *,
        account: ResolvedBrokerAccount,
        target_source: str | None,
        target_asof: str | None,
        target_input_path: str | None,
    ) -> OrderIntent:
        payload = {
            "broker": self.adapter.backend_name,
            "account": account.label,
            "symbol": order.symbol,
            "side": order.side,
            "quantity": order.quantity,
            "order_type": order.order_type,
            "price": _intent_limit_price(order),
            "target_source": target_source,
            "target_asof": target_asof,
            "target_input_path": target_input_path,
        }
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        return OrderIntent(
            intent_id=digest[:24],
            symbol=order.symbol,
            side=order.side,
            quantity=float(order.quantity),
            order_type=order.order_type,
            limit_price=_intent_limit_price(order),
            broker_name=self.adapter.backend_name,
            account_label=account.label,
            target_source=target_source,
            target_asof=target_asof,
            target_input_path=target_input_path,
        )

    def _ensure_parent(
        self,
        state: ExecutionState,
        intent: OrderIntent,
    ) -> ParentOrder:
        for parent in state.parent_orders:
            if parent.intent_id == intent.intent_id:
                return parent
        parent = ParentOrder(
            parent_order_id=f"parent_{intent.intent_id}",
            intent_id=intent.intent_id,
            symbol=intent.symbol,
            side=intent.side,
            requested_quantity=intent.quantity,
            remaining_quantity=intent.quantity,
        )
        state.intents.append(intent)
        state.parent_orders.append(parent)
        return parent

    def _ensure_child(
        self,
        state: ExecutionState,
        parent: ParentOrder,
        intent: OrderIntent,
        order: Order,
    ) -> ChildOrder:
        existing_children = [
            child for child in state.child_orders if child.parent_order_id == parent.parent_order_id
        ]
        if existing_children:
            latest = sorted(existing_children, key=lambda child: child.attempt)[-1]
            if latest.status in OPEN_BROKER_STATUSES and latest.broker_order_id:
                return latest
        attempt = len(existing_children) + 1
        child = ChildOrder(
            child_order_id=f"child_{intent.intent_id}_{attempt}",
            parent_order_id=parent.parent_order_id,
            intent_id=intent.intent_id,
            quantity=float(order.quantity),
            attempt=attempt,
        )
        state.child_orders.append(child)
        parent.child_order_ids.append(child.child_order_id)
        if attempt > 1 and parent.remaining_quantity > 0 and parent.filled_quantity <= 0:
            parent.status = "PENDING"
        parent.updated_at = utc_now_iso()
        return child

    def _get_existing_open_broker_order(
        self,
        state: ExecutionState,
        intent_id: str,
    ) -> BrokerOrderRecord | None:
        child_ids = {
            child.child_order_id
            for child in state.child_orders
            if child.intent_id == intent_id and child.broker_order_id
        }
        if not child_ids:
            return None
        broker_order_ids = {
            child.broker_order_id
            for child in state.child_orders
            if child.child_order_id in child_ids and child.broker_order_id
        }
        for broker_order in state.broker_orders:
            if (
                broker_order.broker_order_id in broker_order_ids
                and broker_order.status in OPEN_BROKER_STATUSES
            ):
                return broker_order
        return None

    def _load_market_data(self, orders: list[Order]) -> dict[str, Any]:
        if not self.risk_chain.needs_market_data():
            return {}
        symbols = sorted({order.symbol for order in orders})
        try:
            return self.adapter.get_quotes(symbols, include_depth=True)
        except Exception as exc:
            logger.warning("Risk market data lookup failed: %s", exc)
            return {}

    def _apply_manual_kill_switch(self, state: ExecutionState) -> ExecutionState:
        active, reason = is_manual_kill_switch_active()
        if active:
            state.kill_switch_active = True
            state.kill_switch_reason = reason
        return state

    def _apply_auto_kill_switch(self, state: ExecutionState) -> None:
        cfg = get_kill_switch_config()
        threshold = int(float(cfg.get("failure_threshold", 0) or 0))
        if threshold > 0 and state.consecutive_failures >= threshold:
            state.kill_switch_active = True
            state.kill_switch_reason = (
                f"automatic kill switch after {state.consecutive_failures} consecutive failures"
            )

    def _reconcile_state(
        self,
        state: ExecutionState,
        account: ResolvedBrokerAccount,
    ) -> ExecutionState:
        try:
            self._fetch_and_merge_reconcile_report(state, account)
        except Exception as exc:
            state.consecutive_failures += 1
            self._apply_auto_kill_switch(state)
            logger.warning("Reconcile failed: %s", exc)
            return state
        return state

    def _fetch_and_merge_reconcile_report(
        self,
        state: ExecutionState,
        account: ResolvedBrokerAccount,
    ) -> tuple[BrokerReconcileReport, int]:
        report = self.adapter.reconcile(account)
        refreshed_orders = self._merge_reconcile_report(state, account, report)
        return report, refreshed_orders

    def _merge_reconcile_report(
        self,
        state: ExecutionState,
        account: ResolvedBrokerAccount,
        report: BrokerReconcileReport,
    ) -> int:
        refreshed_orders = 0

        self.last_reconcile_report = report
        state.last_reconcile_at = report.fetched_at
        for broker_order in report.open_orders:
            self._upsert_broker_order(state, broker_order)
            self._sync_child_from_broker_order(state, broker_order)

        tracked_broker_order_ids = sorted(
            {
                child.broker_order_id
                for child in state.child_orders
                if child.broker_order_id
            }
        )
        open_order_ids = {order.broker_order_id for order in report.open_orders}
        broker_orders_by_id = {
            order.broker_order_id: order
            for order in state.broker_orders
            if order.broker_order_id
        }
        for broker_order_id in tracked_broker_order_ids:
            if broker_order_id in open_order_ids:
                continue
            known = broker_orders_by_id.get(broker_order_id)
            if known is not None and known.status in TERMINAL_BROKER_STATUSES:
                continue
            try:
                broker_order = self.adapter.get_order(broker_order_id, account)
            except Exception as exc:
                report.warnings.append(
                    f"failed to refresh tracked order {broker_order_id}: {exc}"
                )
                continue
            self._upsert_broker_order(state, broker_order)
            self._sync_child_from_broker_order(state, broker_order)
            refreshed_orders += 1

        fill_query_ids = sorted(
            {
                broker_order_id
                for broker_order_id in tracked_broker_order_ids
                if broker_order_id
            }
        )
        for broker_order_id in fill_query_ids:
            try:
                fills = self.adapter.list_fills(account, broker_order_id=broker_order_id)
            except Exception as exc:
                report.warnings.append(
                    f"failed to load fills for tracked order {broker_order_id}: {exc}"
                )
                continue
            for fill in fills:
                self._append_fill_event(state, fill)

        for fill in report.fills:
            self._append_fill_event(state, fill)
        state.consecutive_failures = 0
        return refreshed_orders

    def _record_fill_events(
        self,
        state: ExecutionState,
        intent: OrderIntent,
        parent: ParentOrder,
        broker_order: BrokerOrderRecord,
        account: ResolvedBrokerAccount,
    ) -> None:
        fills = self.adapter.list_fills(account, broker_order_id=broker_order.broker_order_id)
        for fill in fills:
            if any(existing.fill_id == fill.fill_id for existing in state.fill_events):
                continue
            event = ExecutionFillEvent(
                fill_id=fill.fill_id,
                intent_id=intent.intent_id,
                parent_order_id=parent.parent_order_id,
                broker_order_id=broker_order.broker_order_id,
                symbol=fill.symbol,
                quantity=fill.quantity,
                price=fill.price,
                broker_name=fill.broker_name,
                account_label=fill.account_label,
                filled_at=fill.filled_at,
            )
            state.fill_events.append(event)
            self._update_parent_from_fill(parent, event)

    def _cancel_tracked_broker_order(
        self,
        *,
        state: ExecutionState,
        account: ResolvedBrokerAccount,
        target: BrokerOrderRecord,
        order_ref: str,
    ) -> ExecutionCancelResult:
        warnings: list[str] = []
        refreshed = target
        if target.status not in TERMINAL_BROKER_STATUSES:
            self.adapter.cancel_order(target.broker_order_id, account)
            try:
                refreshed = self.adapter.get_order(target.broker_order_id, account)
            except Exception as exc:
                warnings.append(f"cancel submitted but post-cancel refresh failed: {exc}")
                refreshed = self._updated_broker_order_record(target, status="PENDING_CANCEL")
        else:
            warnings.append(f"order already in terminal state: {target.status}")

        self._upsert_broker_order(state, refreshed)
        self._sync_child_from_broker_order(state, refreshed)
        return ExecutionCancelResult(
            broker_name=self.adapter.backend_name,
            account_label=account.label,
            order_ref=order_ref,
            broker_order_id=refreshed.broker_order_id,
            client_order_id=refreshed.client_order_id,
            status=refreshed.status,
            state_path=self.state_store.path_for(self.adapter.backend_name, account.label),
            warnings=warnings,
        )

    def _find_stale_retry_targets(
        self,
        state: ExecutionState,
        *,
        cutoff: datetime,
        warnings: list[str],
    ) -> list[BrokerOrderRecord]:
        targets: list[BrokerOrderRecord] = []
        for broker_order in state.broker_orders:
            if broker_order.status not in OPEN_BROKER_STATUSES:
                continue
            if broker_order.status in STALE_RETRY_EXCLUDED_STATUSES:
                continue
            if float(broker_order.filled_quantity or 0.0) > 0:
                continue
            timestamp = self._timestamp_for_stale_retry(broker_order)
            if timestamp is None:
                warnings.append(
                    f"{broker_order.broker_order_id}: skipped stale retry because timestamp is missing or invalid"
                )
                continue
            if timestamp > cutoff:
                continue
            targets.append(broker_order)
        return targets

    def _timestamp_for_stale_retry(
        self,
        broker_order: BrokerOrderRecord,
    ) -> datetime | None:
        return self._parse_utc_timestamp(broker_order.updated_at) or self._parse_utc_timestamp(
            broker_order.submitted_at
        )

    def _parse_utc_timestamp(self, value: str | None) -> datetime | None:
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

    def _append_fill_event(self, state: ExecutionState, fill: Any) -> None:
        if any(existing.fill_id == fill.fill_id for existing in state.fill_events):
            return
        parent = find_parent_for_fill(state, fill)
        if parent is None:
            return
        event = ExecutionFillEvent(
            fill_id=fill.fill_id,
            intent_id=parent.intent_id,
            parent_order_id=parent.parent_order_id,
            broker_order_id=fill.broker_order_id,
            symbol=fill.symbol,
            quantity=fill.quantity,
            price=fill.price,
            broker_name=fill.broker_name,
            account_label=fill.account_label,
            filled_at=fill.filled_at,
        )
        state.fill_events.append(event)
        self._update_parent_from_fill(parent, event)

    def _update_parent_from_fill(self, parent: ParentOrder, event: ExecutionFillEvent) -> None:
        parent.filled_quantity += float(event.quantity)
        parent.remaining_quantity = max(
            0.0, float(parent.requested_quantity) - float(parent.filled_quantity)
        )
        if parent.remaining_quantity <= 0:
            parent.status = "FILLED"
        elif parent.metadata.get("manual_resolution") == "accepted_partial":
            parent.status = "ACCEPTED_PARTIAL"
        else:
            parent.status = "PARTIALLY_FILLED"
        parent.updated_at = utc_now_iso()

    def _upsert_broker_order(
        self,
        state: ExecutionState,
        broker_order: BrokerOrderRecord,
    ) -> None:
        for index, existing in enumerate(state.broker_orders):
            if existing.broker_order_id == broker_order.broker_order_id:
                state.broker_orders[index] = broker_order
                return
        state.broker_orders.append(broker_order)

    def _updated_broker_order_record(
        self,
        broker_order: BrokerOrderRecord,
        *,
        status: str,
        message: str | None = None,
    ) -> BrokerOrderRecord:
        return BrokerOrderRecord(
            broker_order_id=broker_order.broker_order_id,
            symbol=broker_order.symbol,
            side=broker_order.side,
            quantity=broker_order.quantity,
            broker_name=broker_order.broker_name,
            account_label=broker_order.account_label,
            filled_quantity=broker_order.filled_quantity,
            remaining_quantity=broker_order.remaining_quantity,
            status=status,
            client_order_id=broker_order.client_order_id,
            avg_fill_price=broker_order.avg_fill_price,
            submitted_at=broker_order.submitted_at,
            updated_at=utc_now_iso(),
            message=message or broker_order.message,
            raw=dict(broker_order.raw),
        )

    def _mark_tracked_order_blocked(
        self,
        parent: ParentOrder,
        child: ChildOrder,
        *,
        reason: str,
    ) -> None:
        child.status = "BLOCKED"
        child.message = reason
        child.updated_at = utc_now_iso()
        parent.status = "BLOCKED"
        parent.updated_at = utc_now_iso()

    def _mark_tracked_order_failed(
        self,
        parent: ParentOrder,
        child: ChildOrder,
        *,
        message: str,
    ) -> None:
        child.status = "FAILED"
        child.message = message
        child.updated_at = utc_now_iso()
        parent.status = "FAILED"
        parent.updated_at = utc_now_iso()

    def _sync_child_from_broker_order(
        self,
        state: ExecutionState,
        broker_order: BrokerOrderRecord,
    ) -> None:
        matching_child = next(
            (
                child
                for child in state.child_orders
                if child.broker_order_id == broker_order.broker_order_id
                or (
                    broker_order.client_order_id
                    and child.child_order_id == broker_order.client_order_id
                )
            ),
            None,
        )
        if matching_child is None:
            return
        matching_child.broker_order_id = broker_order.broker_order_id
        matching_child.client_order_id = broker_order.client_order_id or matching_child.client_order_id
        matching_child.status = broker_order.status
        matching_child.message = broker_order.message
        matching_child.updated_at = utc_now_iso()

        parent = next(
            (
                candidate
                for candidate in state.parent_orders
                if candidate.parent_order_id == matching_child.parent_order_id
            ),
            None,
        )
        if parent is None:
            return
        if broker_order.status in FAILURE_BROKER_STATUSES and parent.filled_quantity <= 0:
            parent.status = broker_order.status
            parent.updated_at = utc_now_iso()

    def _apply_broker_record(
        self,
        order: Order,
        broker_order: BrokerOrderRecord,
        *,
        child: ChildOrder,
    ) -> None:
        child.broker_order_id = broker_order.broker_order_id
        child.client_order_id = broker_order.client_order_id or child.client_order_id
        child.status = broker_order.status
        child.message = broker_order.message
        child.updated_at = utc_now_iso()

        order.order_id = broker_order.broker_order_id
        order.broker_order_id = broker_order.broker_order_id
        order.client_order_id = broker_order.client_order_id
        order.broker_status = broker_order.status
        order.filled_quantity = float(broker_order.filled_quantity or 0.0)
        order.remaining_quantity = float(
            broker_order.remaining_quantity
            if broker_order.remaining_quantity is not None
            else max(0.0, float(order.quantity) - float(order.filled_quantity or 0.0))
        )
        order.avg_fill_price = broker_order.avg_fill_price
        order.reconcile_status = "reconciled" if self.last_reconcile_report else None
        if broker_order.status in FAILURE_BROKER_STATUSES:
            order.status = "FAILED"
            order.error_message = broker_order.message
        else:
            order.status = "SUCCESS"

    def _mark_order_blocked(self, order: Order, *, reason: str) -> None:
        order.status = "BLOCKED"
        order.error_message = reason
        order.remaining_quantity = float(order.quantity)
        order.risk_summary = reason
