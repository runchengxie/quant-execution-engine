"""Audit-log discovery and skipped-step bookkeeping for the operator smoke harness."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from project_tools.smoke_operator.steps import planned_workflow_steps


def audit_log_dir() -> Path:
    from project_tools.smoke_operator_harness import PROJECT_ROOT

    return PROJECT_ROOT / "outputs" / "orders"


def list_audit_logs() -> list[Path]:
    directory = audit_log_dir()
    if not directory.exists():
        return []
    return sorted(path for path in directory.glob("*.jsonl") if path.is_file())


def read_audit_summary(path: Path) -> dict[str, object] | None:
    try:
        with path.open("r", encoding="utf-8") as handle:
            first_line = handle.readline().strip()
    except OSError:
        return None
    if not first_line:
        return None
    try:
        payload = json.loads(first_line)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def discover_audit_log(
    *,
    baseline_paths: set[Path] | None = None,
    target_input_path: str | None = None,
) -> tuple[Path | None, dict[str, object] | None]:
    candidates = [path for path in list_audit_logs() if path not in (baseline_paths or set())]
    if not candidates:
        return None, None

    normalized_target_input = None if target_input_path is None else str(target_input_path).strip()
    ranked: list[tuple[int, float, str, Path, dict[str, object] | None]] = []
    for path in candidates:
        summary = read_audit_summary(path)
        score = 0
        if summary is not None and summary.get("record_type") == "rebalance_summary":
            score += 1
        if (
            normalized_target_input is not None
            and summary is not None
            and str(summary.get("target_input_path") or "").strip() == normalized_target_input
        ):
            score += 2
        ranked.append((score, path.stat().st_mtime, path.name, path, summary))
    ranked.sort(reverse=True)
    _, _, _, chosen_path, chosen_summary = ranked[0]
    return chosen_path, chosen_summary


def append_skipped_step(
    skipped_steps: list[dict[str, str]],
    *,
    name: str,
    reason: str,
) -> None:
    existing = {item["name"] for item in skipped_steps}
    if name in existing:
        return
    skipped_steps.append({"name": name, "reason": reason})


def finalize_skipped_steps(
    *,
    args: argparse.Namespace,
    steps: list[dict[str, object]],
    skipped_steps: list[dict[str, str]],
    failed_step: str | None = None,
) -> list[dict[str, str]]:
    finalized = list(skipped_steps)
    if not failed_step:
        return finalized
    planned_steps = planned_workflow_steps(args)
    if failed_step not in planned_steps:
        return finalized
    seen_steps = {str(step.get("name")) for step in steps}
    recorded_steps = {item["name"] for item in finalized}
    failed_index = planned_steps.index(failed_step)
    for name in planned_steps[failed_index + 1 :]:
        if name in seen_steps or name in recorded_steps:
            continue
        append_skipped_step(
            finalized,
            name=name,
            reason=f"workflow stopped after failed step '{failed_step}'",
        )
    return finalized
