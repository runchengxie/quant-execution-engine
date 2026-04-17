"""Recovery action methods for OrderLifecycleService."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .broker.base import BrokerOrderRequest, utc_now_iso
from .execution_state import (
    FAILURE_BROKER_STATUSES,
    OPEN_BROKER_STATUSES,
    STALE_RETRY_EXCLUDED_STATUSES,
    ExecutionAcceptPartialResult,
    ExecutionCancelResult,
    ExecutionRepriceResult,
    ExecutionResumeRemainingResult,
    ExecutionRetryResult,
    ExecutionStaleRetryResult,
    ExecutionState,
)
from .execution_helpers import (
    broker_order_is_open,
    load_account_state,
    require_latest_child_attempt,
    require_partial_fill_quantities,
    resolve_tracked_order_context,
)
from .logging import get_logger
from .models import Order
from .execution_service_state_reconcile_ops import OrderLifecycleStateReconcileOpsMixin

logger = get_logger(__name__)


class OrderLifecycleRecoveryActionsMixin(OrderLifecycleStateReconcileOpsMixin):
    def retry_order(
        self,
        *,
        account_label: str,
        order_ref: str,
    ) -> ExecutionRetryResult:
        """Retry a zero-fill failed or canceled tracked order."""

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
        if child is None or parent is None or intent is None:
            raise ValueError("tracked order is incomplete and cannot be retried")
        require_latest_child_attempt(
            state,
            parent=parent,
            child=child,
            action_name="retry",
        )

        broker_status = broker_order.status if broker_order is not None else child.status
        if broker_status in OPEN_BROKER_STATUSES:
            raise ValueError(f"tracked order is still open: {broker_status}")
        if parent.filled_quantity > 0:
            raise ValueError("retry for partially filled orders is not supported yet")
        if broker_status not in FAILURE_BROKER_STATUSES and child.status != "FAILED":
            raise ValueError(
                f"retry only supports failed/canceled/rejected/expired orders, got: {broker_status}"
            )

        quantity = float(intent.quantity)
        if not quantity.is_integer():
            raise ValueError("retry currently only supports integer-share tracked orders")

        order = Order(
            symbol=intent.symbol,
            quantity=int(quantity),
            side=intent.side,
            price=intent.limit_price,
            order_type=intent.order_type,
        )
        retried = self.execute_orders(
            [order],
            account_label=account_label,
            dry_run=False,
            target_source=intent.target_source,
            target_asof=intent.target_asof,
            target_input_path=intent.target_input_path,
        )[0]
        state_path = self.state_store.path_for(self.adapter.backend_name, account.label)
        return ExecutionRetryResult(
            broker_name=self.adapter.backend_name,
            account_label=account.label,
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

        context = resolve_tracked_order_context(
            self.adapter,
            self.state_store,
            account_label,
            order_ref,
        )
        parent = context.parent
        child = context.child
        broker_order = context.broker_order
        if parent is None or broker_order is None:
            raise ValueError("tracked order is incomplete and cannot cancel the remaining quantity")
        require_latest_child_attempt(
            context.state,
            parent=parent,
            child=child,
            action_name="cancel-rest",
        )
        require_partial_fill_quantities(parent, action_name="cancel-rest")
        if not broker_order_is_open(broker_order):
            raise ValueError(
                f"cancel-rest only supports open tracked broker orders, got: {broker_order.status}"
            )
        return self.cancel_order(account_label=account_label, order_ref=order_ref)

    def resume_remaining_order(
        self,
        *,
        account_label: str,
        order_ref: str,
    ) -> ExecutionResumeRemainingResult:
        """Submit a new child attempt for the remaining quantity after a partial fill."""

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
        if child is None or parent is None or intent is None:
            raise ValueError("tracked order is incomplete and cannot resume remaining quantity")
        require_latest_child_attempt(
            state,
            parent=parent,
            child=child,
            action_name="resume-remaining",
        )
        if parent.metadata.get("manual_resolution") == "accepted_partial":
            raise ValueError("remaining quantity was already accepted locally; resume is disabled")
        _, remaining_quantity = require_partial_fill_quantities(
            parent,
            action_name="resume-remaining",
        )
        if broker_order_is_open(broker_order):
            raise ValueError(
                "tracked broker order is still open; cancel the remaining quantity before resubmitting it"
            )

        quantity = remaining_quantity
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
        broker_order = context.broker_order
        if child is None or parent is None:
            raise ValueError("tracked order is incomplete and cannot accept a partial fill")
        require_latest_child_attempt(
            state,
            parent=parent,
            child=child,
            action_name="accept-partial",
        )
        accepted_filled, abandoned_remaining = require_partial_fill_quantities(
            parent,
            action_name="accept-partial",
        )
        if broker_order_is_open(broker_order):
            raise ValueError(
                "tracked broker order is still open; cancel the remaining quantity before accepting the partial fill"
            )

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
        if child is None or parent is None or intent is None or broker_order is None:
            raise ValueError("tracked order is incomplete and cannot be repriced")
        require_latest_child_attempt(
            state,
            parent=parent,
            child=child,
            action_name="reprice",
        )
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

        account, state = load_account_state(
            self.adapter,
            self.state_store,
            account_label,
        )
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
