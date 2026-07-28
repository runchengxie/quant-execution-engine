"""State maintenance result models and shared constants.

These dataclasses and the timestamp helper are the public data types returned
by :class:`StateMaintenanceService` (defined in ``state_tools``) and the shared
constants reused by the focused state-maintenance submodules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .execution import TERMINAL_BROKER_STATUSES

TERMINAL_PARENT_STATUSES = TERMINAL_BROKER_STATUSES | {
    "BLOCKED",
    "FILLED",
    "ACCEPTED_PARTIAL",
}


@dataclass(slots=True)
class StateDoctorIssue:
    """Single state consistency finding."""

    severity: str
    code: str
    message: str


@dataclass(slots=True)
class StateDoctorResult:
    """State inspection summary."""

    broker_name: str
    account_label: str
    state_path: Path
    issues: list[StateDoctorIssue] = field(default_factory=list)


@dataclass(slots=True)
class StatePruneResult:
    """State prune summary."""

    broker_name: str
    account_label: str
    state_path: Path
    older_than_days: int
    apply: bool
    parent_orders_removed: int = 0
    child_orders_removed: int = 0
    broker_orders_removed: int = 0
    fill_events_removed: int = 0
    intents_removed: int = 0


@dataclass(slots=True)
class StateRepairResult:
    """State repair summary."""

    broker_name: str
    account_label: str
    state_path: Path
    cleared_kill_switch: bool = False
    duplicate_fills_removed: int = 0
    orphan_fills_removed: int = 0
    orphan_terminal_broker_orders_removed: int = 0
    parent_aggregates_recomputed: int = 0


def _parse_timestamp(value: str | None) -> datetime | None:
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
