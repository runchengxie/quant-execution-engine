"""State / preflight table renderers."""

from __future__ import annotations

from ..preflight import PreflightResult
from ..state_tools import StateDoctorResult, StatePruneResult, StateRepairResult


def render_preflight_summary(result: PreflightResult) -> str:
    """Render broker/account readiness checks."""

    readiness = (
        "BLOCKED"
        if result.has_failures
        else "READY_WITH_WARNINGS"
        if result.has_warnings
        else "READY"
    )
    lines = [
        "Preflight summary:",
        f"- Broker / Account / Env: "
        f"{result.broker_name} / {result.account_label} / {result.env_name}",
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
            "- Orphan Terminal Broker Orders Removed: "
            f"{result.orphan_terminal_broker_orders_removed}",
            f"- Parent Aggregates Recomputed: {result.parent_aggregates_recomputed}",
            f"- State file: {result.state_path}",
        ]
    )
