"""State and outcome queries for the operator smoke harness."""

from __future__ import annotations

from quant_execution_engine.diagnostics import diagnose_order_issue
from quant_execution_engine.execution import ExecutionStateStore


def _state_store_or_default(
    state_store: ExecutionStateStore | None,
) -> ExecutionStateStore:
    """Return the provided store, or build a default.

    The default class is resolved from the harness facade
    (``project_tools.smoke_operator_harness``) when present so tests can
    monkeypatch ``ExecutionStateStore`` on that module. We look it up lazily to
    avoid a circular import between this package and the facade.
    """
    if state_store is not None:
        return state_store
    import project_tools.smoke_operator_harness as _harness

    store_cls = getattr(_harness, "ExecutionStateStore", ExecutionStateStore)
    return store_cls()


def symbol_matches(symbol: str, allowed: set[str] | None) -> bool:
    if allowed is None:
        return True
    normalized = str(symbol).strip().upper()
    base = normalized.rsplit(".", 1)[0] if "." in normalized else normalized
    return normalized in allowed or base in allowed


def canonical_symbol(symbol: str, market: str) -> str:
    base = str(symbol).strip().upper()
    suffix = str(market).strip().upper()
    if not base:
        raise ValueError("symbol must not be empty")
    if not suffix:
        raise ValueError("market must not be empty")
    if base.endswith(f".{suffix}"):
        return base
    if "." in base:
        return base
    return f"{base}.{suffix}"


def build_operator_smoke_targets(
    *,
    symbol: str,
    market: str,
    current_quantity: int,
) -> list[dict[str, object]]:
    base_symbol = str(symbol).strip().upper().split(".", 1)[0]
    target_quantity = max(1, int(current_quantity) + 1)
    return [
        {
            "symbol": base_symbol,
            "market": str(market).strip().upper(),
            "target_quantity": target_quantity,
            "notes": "Deterministic operator smoke target with +1 share delta",
            "metadata": {
                "scenario": "operator-smoke",
                "current_quantity": int(current_quantity),
                "target_quantity": target_quantity,
                "delta_quantity": target_quantity - int(current_quantity),
            },
        }
    ]


def latest_tracked_order_ref(
    *,
    broker_name: str,
    account_label: str,
    symbol_filter: str | None = None,
    target_input_path: str | None = None,
    state_store: ExecutionStateStore | None = None,
) -> str | None:
    if target_input_path is not None:
        outcome = latest_operator_outcome(
            broker_name=broker_name,
            account_label=account_label,
            symbol_filter=symbol_filter,
            target_input_path=target_input_path,
            state_store=state_store,
        )
        if outcome is not None:
            broker_order_id = outcome.get("broker_order_id")
            return str(broker_order_id) if broker_order_id else None

    store = _state_store_or_default(state_store)
    state = store.load(broker_name, account_label)
    allowed = None if not symbol_filter else {str(symbol_filter).strip().upper()}
    records = sorted(
        state.broker_orders,
        key=lambda record: (
            record.updated_at,
            record.submitted_at,
            record.broker_order_id,
        ),
        reverse=True,
    )
    for record in records:
        if allowed is not None and not symbol_matches(record.symbol, allowed):
            continue
        return record.broker_order_id
    return None


def latest_operator_outcome(
    *,
    broker_name: str,
    account_label: str,
    symbol_filter: str | None = None,
    target_input_path: str | None = None,
    state_store: ExecutionStateStore | None = None,
) -> dict[str, object] | None:
    store = _state_store_or_default(state_store)
    state = store.load(broker_name, account_label)
    allowed = None if not symbol_filter else {str(symbol_filter).strip().upper()}
    normalized_target_input = None if target_input_path is None else str(target_input_path).strip()

    intents = [
        intent
        for intent in state.intents
        if (normalized_target_input is None or intent.target_input_path == normalized_target_input)
        and symbol_matches(intent.symbol, allowed)
    ]
    if not intents:
        return None

    intent_ids = {intent.intent_id for intent in intents}
    parents = [
        parent
        for parent in state.parent_orders
        if parent.intent_id in intent_ids and symbol_matches(parent.symbol, allowed)
    ]
    if not parents:
        return None

    parent = sorted(
        parents,
        key=lambda item: (
            item.updated_at or "",
            item.created_at or "",
            item.parent_order_id,
        ),
        reverse=True,
    )[0]
    children = [
        child for child in state.child_orders if child.parent_order_id == parent.parent_order_id
    ]
    child = (
        sorted(
            children,
            key=lambda item: (
                item.attempt,
                item.updated_at or "",
                item.created_at or "",
                item.child_order_id,
            ),
            reverse=True,
        )[0]
        if children
        else None
    )
    broker_order = None
    if child is not None and child.broker_order_id:
        broker_order = next(
            (
                record
                for record in state.broker_orders
                if record.broker_order_id == child.broker_order_id
            ),
            None,
        )

    record = broker_order or child or parent
    diagnostic = diagnose_order_issue(record)
    status = (
        broker_order.status
        if broker_order is not None
        else child.status
        if child is not None
        else parent.status
    )
    message = (
        broker_order.message
        if broker_order is not None
        else child.message
        if child is not None
        else None
    )
    broker_order_id = (
        broker_order.broker_order_id
        if broker_order is not None
        else child.broker_order_id
        if child is not None
        else None
    )
    client_order_id = (
        broker_order.client_order_id
        if broker_order is not None
        else child.client_order_id
        if child is not None
        else None
    )
    return {
        "status": status,
        "source": "broker" if broker_order is not None else "local",
        "message": message,
        "category": diagnostic.code if diagnostic is not None else None,
        "next_step_hint": diagnostic.action_hint if diagnostic is not None else None,
        "parent_order_id": parent.parent_order_id,
        "child_order_id": child.child_order_id if child is not None else None,
        "broker_order_id": broker_order_id,
        "client_order_id": client_order_id,
    }
