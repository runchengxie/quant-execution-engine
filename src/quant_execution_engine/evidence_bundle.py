"""Evidence bundle builder for local execution runs (public facade).

The public surface (``create_evidence_bundle``, ``render_evidence_bundle_result``
and the data models) is preserved here. The implementation lives in the focused
submodules (``_evidence_models`` / ``_evidence_helpers``); this file keeps the
entry-point logic and re-exports the helpers.

``OrderLifecycleService`` is re-exported as a module attribute so tests that
``monkeypatch`` it on this module (e.g. ``setattr(evidence_bundle,
"OrderLifecycleService", ...)``) keep affecting :func:`create_evidence_bundle`.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ._evidence_helpers import (
    _collect_trace_order_refs,
    _copy_artifact,
    _find_run_audit,
    _find_smoke_evidence,
    _outputs_dir,
    _resolve_project_path,
    _summarize_order_trace,
    _write_generated_artifact,
)
from ._evidence_models import (
    EvidenceArtifact,
    EvidenceBundleError,
    EvidenceBundleResult,
    GeneratedArtifactCapture,
)
from .broker import get_broker_adapter
from .execution import OrderLifecycleService
from .execution_state import ExecutionStateStore
from .paths import PROJECT_ROOT

__all__ = [
    "EvidenceArtifact",
    "EvidenceBundleError",
    "EvidenceBundleResult",
    "GeneratedArtifactCapture",
    "OrderLifecycleService",
    "create_evidence_bundle",
    "render_evidence_bundle_result",
]


def _build_order_trace_artifact(
    *,
    project_root: Path,
    bundle_path: Path,
    run_id: str,
    broker_name: str | None,
    account_label: str | None,
    dry_run: bool | None,
    matching_records: list[dict[str, Any]],
) -> GeneratedArtifactCapture:
    if not broker_name or not account_label:
        artifact = EvidenceArtifact(
            name="order_traces",
            artifact_type="trace",
            status="skipped_not_applicable",
            reason="broker_name/account_label were unavailable for trace capture",
        )
        return GeneratedArtifactCapture(
            artifact=artifact,
            manifest_summary={
                "artifact_status": artifact.status,
                "artifact_bundle_path": artifact.bundle_path,
                "artifact_reason": artifact.reason,
                "trace_order_ref_count": 0,
                "trace_count": 0,
                "warning_count": 0,
                "entries": [],
            },
        )

    order_refs = _collect_trace_order_refs(matching_records)
    if not order_refs:
        artifact = EvidenceArtifact(
            name="order_traces",
            artifact_type="trace",
            status="skipped_not_applicable",
            reason="audit log contained no traceable order references",
        )
        return GeneratedArtifactCapture(
            artifact=artifact,
            manifest_summary={
                "artifact_status": artifact.status,
                "artifact_bundle_path": artifact.bundle_path,
                "artifact_reason": artifact.reason,
                "trace_order_ref_count": 0,
                "trace_count": 0,
                "warning_count": 0,
                "entries": [],
            },
        )

    adapter = None
    warnings: list[str] = []
    traces: list[Any] = []
    try:
        try:
            adapter = get_broker_adapter(broker_name=broker_name)
        except Exception as exc:
            artifact = EvidenceArtifact(
                name="order_traces",
                artifact_type="trace",
                status="skipped_unavailable",
                reason=f"failed to initialize broker adapter for trace capture: {exc}",
            )
            return GeneratedArtifactCapture(
                artifact=artifact,
                manifest_summary={
                    "artifact_status": artifact.status,
                    "artifact_bundle_path": artifact.bundle_path,
                    "artifact_reason": artifact.reason,
                    "trace_order_ref_count": len(order_refs),
                    "trace_count": 0,
                    "warning_count": 0,
                    "entries": [],
                },
            )

        service = OrderLifecycleService(
            adapter,
            state_store=ExecutionStateStore(root_dir=_outputs_dir(project_root) / "state"),
        )
        for order_ref in order_refs:
            try:
                traces.append(
                    service.get_order_trace(account_label=account_label, order_ref=order_ref)
                )
            except Exception as exc:
                warnings.append(f"{order_ref}: {exc}")
        payload = {
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "run_id": run_id,
            "broker_name": broker_name,
            "account_label": account_label,
            "dry_run": dry_run,
            "trace_order_refs": order_refs,
            "trace_count": len(traces),
            "warning_count": len(warnings),
            "warnings": warnings,
            "traces": traces,
        }
        reason = f"{len(warnings)} trace(s) could not be resolved" if warnings else None
        artifact = _write_generated_artifact(
            bundle_path=bundle_path,
            artifact_type="trace",
            name="order_traces",
            filename="order_traces.json",
            payload=payload,
            reason=reason,
        )
        return GeneratedArtifactCapture(
            artifact=artifact,
            manifest_summary={
                "artifact_status": artifact.status,
                "artifact_bundle_path": artifact.bundle_path,
                "artifact_reason": artifact.reason,
                "trace_order_ref_count": len(order_refs),
                "trace_count": len(traces),
                "warning_count": len(warnings),
                "entries": [_summarize_order_trace(trace) for trace in traces],
                "warnings": warnings,
            },
        )
    finally:
        close_fn = getattr(adapter, "close", None)
        if callable(close_fn):
            close_fn()


def create_evidence_bundle(
    *,
    run_id: str,
    project_root: Path | None = None,
    output_dir: Path | None = None,
    operator_notes: list[str] | None = None,
    created_at: str | None = None,
) -> EvidenceBundleResult:
    """Create a local evidence bundle for an execution run id."""

    root = project_root or PROJECT_ROOT
    normalized_run_id = str(run_id).strip()
    if not normalized_run_id:
        raise EvidenceBundleError("run id is required")
    audit_log_path, audit_records, _ = _find_run_audit(root, normalized_run_id)
    matching_records = [
        record for record in audit_records if str(record.get("run_id") or "") == normalized_run_id
    ]
    summary = next(
        (record for record in matching_records if record.get("record_type") == "rebalance_summary"),
        matching_records[0],
    )
    broker_name = str(summary.get("broker_name") or "") or None
    account_label = str(summary.get("account_label") or "") or None
    target_input_path = (
        str(summary.get("target_input_path")) if summary.get("target_input_path") else None
    )
    state_path = None
    if broker_name and account_label:
        state_path = ExecutionStateStore(root_dir=_outputs_dir(root) / "state").path_for(
            broker_name, account_label
        )
    smoke_path = _find_smoke_evidence(
        root,
        run_id=normalized_run_id,
        audit_log_path=audit_log_path,
        target_input_path=target_input_path,
    )

    bundle_root = output_dir or (_outputs_dir(root) / "evidence-bundles")
    bundle_path = bundle_root / normalized_run_id
    bundle_path.mkdir(parents=True, exist_ok=True)
    generated_at = created_at or datetime.now(timezone.utc).isoformat()
    dry_run = bool(summary.get("dry_run")) if summary.get("dry_run") is not None else None

    trace_capture = _build_order_trace_artifact(
        project_root=root,
        bundle_path=bundle_path,
        run_id=normalized_run_id,
        broker_name=broker_name,
        account_label=account_label,
        dry_run=dry_run,
        matching_records=matching_records,
    )

    artifacts = [
        _copy_artifact(
            project_root=root,
            source_path=audit_log_path,
            bundle_path=bundle_path,
            artifact_type="audit",
            name="audit_log",
            required=True,
        ),
        _copy_artifact(
            project_root=root,
            source_path=_resolve_project_path(root, target_input_path),
            bundle_path=bundle_path,
            artifact_type="targets",
            name="target_input",
        ),
        _copy_artifact(
            project_root=root,
            source_path=state_path,
            bundle_path=bundle_path,
            artifact_type="state",
            name="local_state",
        ),
        _copy_artifact(
            project_root=root,
            source_path=smoke_path,
            bundle_path=bundle_path,
            artifact_type="smoke",
            name="smoke_evidence",
        ),
        trace_capture.artifact,
    ]

    note_values = list(operator_notes or [])
    if smoke_path is not None:
        try:
            smoke_payload = json.loads(smoke_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            smoke_payload = {}
        if isinstance(smoke_payload, dict):
            note_values.extend(str(item) for item in (smoke_payload.get("operator_notes") or []))
    if note_values:
        notes_path = bundle_path / "operator_notes.json"
        notes_payload = {"operator_notes": note_values}
        notes_path.write_text(
            json.dumps(notes_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        artifacts.append(
            EvidenceArtifact(
                name="operator_notes",
                artifact_type="notes",
                status="included",
                source_path=None,
                bundle_path=str(notes_path.relative_to(bundle_path)),
            )
        )
    else:
        artifacts.append(
            EvidenceArtifact(
                name="operator_notes",
                artifact_type="notes",
                status="missing",
                reason="operator notes were not provided",
            )
        )

    result = EvidenceBundleResult(
        run_id=normalized_run_id,
        broker_name=broker_name,
        account_label=account_label,
        dry_run=dry_run,
        bundle_path=bundle_path,
        manifest_path=bundle_path / "manifest.json",
        trace_summary=trace_capture.manifest_summary,
        artifacts=artifacts,
    )
    manifest = {
        "created_at": generated_at,
        "run_id": normalized_run_id,
        "broker_name": broker_name,
        "account_label": account_label,
        "dry_run": result.dry_run,
        "bundle_path": str(bundle_path),
        "audit_record_count": len(matching_records),
        "included_artifact_count": result.included_count,
        "missing_artifact_count": result.missing_count,
        "skipped_artifact_count": result.skipped_count,
        "trace_summary": result.trace_summary,
        "artifacts": [artifact.to_payload() for artifact in artifacts],
    }
    result.manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return result


def render_evidence_bundle_result(result: EvidenceBundleResult) -> str:
    """Render an evidence bundle result for operator review."""

    broker_account = f"{result.broker_name or '-'} / {result.account_label or '-'}"
    trace_summary = result.trace_summary or {}
    trace_count = int(trace_summary.get("trace_count") or 0)
    trace_order_ref_count = int(trace_summary.get("trace_order_ref_count") or 0)
    warning_count = int(trace_summary.get("warning_count") or 0)
    trace_status = str(trace_summary.get("artifact_status") or "unknown")
    lines = [
        "Evidence bundle created:",
        f"- Run ID: {result.run_id}",
        f"- Broker / Account: {broker_account}",
        f"- Bundle path: {result.bundle_path}",
        f"- Manifest: {result.manifest_path}",
        f"- Included artifacts: {result.included_count}",
        f"- Missing artifacts: {result.missing_count}",
        f"- Skipped artifacts: {result.skipped_count}",
        "- Trace summary: "
        f"{trace_count} trace(s) / {trace_order_ref_count} ref(s) / "
        f"{warning_count} warning(s) [{trace_status}]",
    ]
    if warning_count:
        lines.append("- Trace warnings: inspect manifest.json trace_summary.warnings")
    lines.append(
        "- Review: inspect manifest.json first, then compare "
        "audit/state/target/smoke/trace artifacts."
    )
    return "\n".join(lines)
