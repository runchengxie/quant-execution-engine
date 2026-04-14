"""Table renderer

Provides table format data rendering functionality.
"""

from ..broker.base import BrokerOrderRecord, BrokerReconcileReport
from ..execution import (
    ExecutionBulkCancelResult,
    ExecutionStaleRetryResult,
    ExecutionTrackedOrder,
)
from ..models import AccountSnapshot, Order, Quote, RebalanceResult


def render_quotes(quotes: list[Quote]) -> str:
    """Render stock quotes table

    Args:
        quotes: List of quotes

    Returns:
        str: Formatted table string
    """
    if not quotes:
        return "No quote data"

    lines = []
    lines.append("Real-time quotes:")
    lines.append("-" * 50)

    for quote in quotes:
        lines.append(
            f"{quote.symbol:12} | Price: {quote.price:>10.2f} | Time: {quote.timestamp}"
        )

    return "\n".join(lines)


def render_account_snapshot(
    snapshot: AccountSnapshot, only_funds: bool = False, only_positions: bool = False
) -> str:
    """Render account snapshot table

    Args:
        snapshot: Account snapshot
        only_funds: Only show fund information
        only_positions: Only show position information

    Returns:
        str: Formatted table string
    """
    lines = []

    # Environment identifier
    if snapshot.env == "real":
        lines.append("!!! REAL ACCOUNT DATA (READ-ONLY) !!!")

    # Fund information
    if not only_positions:
        lines.append(f"\n[{snapshot.env.upper()}] Cash (USD): ${snapshot.cash_usd:,.2f}")
        if not only_funds:
            lines.append(f"Positions value: ${snapshot.total_market_value:,.2f}")
            lines.append(f"Total assets: ${snapshot.total_portfolio_value:,.2f}")

    # Position information
    if not only_funds:
        if snapshot.positions:
            if not only_positions:
                lines.append("\nPositions:")
            lines.append("Symbol        Qty        Last       Est.Value")
            lines.append("-" * 50)

            for position in snapshot.positions:
                lines.append(
                    f"{position.symbol:12} {position.quantity:10} "
                    f"{position.last_price:10.2f} ${position.estimated_value:>10,.2f}"
                )
        else:
            if not only_positions:
                lines.append("\nNo positions held")

    return "\n".join(lines)


def render_multiple_account_snapshots(
    snapshots: list[AccountSnapshot],
    only_funds: bool = False,
    only_positions: bool = False,
) -> str:
    """Render multiple account snapshots

    Args:
        snapshots: List of account snapshots
        only_funds: Only show fund information
        only_positions: Only show position information

    Returns:
        str: Formatted table string
    """
    if not snapshots:
        return "No account data"

    lines = []
    for snapshot in snapshots:
        lines.append(render_account_snapshot(snapshot, only_funds, only_positions))

    return "\n".join(lines)


def render_rebalance_plan(result: RebalanceResult) -> str:
    """Render rebalance plan table

    Args:
        result: Rebalance result

    Returns:
        str: Formatted table string
    """
    lines = []

    # Title
    mode = "Dry Run" if result.dry_run else "Execution Mode"
    lines.append(f"\n=== {mode} - {result.sheet_name} Rebalance Summary ===")
    lines.append("-" * 80)

    # Account overview
    lines.append(f"Total assets: ${result.total_portfolio_value:,.2f}")
    lines.append(
        f"Equal weight allocation: target value per stock ${result.target_value_per_stock:,.2f}"
    )
    lines.append("-" * 80)

    # Rebalance details header
    lines.append("Symbol   | Last Price | Current Qty | Target Qty | Delta   | Action")
    lines.append("-" * 80)

    # Build current positions mapping
    current_positions_map = {pos.symbol: pos for pos in result.current_positions}

    # Show rebalance situation for each target stock
    for target_pos in result.target_positions:
        current_pos = current_positions_map.get(target_pos.symbol)
        current_qty = current_pos.quantity if current_pos else 0

        delta_qty = target_pos.quantity - current_qty

        # Find corresponding order
        order = None
        for o in result.orders:
            if o.symbol == target_pos.symbol or o.symbol.replace(
                ".US", ""
            ) == target_pos.symbol.replace(".US", ""):
                order = o
                break

        if order:
            action = f"{order.side} {order.quantity}"
        elif abs(delta_qty) > 0:
            action = "Skip (too small delta)"
        else:
            action = "No change"

        lines.append(
            f"{target_pos.symbol[:8]:8s} | {target_pos.last_price:8.2f} | "
            f"{current_qty:8d} | {target_pos.quantity:8d} | {delta_qty:7d} | {action}"
        )

    # Order summary
    lines.append(f"\nProcessed {len(result.orders)} orders")

    if result.dry_run:
        lines.append("\nNote: this is a dry run, no orders were placed")
        lines.append("Use --execute to run broker-backed submission with risk gates and reconcile")
    else:
        lines.append("\nLive mode used the selected broker adapter; inspect audit logs for lifecycle details")

    return "\n".join(lines)


def render_orders(orders: list[Order]) -> str:
    """Render order list

    Args:
        orders: List of orders

    Returns:
        str: Formatted table string
    """
    if not orders:
        return "No order data"

    lines = []
    lines.append("Order details:")
    lines.append("Symbol   | Side | Qty    | Price    | Status   | Order ID")
    lines.append("-" * 65)

    for order in orders:
        price_str = f"{order.price:.2f}" if order.price else "MARKET"
        order_id_str = order.order_id[:8] if order.order_id else "N/A"

        lines.append(
            f"{order.symbol[:8]:8s} | {order.side:4s} | {order.quantity:6d} | "
            f"{price_str:8s} | {order.status:8s} | {order_id_str}"
        )

        if order.error_message:
            lines.append(f"  -> Error: {order.error_message}")

    return "\n".join(lines)


def render_broker_orders(records: list[BrokerOrderRecord]) -> str:
    """Render tracked broker order records."""

    if not records:
        return "No tracked broker orders"

    lines = []
    lines.append("Tracked broker orders:")
    lines.append(
        "Broker ID           | Symbol      | Side | Qty      | Filled   | Status           | Client ID"
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

    return "\n".join(lines)


def render_reconcile_summary(
    *,
    report: BrokerReconcileReport,
    state_path: str,
    tracked_orders: int,
    fill_events: int,
    new_fill_events: int,
    refreshed_orders: int,
) -> str:
    """Render manual reconcile summary."""

    lines = [
        "Reconcile summary:",
        f"- Broker / Account: {report.broker_name} / {report.account_label}",
        f"- Open orders from broker: {len(report.open_orders)}",
        f"- Tracked broker orders: {tracked_orders}",
        f"- Total fill events in state: {fill_events}",
        f"- New fill events recorded: {new_fill_events}",
        f"- Closed tracked orders refreshed: {refreshed_orders}",
        f"- State file: {state_path}",
    ]
    if report.warnings:
        lines.append("- Warnings:")
        for warning in report.warnings:
            lines.append(f"  * {warning}")
    return "\n".join(lines)


def render_cancel_summary(
    *,
    broker_name: str,
    account_label: str,
    order_ref: str,
    broker_order_id: str,
    client_order_id: str | None,
    status: str,
    state_path: str,
    warnings: list[str],
) -> str:
    """Render tracked-order cancel summary."""

    lines = [
        "Cancel summary:",
        f"- Broker / Account: {broker_name} / {account_label}",
        f"- Requested Ref: {order_ref}",
        f"- Broker Order ID: {broker_order_id}",
        f"- Client Order ID: {client_order_id or '-'}",
        f"- Current Status: {status}",
        f"- State file: {state_path}",
    ]
    if warnings:
        lines.append("- Warnings:")
        for warning in warnings:
            lines.append(f"  * {warning}")
    return "\n".join(lines)


def render_bulk_cancel_summary(outcome: ExecutionBulkCancelResult) -> str:
    """Render tracked bulk-cancel summary."""

    canceled = sum(1 for result in outcome.results if result.status == "CANCELED")
    pending_cancel = sum(1 for result in outcome.results if result.status == "PENDING_CANCEL")
    other_statuses = len(outcome.results) - canceled - pending_cancel

    lines = [
        "Bulk cancel summary:",
        f"- Broker / Account: {outcome.broker_name} / {outcome.account_label}",
        f"- Tracked open orders targeted: {outcome.targeted_orders}",
        f"- Cancel requests completed: {len(outcome.results)}",
        f"- Final CANCELED: {canceled}",
        f"- Final PENDING_CANCEL: {pending_cancel}",
        f"- Other statuses: {other_statuses}",
        f"- State file: {outcome.state_path}",
    ]
    if outcome.results:
        lines.append("- Orders:")
        for result in outcome.results:
            lines.append(
                f"  * {result.broker_order_id} ({result.client_order_id or '-'}) -> {result.status}"
            )
            for warning in result.warnings:
                lines.append(f"    warning: {warning}")
    if outcome.warnings:
        lines.append("- Warnings:")
        for warning in outcome.warnings:
            lines.append(f"  * {warning}")
    if not outcome.results and not outcome.warnings:
        lines.append("- No tracked open orders were found in local execution state")
    return "\n".join(lines)


def render_tracked_order_detail(tracked: ExecutionTrackedOrder) -> str:
    """Render tracked order details from local execution state."""

    lines = [
        "Tracked order detail:",
        f"- Broker / Account: {tracked.broker_name} / {tracked.account_label}",
        f"- Requested Ref: {tracked.order_ref}",
        f"- State file: {tracked.state_path}",
    ]
    if tracked.intent is not None:
        lines.extend(
            [
                f"- Intent: {tracked.intent.intent_id} {tracked.intent.side} {tracked.intent.quantity:g} {tracked.intent.symbol}",
                f"- Intent Order Type: {tracked.intent.order_type}",
            ]
        )
    if tracked.parent is not None:
        lines.extend(
            [
                f"- Parent: {tracked.parent.parent_order_id}",
                f"- Parent Status: {tracked.parent.status}",
                f"- Parent Filled / Remaining: {tracked.parent.filled_quantity:g} / {tracked.parent.remaining_quantity:g}",
            ]
        )
    if tracked.child is not None:
        lines.extend(
            [
                f"- Child: {tracked.child.child_order_id} (attempt {tracked.child.attempt})",
                f"- Child Status: {tracked.child.status}",
            ]
        )
    if tracked.broker_order is not None:
        lines.extend(
            [
                f"- Broker Order ID: {tracked.broker_order.broker_order_id}",
                f"- Broker Status: {tracked.broker_order.status}",
                f"- Client Order ID: {tracked.broker_order.client_order_id or '-'}",
                f"- Broker Filled / Remaining: {float(tracked.broker_order.filled_quantity or 0.0):g} / {float(tracked.broker_order.remaining_quantity or 0.0):g}",
            ]
        )
    lines.append(f"- Fill Events: {len(tracked.fill_events)}")
    for fill in tracked.fill_events:
        lines.append(
            f"  * {fill.fill_id}: {fill.quantity:g} @ {fill.price:g} on {fill.filled_at}"
        )
    return "\n".join(lines)


def render_retry_summary(
    *,
    broker_name: str,
    account_label: str,
    order_ref: str,
    new_child_order_id: str,
    broker_order_id: str | None,
    broker_status: str | None,
    state_path: str,
    warnings: list[str],
) -> str:
    """Render tracked-order retry summary."""

    lines = [
        "Retry summary:",
        f"- Broker / Account: {broker_name} / {account_label}",
        f"- Requested Ref: {order_ref}",
        f"- New Child Order ID: {new_child_order_id}",
        f"- Broker Order ID: {broker_order_id or '-'}",
        f"- Broker Status: {broker_status or '-'}",
        f"- State file: {state_path}",
    ]
    if warnings:
        lines.append("- Warnings:")
        for warning in warnings:
            lines.append(f"  * {warning}")
    return "\n".join(lines)


def render_stale_retry_summary(outcome: ExecutionStaleRetryResult) -> str:
    """Render stale tracked-order retry summary."""

    lines = [
        "Stale retry summary:",
        f"- Broker / Account: {outcome.broker_name} / {outcome.account_label}",
        f"- Older Than (minutes): {outcome.older_than_minutes}",
        f"- Targeted stale tracked orders: {outcome.targeted_orders}",
        f"- Cancel attempts completed: {len(outcome.cancel_results)}",
        f"- Retry attempts completed: {len(outcome.retry_results)}",
        f"- State file: {outcome.state_path}",
    ]
    if outcome.cancel_results:
        lines.append("- Cancel results:")
        for result in outcome.cancel_results:
            lines.append(f"  * {result.broker_order_id} -> {result.status}")
            for warning in result.warnings:
                lines.append(f"    warning: {warning}")
    if outcome.retry_results:
        lines.append("- Retry results:")
        for result in outcome.retry_results:
            lines.append(
                f"  * {result.order_ref} -> child {result.new_child_order_id} / broker {result.broker_order_id or '-'} / status {result.broker_status or '-'}"
            )
            for warning in result.warnings:
                lines.append(f"    warning: {warning}")
    if outcome.warnings:
        lines.append("- Warnings:")
        for warning in outcome.warnings:
            lines.append(f"  * {warning}")
    if (
        not outcome.cancel_results
        and not outcome.retry_results
        and not outcome.warnings
    ):
        lines.append("- No stale tracked open orders were eligible for retry")
    return "\n".join(lines)
