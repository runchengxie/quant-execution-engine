"""Shared helpers for the table renderers.

These private helpers and the import surface are shared by the focused table
renderer submodules (``_table_market`` / ``_table_broker`` / ``_table_execution``
/ ``_table_state``). They live here so the submodules stay small while still
being importable independently.
"""

from __future__ import annotations

from typing import Any


def _append_diagnostic(lines: list[str], diagnostic: Any | None) -> None:
    if diagnostic is None:
        return
    lines.append(f"- Diagnostic: [{diagnostic.code}] {diagnostic.summary}")
    if diagnostic.action_hint:
        lines.append(f"- Suggested Next Step: {diagnostic.action_hint}")


def _append_parent_lines(lines: list[str], parent: Any | None) -> None:
    if parent is None:
        return
    lines.extend(
        [
            f"- Parent: {parent.parent_order_id}",
            f"- Parent Status: {parent.status}",
            "- Parent Filled / Remaining: "
            f"{parent.filled_quantity:g} / "
            f"{parent.remaining_quantity:g}",
        ]
    )


def _append_child_selection_lines(lines: list[str], child: Any | None) -> None:
    if child is None:
        return
    lines.append(
        f"- Selected Child: {child.child_order_id} (attempt {child.attempt}, status {child.status})"
    )
