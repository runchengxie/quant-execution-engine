"""Execution lifecycle models and file-backed state store."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field, is_dataclass
from pathlib import Path
from typing import Any

from .broker.base import BrokerFillRecord, BrokerOrderRecord, BrokerReconcileReport, utc_now_iso
from .config import load_cfg
from .logging import get_run_id
from .paths import OUTPUTS_DIR


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
TERMINAL_BROKER_STATUSES = SUCCESS_BROKER_STATUSES | FAILURE_BROKER_STATUSES
STALE_RETRY_EXCLUDED_STATUSES = {"PENDING_CANCEL", "WAIT_TO_CANCEL"}
DEFAULT_EXCEPTION_STATUSES = {
    "BLOCKED",
    "FAILED",
    "REJECTED",
    "EXPIRED",
    "PARTIALLY_FILLED",
    "PENDING_CANCEL",
    "WAIT_TO_CANCEL",
}


@dataclass(slots=True)
class OrderIntent:
    """Stable order intent captured before broker submission."""

    intent_id: str
    symbol: str
    side: str
    quantity: float
    order_type: str
    limit_price: float | None = None
    broker_name: str = ""
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
    metadata: dict[str, Any] = field(default_factory=dict)


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
    message: str | None = None
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
    broker_name: str = ""
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


@dataclass(slots=True)
class ExecutionReconcileResult:
    """Result of a manual reconcile pass."""

    report: BrokerReconcileReport
    state: ExecutionState
    state_path: Path
    new_fill_events: int = 0
    refreshed_orders: int = 0
    changed_orders: list["ExecutionReconcileDelta"] = field(default_factory=list)


@dataclass(slots=True)
class ExecutionReconcileDelta:
    """Single tracked order change detected during reconcile."""

    broker_order_id: str
    symbol: str
    before_status: str | None
    after_status: str
    before_filled_quantity: float = 0.0
    after_filled_quantity: float = 0.0
    new_fill_events: int = 0


@dataclass(slots=True)
class ExecutionCancelResult:
    """Result of a tracked-order cancel request."""

    broker_name: str
    account_label: str
    order_ref: str
    broker_order_id: str
    client_order_id: str | None
    status: str
    state_path: Path
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ExecutionBulkCancelResult:
    """Result of a bulk tracked-order cancel request."""

    broker_name: str
    account_label: str
    state_path: Path
    targeted_orders: int = 0
    results: list[ExecutionCancelResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ExecutionTrackedOrder:
    """Tracked order details resolved from local execution state."""

    broker_name: str
    account_label: str
    order_ref: str
    state_path: Path
    intent: OrderIntent | None
    parent: ParentOrder | None
    child: ChildOrder | None
    broker_order: BrokerOrderRecord | None
    fill_events: list[ExecutionFillEvent] = field(default_factory=list)


@dataclass(slots=True)
class ExecutionOrderTrace:
    """Merged tracked-state and broker-side trace for one execution parent."""

    broker_name: str
    account_label: str
    order_ref: str
    state_path: Path
    intent: OrderIntent | None
    parent: ParentOrder | None
    child: ChildOrder | None
    broker_order: BrokerOrderRecord | None
    child_orders: list[ChildOrder] = field(default_factory=list)
    tracked_broker_orders: list[BrokerOrderRecord] = field(default_factory=list)
    fill_events: list[ExecutionFillEvent] = field(default_factory=list)
    broker_history_orders: list[BrokerOrderRecord] = field(default_factory=list)
    broker_history_fills: list[BrokerFillRecord] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ExecutionExceptionRecord:
    """Resolved exception record from local execution state."""

    broker_name: str
    account_label: str
    symbol: str
    side: str
    status: str
    parent_order_id: str
    child_order_id: str | None
    broker_order_id: str | None
    client_order_id: str | None
    source: str
    message: str | None = None
    filled_quantity: float = 0.0
    remaining_quantity: float | None = None
    updated_at: str | None = None


@dataclass(slots=True)
class ExecutionRetryResult:
    """Result of a tracked-order retry request."""

    broker_name: str
    account_label: str
    order_ref: str
    new_child_order_id: str
    broker_order_id: str | None
    broker_status: str | None
    state_path: Path
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ExecutionResumeRemainingResult:
    """Result of resubmitting the remaining quantity after a partial fill."""

    broker_name: str
    account_label: str
    order_ref: str
    submitted_quantity: float
    new_child_order_id: str
    broker_order_id: str | None
    broker_status: str | None
    state_path: Path
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ExecutionRepriceResult:
    """Result of a tracked-order reprice request."""

    broker_name: str
    account_label: str
    order_ref: str
    old_broker_order_id: str
    cancel_status: str
    old_limit_price: float | None
    new_limit_price: float
    new_child_order_id: str | None
    broker_order_id: str | None
    broker_status: str | None
    state_path: Path
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ExecutionAcceptPartialResult:
    """Result of accepting a partial fill locally."""

    broker_name: str
    account_label: str
    order_ref: str
    parent_order_id: str
    accepted_filled_quantity: float
    abandoned_remaining_quantity: float
    state_path: Path
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ExecutionStaleRetryResult:
    """Result of a stale tracked-order retry pass."""

    broker_name: str
    account_label: str
    state_path: Path
    older_than_minutes: int
    targeted_orders: int = 0
    cancel_results: list[ExecutionCancelResult] = field(default_factory=list)
    retry_results: list[ExecutionRetryResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


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


__all__ = [
    "OPEN_BROKER_STATUSES",
    "SUCCESS_BROKER_STATUSES",
    "FAILURE_BROKER_STATUSES",
    "TERMINAL_BROKER_STATUSES",
    "STALE_RETRY_EXCLUDED_STATUSES",
    "DEFAULT_EXCEPTION_STATUSES",
    "OrderIntent",
    "ParentOrder",
    "ChildOrder",
    "ExecutionFillEvent",
    "ExecutionState",
    "ExecutionReconcileResult",
    "ExecutionReconcileDelta",
    "ExecutionCancelResult",
    "ExecutionBulkCancelResult",
    "ExecutionTrackedOrder",
    "ExecutionOrderTrace",
    "ExecutionExceptionRecord",
    "ExecutionRetryResult",
    "ExecutionResumeRemainingResult",
    "ExecutionRepriceResult",
    "ExecutionAcceptPartialResult",
    "ExecutionStaleRetryResult",
    "ExecutionStateStore",
]
