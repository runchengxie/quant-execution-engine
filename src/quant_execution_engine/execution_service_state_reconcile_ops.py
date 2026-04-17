"""State/reconcile operations for OrderLifecycleService."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

from .broker.base import (
    BrokerOrderRecord,
    BrokerReconcileReport,
    ResolvedBrokerAccount,
    utc_now_iso,
)
from .execution_state import (
    FAILURE_BROKER_STATUSES,
    OPEN_BROKER_STATUSES,
    STALE_RETRY_EXCLUDED_STATUSES,
    SUCCESS_BROKER_STATUSES,
    TERMINAL_BROKER_STATUSES,
    ChildOrder,
    ExecutionCancelResult,
    ExecutionFillEvent,
    ExecutionState,
    OrderIntent,
    ParentOrder,
)
from .execution_helpers import find_parent_for_fill, load_account_state
from .logging import get_logger
from .models import Order
from .risk import RiskDecision, get_kill_switch_config, is_manual_kill_switch_active

logger = get_logger(__name__)


def _intent_limit_price(order: Order) -> float | None:
    if str(order.order_type).upper() != "LIMIT":
        return None
    return float(order.price) if order.price is not None else None


class OrderLifecycleStateReconcileOpsMixin:
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
