"""Table renderer

Provides table format data rendering functionality.
"""

from ..broker.base import BrokerFillRecord, BrokerOrderRecord, BrokerReconcileReport
from ..diagnostics import diagnose_order_issue, diagnose_warning_message
from ..execution import (
    ExecutionAcceptPartialResult,
    ExecutionBulkCancelResult,
    ExecutionExceptionRecord,
    ExecutionReconcileDelta,
    ExecutionRepriceResult,
    ExecutionResumeRemainingResult,
    ExecutionStaleRetryResult,
    ExecutionTrackedOrder,
)
from ..models import AccountSnapshot, Order, Quote, RebalanceResult
from ..preflight import PreflightResult
from ..state_tools import StateDoctorResult, StatePruneResult, StateRepairResult


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
        "Broker ID           | Symbol      | Side | Qty      | Filled   | Status           | Updated At"
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
        "Status           | Symbol      | Side | Source | Parent                | Child                 | Broker ID           "
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


def render_reconcile_summary(
    *,
    report: BrokerReconcileReport,
    state_path: str,
    tracked_orders: int,
    fill_events: int,
    new_fill_events: int,
    refreshed_orders: int,
    changed_orders: list[ExecutionReconcileDelta],
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
        f"- Changed tracked orders: {len(changed_orders)}",
        f"- State file: {state_path}",
    ]
    if changed_orders:
        lines.append("- Changes:")
        for delta in changed_orders:
            before_status = delta.before_status or "-"
            fill_delta = delta.after_filled_quantity - delta.before_filled_quantity
            lines.append(
                "  * "
                f"{delta.broker_order_id} {delta.symbol}: "
                f"{before_status} -> {delta.after_status}, "
                f"filled {delta.before_filled_quantity:g} -> {delta.after_filled_quantity:g}"
            )
            if delta.new_fill_events > 0 or fill_delta > 0:
                lines.append(
                    f"    new_fill_events={delta.new_fill_events}, filled_delta={fill_delta:g}"
                )
    if report.warnings:
        lines.append("- Warnings:")
        for warning in report.warnings:
            diagnostic = diagnose_warning_message(warning)
            lines.append(f"  * [{diagnostic.code}] {diagnostic.summary}")
            if diagnostic.action_hint:
                lines.append(f"    next: {diagnostic.action_hint}")
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
            diagnostic = diagnose_warning_message(warning)
            lines.append(f"  * [{diagnostic.code}] {diagnostic.summary}")
            if diagnostic.action_hint:
                lines.append(f"    next: {diagnostic.action_hint}")
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
                diagnostic = diagnose_warning_message(warning)
                lines.append(f"    warning: [{diagnostic.code}] {diagnostic.summary}")
                if diagnostic.action_hint:
                    lines.append(f"    next: {diagnostic.action_hint}")
    if outcome.warnings:
        lines.append("- Warnings:")
        for warning in outcome.warnings:
            diagnostic = diagnose_warning_message(warning)
            lines.append(f"  * [{diagnostic.code}] {diagnostic.summary}")
            if diagnostic.action_hint:
                lines.append(f"    next: {diagnostic.action_hint}")
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
                f"- Target Source: {tracked.intent.target_source or '-'}",
                f"- Target Asof: {tracked.intent.target_asof or '-'}",
                f"- Target Input: {tracked.intent.target_input_path or '-'}",
            ]
        )
        if str(tracked.intent.order_type).upper() == "LIMIT":
            lines.append(
                f"- Intent Limit Price: {tracked.intent.limit_price if tracked.intent.limit_price is not None else '-'}"
            )
        last_reprice_at = tracked.intent.metadata.get("last_reprice_at")
        if last_reprice_at:
            lines.append(f"- Last Reprice At: {last_reprice_at}")
        if "last_reprice_from_limit_price" in tracked.intent.metadata:
            lines.append(
                "- Last Reprice From Limit: "
                f"{tracked.intent.metadata.get('last_reprice_from_limit_price')}"
            )
    if tracked.parent is not None:
        lines.extend(
            [
                f"- Parent: {tracked.parent.parent_order_id}",
                f"- Parent Status: {tracked.parent.status}",
                f"- Parent Filled / Remaining: {tracked.parent.filled_quantity:g} / {tracked.parent.remaining_quantity:g}",
            ]
        )
        manual_resolution = tracked.parent.metadata.get("manual_resolution")
        if manual_resolution:
            lines.append(f"- Manual Resolution: {manual_resolution}")
        if tracked.parent.metadata.get("manual_resolution_at"):
            lines.append(
                f"- Manual Resolution At: {tracked.parent.metadata.get('manual_resolution_at')}"
            )
    if tracked.child is not None:
        lines.extend(
            [
                f"- Child: {tracked.child.child_order_id} (attempt {tracked.child.attempt})",
                f"- Child Status: {tracked.child.status}",
            ]
        )
        if tracked.child.message:
            lines.append(f"- Child Message: {tracked.child.message}")
    if tracked.broker_order is not None:
        lines.extend(
            [
                f"- Broker Order ID: {tracked.broker_order.broker_order_id}",
                f"- Broker Status: {tracked.broker_order.status}",
                f"- Client Order ID: {tracked.broker_order.client_order_id or '-'}",
                f"- Broker Filled / Remaining: {float(tracked.broker_order.filled_quantity or 0.0):g} / {float(tracked.broker_order.remaining_quantity or 0.0):g}",
            ]
        )
        diagnostic = diagnose_order_issue(tracked.broker_order)
        if diagnostic is not None:
            lines.append(f"- Diagnostic: [{diagnostic.code}] {diagnostic.summary}")
            if diagnostic.action_hint:
                lines.append(f"- Suggested Next Step: {diagnostic.action_hint}")
    elif tracked.child is not None:
        diagnostic = diagnose_order_issue(tracked.child)
        if diagnostic is not None:
            lines.append(f"- Diagnostic: [{diagnostic.code}] {diagnostic.summary}")
            if diagnostic.action_hint:
                lines.append(f"- Suggested Next Step: {diagnostic.action_hint}")
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
            diagnostic = diagnose_warning_message(warning)
            lines.append(f"  * [{diagnostic.code}] {diagnostic.summary}")
            if diagnostic.action_hint:
                lines.append(f"    next: {diagnostic.action_hint}")
    return "\n".join(lines)


def render_reprice_summary(outcome: ExecutionRepriceResult) -> str:
    """Render tracked-order reprice summary."""

    lines = [
        "Reprice summary:",
        f"- Broker / Account: {outcome.broker_name} / {outcome.account_label}",
        f"- Requested Ref: {outcome.order_ref}",
        f"- Old Broker Order ID: {outcome.old_broker_order_id}",
        f"- Cancel Status: {outcome.cancel_status}",
        f"- Old Limit Price: {outcome.old_limit_price if outcome.old_limit_price is not None else '-'}",
        f"- New Limit Price: {outcome.new_limit_price}",
        f"- New Child Order ID: {outcome.new_child_order_id or '-'}",
        f"- New Broker Order ID: {outcome.broker_order_id or '-'}",
        f"- New Broker Status: {outcome.broker_status or '-'}",
        f"- State file: {outcome.state_path}",
    ]
    if outcome.warnings:
        lines.append("- Warnings:")
        for warning in outcome.warnings:
            diagnostic = diagnose_warning_message(warning)
            lines.append(f"  * [{diagnostic.code}] {diagnostic.summary}")
            if diagnostic.action_hint:
                lines.append(f"    next: {diagnostic.action_hint}")
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
                diagnostic = diagnose_warning_message(warning)
                lines.append(f"    warning: [{diagnostic.code}] {diagnostic.summary}")
                if diagnostic.action_hint:
                    lines.append(f"    next: {diagnostic.action_hint}")
    if outcome.retry_results:
        lines.append("- Retry results:")
        for result in outcome.retry_results:
            lines.append(
                f"  * {result.order_ref} -> child {result.new_child_order_id} / broker {result.broker_order_id or '-'} / status {result.broker_status or '-'}"
            )
            for warning in result.warnings:
                diagnostic = diagnose_warning_message(warning)
                lines.append(f"    warning: [{diagnostic.code}] {diagnostic.summary}")
                if diagnostic.action_hint:
                    lines.append(f"    next: {diagnostic.action_hint}")
    if outcome.warnings:
        lines.append("- Warnings:")
        for warning in outcome.warnings:
            diagnostic = diagnose_warning_message(warning)
            lines.append(f"  * [{diagnostic.code}] {diagnostic.summary}")
            if diagnostic.action_hint:
                lines.append(f"    next: {diagnostic.action_hint}")
    if (
        not outcome.cancel_results
        and not outcome.retry_results
        and not outcome.warnings
    ):
        lines.append("- No stale tracked open orders were eligible for retry")
    return "\n".join(lines)


def render_resume_remaining_summary(outcome: ExecutionResumeRemainingResult) -> str:
    """Render resume-remaining summary."""

    lines = [
        "Resume remaining summary:",
        f"- Broker / Account: {outcome.broker_name} / {outcome.account_label}",
        f"- Requested Ref: {outcome.order_ref}",
        f"- Submitted Remaining Quantity: {outcome.submitted_quantity:g}",
        f"- New Child Order ID: {outcome.new_child_order_id}",
        f"- Broker Order ID: {outcome.broker_order_id or '-'}",
        f"- Broker Status: {outcome.broker_status or '-'}",
        f"- State file: {outcome.state_path}",
    ]
    if outcome.warnings:
        lines.append("- Warnings:")
        for warning in outcome.warnings:
            diagnostic = diagnose_warning_message(warning)
            lines.append(f"  * [{diagnostic.code}] {diagnostic.summary}")
            if diagnostic.action_hint:
                lines.append(f"    next: {diagnostic.action_hint}")
    return "\n".join(lines)


def render_accept_partial_summary(outcome: ExecutionAcceptPartialResult) -> str:
    """Render accept-partial summary."""

    lines = [
        "Accept partial summary:",
        f"- Broker / Account: {outcome.broker_name} / {outcome.account_label}",
        f"- Requested Ref: {outcome.order_ref}",
        f"- Parent Order ID: {outcome.parent_order_id}",
        f"- Accepted Filled Quantity: {outcome.accepted_filled_quantity:g}",
        f"- Abandoned Remaining Quantity: {outcome.abandoned_remaining_quantity:g}",
        f"- State file: {outcome.state_path}",
    ]
    if outcome.warnings:
        lines.append("- Warnings:")
        for warning in outcome.warnings:
            diagnostic = diagnose_warning_message(warning)
            lines.append(f"  * [{diagnostic.code}] {diagnostic.summary}")
            if diagnostic.action_hint:
                lines.append(f"    next: {diagnostic.action_hint}")
    return "\n".join(lines)


def render_preflight_summary(result: PreflightResult) -> str:
    """Render broker/account readiness checks."""

    readiness = "BLOCKED" if result.has_failures else "READY_WITH_WARNINGS" if result.has_warnings else "READY"
    lines = [
        "Preflight summary:",
        f"- Broker / Account / Env: {result.broker_name} / {result.account_label} / {result.env_name}",
        f"- Symbols: {', '.join(result.symbols)}",
        f"- Readiness: {readiness}",
    ]
    for check in result.checks:
        lines.append(f"  * [{check.outcome}] {check.name}: {check.message}")
    return "\n".join(lines)


def render_state_doctor_summary(result: StateDoctorResult) -> str:
    """Render state doctor findings."""

    lines = [
        "State doctor summary:",
        f"- Broker / Account: {result.broker_name} / {result.account_label}",
        f"- State file: {result.state_path}",
        f"- Findings: {len(result.issues)}",
    ]
    for issue in result.issues:
        lines.append(f"  * [{issue.severity}] {issue.code}: {issue.message}")
    return "\n".join(lines)


def render_state_prune_summary(result: StatePruneResult) -> str:
    """Render state prune summary."""

    action = "applied" if result.apply else "preview"
    return "\n".join(
        [
            "State prune summary:",
            f"- Broker / Account: {result.broker_name} / {result.account_label}",
            f"- Older Than (days): {result.older_than_days}",
            f"- Mode: {action}",
            f"- Parent Orders Removed: {result.parent_orders_removed}",
            f"- Child Orders Removed: {result.child_orders_removed}",
            f"- Broker Orders Removed: {result.broker_orders_removed}",
            f"- Fill Events Removed: {result.fill_events_removed}",
            f"- Intents Removed: {result.intents_removed}",
            f"- State file: {result.state_path}",
        ]
    )


def render_state_repair_summary(result: StateRepairResult) -> str:
    """Render state repair summary."""

    return "\n".join(
        [
            "State repair summary:",
            f"- Broker / Account: {result.broker_name} / {result.account_label}",
            f"- Cleared Kill Switch: {'yes' if result.cleared_kill_switch else 'no'}",
            f"- Duplicate Fills Removed: {result.duplicate_fills_removed}",
            f"- Orphan Fills Removed: {result.orphan_fills_removed}",
            f"- Orphan Terminal Broker Orders Removed: {result.orphan_terminal_broker_orders_removed}",
            f"- Parent Aggregates Recomputed: {result.parent_aggregates_recomputed}",
            f"- State file: {result.state_path}",
        ]
    )
