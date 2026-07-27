"""Reproducible evidence record writer for the operator smoke harness."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from quant_execution_engine.broker import is_paper_broker
from quant_execution_engine.execution import ExecutionStateStore


def write_evidence(
    *,
    args: argparse.Namespace,
    broker: str,
    account_label: str,
    canonical: str,
    steps: list[dict[str, object]],
    output_path: Path,
    latest_order_ref: str | None,
    success: bool = True,
    failure_message: str | None = None,
    failed_step: str | None = None,
    failure_category: str | None = None,
    next_step_hint: str | None = None,
    skipped_steps: list[dict[str, str]] | None = None,
    operator_outcome: dict[str, object] | None = None,
    audit_log_path: Path | None = None,
    audit_summary: dict[str, object] | None = None,
) -> Path | None:
    evidence_output = getattr(args, "evidence_output", None)
    if not evidence_output:
        return None
    evidence_path = Path(evidence_output)
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "broker": broker,
        "broker_mode": "paper" if is_paper_broker(broker) else "real",
        "account_label": account_label,
        "symbol": canonical,
        "execute": bool(args.execute),
        "preflight_only": bool(args.preflight_only),
        "cleanup_open_orders": bool(args.cleanup_open_orders),
        "allow_non_paper": bool(args.allow_non_paper),
        "operator_notes": list(getattr(args, "operator_notes", []) or []),
        "targets_output": str(output_path),
        "state_path": str(ExecutionStateStore().path_for(broker, account_label)),
        "audit_log_path": str(audit_log_path) if audit_log_path is not None else None,
        "audit_run_id": (
            str(audit_summary.get("run_id"))
            if audit_summary is not None and audit_summary.get("run_id")
            else None
        ),
        "audit_order_count": (
            int(audit_summary.get("order_count"))
            if audit_summary is not None and audit_summary.get("order_count") is not None
            else None
        ),
        "audit_target_input_path": (
            str(audit_summary.get("target_input_path"))
            if audit_summary is not None and audit_summary.get("target_input_path")
            else None
        ),
        "latest_tracked_order_ref": latest_order_ref,
        "success": bool(success),
        "failure_message": failure_message,
        "failed_step": failed_step,
        "failure_category": failure_category,
        "next_step_hint": next_step_hint,
        "skipped_steps": list(skipped_steps or []),
        "operator_outcome_status": (
            operator_outcome.get("status") if operator_outcome is not None else None
        ),
        "operator_outcome_source": (
            operator_outcome.get("source") if operator_outcome is not None else None
        ),
        "operator_outcome_message": (
            operator_outcome.get("message") if operator_outcome is not None else None
        ),
        "operator_outcome_category": (
            operator_outcome.get("category") if operator_outcome is not None else None
        ),
        "operator_next_step_hint": (
            operator_outcome.get("next_step_hint") if operator_outcome is not None else None
        ),
        "operator_outcome_parent_order_id": (
            operator_outcome.get("parent_order_id") if operator_outcome is not None else None
        ),
        "operator_outcome_child_order_id": (
            operator_outcome.get("child_order_id") if operator_outcome is not None else None
        ),
        "operator_outcome_broker_order_id": (
            operator_outcome.get("broker_order_id") if operator_outcome is not None else None
        ),
        "operator_outcome_client_order_id": (
            operator_outcome.get("client_order_id") if operator_outcome is not None else None
        ),
        "steps": steps,
    }
    evidence_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n== evidence ==\nWrote {evidence_path}")
    return evidence_path
