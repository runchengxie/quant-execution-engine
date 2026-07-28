"""Reprice recovery action for OrderLifecycleService.

Builds on :class:`OrderLifecycleRecoverySingleMixin`: cancel-and-resubmit a tracked
open LIMIT order at a new price (``reprice_order``).
"""

from __future__ import annotations

from ._recovery_actions_single import OrderLifecycleRecoverySingleMixin
from .broker.base import utc_now_iso
from .execution_helpers import require_latest_child_attempt, resolve_tracked_order_context
from .execution_state import (
    OPEN_BROKER_STATUSES,
    STALE_RETRY_EXCLUDED_STATUSES,
    ExecutionRepriceResult,
)
from .logging import get_logger
from .models import Order

logger = get_logger(__name__)


class OrderLifecycleRecoveryRepriceMixin(OrderLifecycleRecoverySingleMixin):
    """Reprice (cancel + resubmit at new limit) recovery action."""

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
        if (
            float(parent.filled_quantity or 0.0) > 0
            or float(broker_order.filled_quantity or 0.0) > 0
        ):
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
                warnings.append(
                    "replacement skipped because fractional tracked quantity is not supported yet"
                )
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
