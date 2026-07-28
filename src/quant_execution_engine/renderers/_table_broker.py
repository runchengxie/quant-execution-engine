"""Broker-facing table renderers (orders, history, fills, exceptions)."""

from __future__ import annotations

from ..broker.base import BrokerFillRecord, BrokerOrderRecord
from ..diagnostics import diagnose_order_issue
from ..execution import ExecutionExceptionRecord


def render_broker_orders(records: list[BrokerOrderRecord]) -> str:
    """Render tracked broker order records."""

    if not records:
        return "No tracked broker orders"

    lines = []
    lines.append("Tracked broker orders:")
    lines.append(
        "Broker ID           | Symbol      | Side | Qty      | Filled   | "
        "Status           | Client ID"
    )
    lines.append("-" * 108)

    for record in records:
        client_order_id = record.client_order_id or "-"
        lines.append(
            f"{record.broker_order_id[:18]:18s} | "
            f"{record.symbol[:10]:10s} | "
            f"{record.side[:4]:4s} | "
            f"{record.quantity:8.2f} | "
            f"{float(record.filled_quantity or 0.0):8.2f} | "
            f"{record.status[:16]:16s} | "
            f"{client_order_id[:18]}"
        )
        diagnostic = diagnose_order_issue(record)
        if record.message:
            lines.append(f"  -> {record.message}")
        if diagnostic is not None:
            lines.append(f"  -> [{diagnostic.code}] {diagnostic.summary}")
            if diagnostic.action_hint:
                lines.append(f"  -> Next: {diagnostic.action_hint}")

    return "\n".join(lines)


def render_broker_order_history(records: list[BrokerOrderRecord]) -> str:
    """Render broker-side read-only order history."""

    if not records:
        return "No broker-side order history"

    lines = []
    lines.append("Broker-side order history:")
    lines.append(
        "Broker ID           | Symbol      | Side | Qty      | Filled   | "
        "Status           | Updated At"
    )
    lines.append("-" * 110)

    for record in records:
        lines.append(
            f"{record.broker_order_id[:18]:18s} | "
            f"{record.symbol[:10]:10s} | "
            f"{record.side[:4]:4s} | "
            f"{record.quantity:8.2f} | "
            f"{float(record.filled_quantity or 0.0):8.2f} | "
            f"{record.status[:16]:16s} | "
            f"{record.updated_at[:19]}"
        )
        if record.client_order_id:
            lines.append(f"  -> client_order_id={record.client_order_id}")
        if record.message:
            lines.append(f"  -> {record.message}")

    return "\n".join(lines)


def render_broker_fill_history(records: list[BrokerFillRecord]) -> str:
    """Render broker-side read-only fill history."""

    if not records:
        return "No broker-side fill history"

    lines = []
    lines.append("Broker-side fill history:")
    lines.append(
        "Filled At           | Symbol      | Qty      | Price      | Broker ID           | Fill ID"
    )
    lines.append("-" * 116)

    for record in records:
        lines.append(
            f"{record.filled_at[:19]:19s} | "
            f"{record.symbol[:10]:10s} | "
            f"{record.quantity:8.2f} | "
            f"{record.price:10.4f} | "
            f"{record.broker_order_id[:18]:18s} | "
            f"{record.fill_id[:24]}"
        )

    return "\n".join(lines)


def render_exception_orders(records: list[ExecutionExceptionRecord]) -> str:
    """Render local exception queue records."""

    if not records:
        return "No tracked execution exceptions"

    lines = []
    lines.append("Tracked execution exceptions:")
    lines.append(
        "Status           | Symbol      | Side | Source | Parent                | "
        "Child                 | Broker ID           "
    )
    lines.append("-" * 120)

    for record in records:
        lines.append(
            f"{record.status[:16]:16s} | "
            f"{record.symbol[:10]:10s} | "
            f"{record.side[:4]:4s} | "
            f"{record.source[:6]:6s} | "
            f"{record.parent_order_id[:20]:20s} | "
            f"{(record.child_order_id or '-')[:21]:21s} | "
            f"{(record.broker_order_id or '-')[:18]:18s}"
        )
        diagnostic = diagnose_order_issue(record)
        if record.message:
            lines.append(f"  -> {record.message}")
        if diagnostic is not None:
            lines.append(f"  -> [{diagnostic.code}] {diagnostic.summary}")
            if diagnostic.action_hint:
                lines.append(f"  -> Next: {diagnostic.action_hint}")

    return "\n".join(lines)
