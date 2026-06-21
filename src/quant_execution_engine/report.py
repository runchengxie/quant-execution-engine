"""Execution run report — human-readable summary from evidence bundles.

Reads ``outputs/evidence-bundles/*/manifest.json`` to produce operator-friendly
summaries without packing a full evidence bundle first.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .paths import PROJECT_ROOT


class ReportError(RuntimeError):
    """Raised when a report cannot be produced."""


@dataclass(slots=True)
class RunReport:
    """A single run report drawn from an evidence bundle manifest."""

    run_id: str
    broker_name: str | None
    account_label: str | None
    dry_run: bool | None
    created_at: str | None
    bundle_path: str
    included_count: int
    missing_count: int
    skipped_count: int
    audit_record_count: int
    trace_summary: dict[str, Any] | None


def _bundles_dir(project_root: Path) -> Path:
    return project_root / "outputs" / "evidence-bundles"


def _list_bundle_ids(project_root: Path) -> list[str]:
    directory = _bundles_dir(project_root)
    if not directory.exists():
        return []
    ids: list[str] = []
    for path in sorted(directory.iterdir()):
        if path.is_dir() and (path / "manifest.json").exists():
            ids.append(path.name)
    return ids


def _read_manifest(bundle_dir: Path) -> dict[str, Any] | None:
    manifest_path = bundle_dir / "manifest.json"
    if not manifest_path.exists():
        return None
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _build_run_report(bundle_dir: Path, run_id: str) -> RunReport:
    payload = _read_manifest(bundle_dir)
    if payload is None:
        raise ReportError(f"no readable manifest.json in {bundle_dir}")

    return RunReport(
        run_id=run_id,
        broker_name=str(payload.get("broker_name") or "") or None,
        account_label=str(payload.get("account_label") or "") or None,
        dry_run=(
            bool(payload["dry_run"]) if payload.get("dry_run") is not None else None
        ),
        created_at=str(payload.get("created_at") or "") or None,
        bundle_path=str(bundle_dir),
        included_count=int(payload.get("included_artifact_count", 0)),
        missing_count=int(payload.get("missing_artifact_count", 0)),
        skipped_count=int(payload.get("skipped_artifact_count", 0)),
        audit_record_count=int(payload.get("audit_record_count", 0)),
        trace_summary=payload.get("trace_summary"),
    )


def list_run_reports(
    *,
    project_root: Path | None = None,
    broker_filter: str | None = None,
    last_n: int | None = None,
) -> list[RunReport]:
    """Return available run reports, newest first."""
    root = project_root or PROJECT_ROOT
    bundle_ids = _list_bundle_ids(root)

    if broker_filter:
        filtered: list[str] = []
        for bid in bundle_ids:
            manifest = _read_manifest(_bundles_dir(root) / bid)
            if manifest and str(manifest.get("broker_name") or "") == broker_filter:
                filtered.append(bid)
        bundle_ids = filtered

    if last_n is not None and last_n > 0:
        bundle_ids = bundle_ids[-last_n:]

    reports: list[RunReport] = []
    for bid in reversed(bundle_ids):  # newest first
        bundle_dir = _bundles_dir(root) / bid
        try:
            reports.append(_build_run_report(bundle_dir, bid))
        except ReportError:
            continue
    return reports


def get_run_report(
    run_id: str,
    *,
    project_root: Path | None = None,
) -> RunReport:
    """Return a report for a specific run id."""
    root = project_root or PROJECT_ROOT
    bundle_dir = _bundles_dir(root) / run_id
    if not bundle_dir.is_dir():
        available = _list_bundle_ids(root)
        available_text = ", ".join(available) if available else "none"
        raise ReportError(
            f"run id {run_id} not found in {_bundles_dir(root)}; "
            f"available: {available_text}"
        )
    return _build_run_report(bundle_dir, run_id)


def render_run_report(report: RunReport) -> str:
    """Render a single run report for the operator."""
    broker_account = f"{report.broker_name or '-'} / {report.account_label or '-'}"
    mode = "DRY RUN" if report.dry_run else ("LIVE" if report.dry_run is False else "?")

    lines = [
        f"Run: {report.run_id}",
        f"  Broker / Account: {broker_account}",
        f"  Mode:              {mode}",
        f"  Created:           {report.created_at or '-'}",
        f"  Bundle:            {report.bundle_path}",
        f"  Audit records:     {report.audit_record_count}",
        f"  Included: {report.included_count}  Missing: {report.missing_count}"
        f"  Skipped: {report.skipped_count}",
    ]

    trace = report.trace_summary
    if trace:
        trace_count = int(trace.get("trace_count") or 0)
        warning_count = int(trace.get("warning_count") or 0)
        trace_status = str(trace.get("artifact_status") or "unknown")
        ref_count = int(trace.get("trace_order_ref_count") or 0)
        lines.append(
            f"  Traces: {trace_count} trace(s) / {ref_count} ref(s) "
            f"/ {warning_count} warning(s) [{trace_status}]"
        )
        entries = trace.get("entries") or []
        if entries:
            lines.append(f"  Order trace entries ({len(entries)}):")
            lines.append(f"  {'Order Ref':30s} {'Intent':12s} {'Parent':10s} "
                         f"{'Broker':10s} {'Children':>8s} {'Fills':>6s} {'Warnings':>8s}")
            lines.append("  " + "-" * 90)
            for entry in entries:
                order_ref = str(entry.get("order_ref", "-"))[:28]
                intent = str(entry.get("intent_id", "-") or "-")[:10]
                parent_status = str(entry.get("parent_status", "-") or "-")[:8]
                broker_status = str(entry.get("broker_status", "-") or "-")[:8]
                children = int(entry.get("child_attempt_count", 0))
                fills = int(entry.get("fill_event_count", 0))
                warns = int(entry.get("warning_count", 0))
                lines.append(
                    f"  {order_ref:30s} {intent:12s} {parent_status:10s} "
                    f"{broker_status:10s} {children:>8d} {fills:>6d} {warns:>8d}"
                )

    return "\n".join(lines)


def render_run_report_list(reports: list[RunReport]) -> str:
    """Render a listing of run reports."""
    if not reports:
        return "No evidence bundles found."

    lines = [f"Evidence bundles ({len(reports)}):", ""]
    lines.append(
        f"{'Run ID':36s} {'Broker':16s} {'Mode':6s} "
        f"{'Created':20s} {'Incl':>4s} {'Miss':>4s} {'Skip':>4s}"
    )
    lines.append("-" * 100)
    for report in reports:
        run_id = report.run_id[:34]
        broker = (report.broker_name or "-")[:14]
        mode = "dry" if report.dry_run else ("live" if report.dry_run is False else "?")
        created = (report.created_at or "-")[:19]
        lines.append(
            f"{run_id:36s} {broker:16s} {mode:6s} "
            f"{created:20s} {report.included_count:>4d} {report.missing_count:>4d} "
            f"{report.skipped_count:>4d}"
        )
    return "\n".join(lines)
