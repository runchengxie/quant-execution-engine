"""Intent / parent / child build + kill-switch + stale-retry helpers.

This is the first layer of :class:`OrderLifecycleStateReconcileOpsMixin`
(intent/parent/child construction, kill-switch handling, stale-retry targeting).
The states/order-record mutation layer lives in ``_reconcile_ops_state``.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from .broker.base import BrokerAdapter, BrokerOrderRecord, ResolvedBrokerAccount, utc_now_iso
from .execution_state import (
    OPEN_BROKER_STATUSES,
    STALE_RETRY_EXCLUDED_STATUSES,
    ChildOrder,
    ExecutionState,
    ExecutionStateStore,
    OrderIntent,
    ParentOrder,
)
from .logging import get_logger
from .models import Order
from .risk import RiskGateChain, get_kill_switch_config, is_manual_kill_switch_active

logger = get_logger(__name__)


def _intent_limit_price(order: Order) -> float | None:
    if str(order.order_type).upper() != "LIMIT":
        return None
    return float(order.price) if order.price is not None else None


class OrderLifecycleReconcileOpsIntentMixin:
    adapter: BrokerAdapter
    state_store: ExecutionStateStore
    risk_chain: RiskGateChain

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
            quotes = self.adapter.get_quotes(symbols, include_depth=True)
            return dict(quotes)
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
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)

    def _timestamp_for_stale_retry(
        self,
        broker_order: BrokerOrderRecord,
    ) -> datetime | None:
        return self._parse_utc_timestamp(broker_order.updated_at) or self._parse_utc_timestamp(
            broker_order.submitted_at
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
                    f"{broker_order.broker_order_id}: skipped stale retry because "
                    "timestamp is missing or invalid"
                )
                continue
            if timestamp > cutoff:
                continue
            targets.append(broker_order)
        return targets
