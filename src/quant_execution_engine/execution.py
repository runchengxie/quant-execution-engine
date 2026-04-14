"""Execution lifecycle models, state store, and submission coordinator."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field, is_dataclass
from pathlib import Path
from typing import Any

from .broker.base import (
    BrokerAdapter,
    BrokerOrderRecord,
    BrokerOrderRequest,
    BrokerReconcileReport,
    ResolvedBrokerAccount,
    utc_now_iso,
)
from .config import load_cfg
from .logging import get_logger, get_run_id
from .models import Order
from .paths import OUTPUTS_DIR
from .risk import RiskDecision, RiskGateChain, get_kill_switch_config, is_manual_kill_switch_active

logger = get_logger(__name__)


OPEN_BROKER_STATUSES = {
    "NEW",
    "ACCEPTED",
    "PENDING_NEW",
    "PENDING_REPLACE",
    "PARTIALLY_FILLED",
    "WAIT_TO_NEW",
    "WAIT_TO_CANCEL",
    "PENDING_CANCEL",
}
SUCCESS_BROKER_STATUSES = {"FILLED"}
FAILURE_BROKER_STATUSES = {"CANCELED", "REJECTED", "EXPIRED", "FAILED"}


@dataclass(slots=True)
class OrderIntent:
    """Stable order intent captured before broker submission."""

    intent_id: str
    symbol: str
    side: str
    quantity: float
    order_type: str
    limit_price: float | None = None
    broker_name: str = "longport"
    account_label: str = "main"
    target_source: str | None = None
    target_asof: str | None = None
    target_input_path: str | None = None
    run_id: str = field(default_factory=get_run_id)
    created_at: str = field(default_factory=utc_now_iso)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ParentOrder:
    """Higher-level execution goal tracked across child orders."""

    parent_order_id: str
    intent_id: str
    symbol: str
    side: str
    requested_quantity: float
    filled_quantity: float = 0.0
    remaining_quantity: float = 0.0
    status: str = "PENDING"
    child_order_ids: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class ChildOrder:
    """Concrete child order attempt attached to a parent order."""

    child_order_id: str
    parent_order_id: str
    intent_id: str
    quantity: float
    attempt: int = 1
    broker_order_id: str | None = None
    client_order_id: str | None = None
    status: str = "PENDING"
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class ExecutionFillEvent:
    """Stored execution fill event."""

    fill_id: str
    intent_id: str
    parent_order_id: str
    broker_order_id: str
    symbol: str
    quantity: float
    price: float
    broker_name: str
    account_label: str
    filled_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class ExecutionState:
    """Persisted execution state."""

    version: int = 1
    broker_name: str = "longport"
    account_label: str = "main"
    updated_at: str = field(default_factory=utc_now_iso)
    consecutive_failures: int = 0
    kill_switch_active: bool = False
    kill_switch_reason: str | None = None
    last_reconcile_at: str | None = None
    intents: list[OrderIntent] = field(default_factory=list)
    parent_orders: list[ParentOrder] = field(default_factory=list)
    child_orders: list[ChildOrder] = field(default_factory=list)
    broker_orders: list[BrokerOrderRecord] = field(default_factory=list)
    fill_events: list[ExecutionFillEvent] = field(default_factory=list)


def _state_dir_from_config() -> Path:
    cfg = load_cfg() or {}
    execution_cfg = cfg.get("execution") or {}
    state_dir = execution_cfg.get("state_dir") if isinstance(execution_cfg, dict) else None
    if state_dir:
        path = Path(str(state_dir))
        if not path.is_absolute():
            path = Path.cwd() / path
        return path
    return OUTPUTS_DIR / "state"


def _jsonable(obj: Any) -> Any:
    if is_dataclass(obj):
        return {key: _jsonable(value) for key, value in asdict(obj).items()}
    if isinstance(obj, list):
        return [_jsonable(item) for item in obj]
    if isinstance(obj, dict):
        return {str(key): _jsonable(value) for key, value in obj.items()}
    return obj


class ExecutionStateStore:
    """File-backed execution state store."""

    def __init__(self, root_dir: Path | None = None) -> None:
        self.root_dir = root_dir or _state_dir_from_config()

    def path_for(self, broker_name: str, account_label: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", account_label or "main")
        return self.root_dir / f"{broker_name}_{safe}.json"

    def load(self, broker_name: str, account_label: str) -> ExecutionState:
        path = self.path_for(broker_name, account_label)
        if not path.exists():
            return ExecutionState(broker_name=broker_name, account_label=account_label)
        raw = json.loads(path.read_text(encoding="utf-8"))
        return ExecutionState(
            version=int(raw.get("version", 1)),
            broker_name=str(raw.get("broker_name") or broker_name),
            account_label=str(raw.get("account_label") or account_label),
            updated_at=str(raw.get("updated_at") or utc_now_iso()),
            consecutive_failures=int(raw.get("consecutive_failures", 0) or 0),
            kill_switch_active=bool(raw.get("kill_switch_active", False)),
            kill_switch_reason=raw.get("kill_switch_reason"),
            last_reconcile_at=raw.get("last_reconcile_at"),
            intents=[OrderIntent(**item) for item in raw.get("intents", [])],
            parent_orders=[ParentOrder(**item) for item in raw.get("parent_orders", [])],
            child_orders=[ChildOrder(**item) for item in raw.get("child_orders", [])],
            broker_orders=[BrokerOrderRecord(**item) for item in raw.get("broker_orders", [])],
            fill_events=[ExecutionFillEvent(**item) for item in raw.get("fill_events", [])],
        )

    def save(self, state: ExecutionState) -> Path:
        path = self.path_for(state.broker_name, state.account_label)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = _jsonable(state)
        payload["updated_at"] = utc_now_iso()
        tmp_path = path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(path)
        return path


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
                self._mark_order_blocked(order, reason=state.kill_switch_reason or "kill switch active")
                executed_orders.append(order)
                continue

            decisions = self.risk_chain.evaluate(order, quote=market_data.get(order.symbol))
            order.risk_decisions = [decision.to_payload() for decision in decisions]
            blocked = next((decision for decision in decisions if decision.outcome == "BLOCK"), None)
            if blocked is not None:
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
                self._record_fill_events(state, intent, parent, broker_order, account)
                self._apply_broker_record(order, broker_order, child=child)
                state.consecutive_failures = 0
                state.kill_switch_active = False
                state.kill_switch_reason = None
            except Exception as exc:
                state.consecutive_failures += 1
                self._apply_auto_kill_switch(state)
                child.status = "FAILED"
                child.updated_at = utc_now_iso()
                order.status = "FAILED"
                order.error_message = str(exc)
                order.remaining_quantity = float(order.quantity)
                logger.error("Broker submit failed for %s: %s", order.symbol, exc)
            executed_orders.append(order)

        self.state_store.save(state)
        return executed_orders

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
            "price": order.price,
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
            limit_price=order.price,
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
            report = self.adapter.reconcile(account)
        except Exception as exc:
            state.consecutive_failures += 1
            self._apply_auto_kill_switch(state)
            logger.warning("Reconcile failed: %s", exc)
            return state

        self.last_reconcile_report = report
        state.last_reconcile_at = report.fetched_at
        for broker_order in report.open_orders:
            self._upsert_broker_order(state, broker_order)
        for fill in report.fills:
            if any(existing.fill_id == fill.fill_id for existing in state.fill_events):
                continue
            matching_parent = next(
                (
                    parent
                    for parent in state.parent_orders
                    if parent.symbol == fill.symbol and parent.status not in {"FILLED", "CANCELED"}
                ),
                None,
            )
            if matching_parent is None:
                continue
            event = ExecutionFillEvent(
                fill_id=fill.fill_id,
                intent_id=matching_parent.intent_id,
                parent_order_id=matching_parent.parent_order_id,
                broker_order_id=fill.broker_order_id,
                symbol=fill.symbol,
                quantity=fill.quantity,
                price=fill.price,
                broker_name=fill.broker_name,
                account_label=fill.account_label,
                filled_at=fill.filled_at,
            )
            state.fill_events.append(event)
            self._update_parent_from_fill(matching_parent, event)
        state.consecutive_failures = 0
        return state

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

    def _update_parent_from_fill(self, parent: ParentOrder, event: ExecutionFillEvent) -> None:
        parent.filled_quantity += float(event.quantity)
        parent.remaining_quantity = max(
            0.0, float(parent.requested_quantity) - float(parent.filled_quantity)
        )
        parent.status = "FILLED" if parent.remaining_quantity <= 0 else "PARTIALLY_FILLED"
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
