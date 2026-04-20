"""Evidence bundle builder for local execution runs."""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .broker import get_broker_adapter
from .execution import OrderLifecycleService
from .execution_state import ExecutionOrderTrace, ExecutionStateStore
from .paths import PROJECT_ROOT


class EvidenceBundleError(RuntimeError):
    """Raised when an evidence bundle cannot be produced safely."""


@dataclass(slots=True)
class EvidenceArtifact:
    """Single artifact recorded in an evidence bundle manifest."""

    name: str
    artifact_type: str
    status: str
    source_path: str | None = None
    bundle_path: str | None = None
    reason: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "artifact_type": self.artifact_type,
            "status": self.status,
            "source_path": self.source_path,
            "bundle_path": self.bundle_path,
            "reason": self.reason,
        }


@dataclass(slots=True)
class GeneratedArtifactCapture:
    """Generated artifact plus a compact manifest summary."""

    artifact: EvidenceArtifact
    manifest_summary: dict[str, Any] | None = None


@dataclass(slots=True)
class EvidenceBundleResult:
    """Summary of a generated evidence bundle."""

    run_id: str
    broker_name: str | None
    account_label: str | None
    dry_run: bool | None
    bundle_path: Path
    manifest_path: Path
    artifacts: list[EvidenceArtifact] = field(default_factory=list)

    @property
    def included_count(self) -> int:
        return sum(1 for artifact in self.artifacts if artifact.status == "included")

    @property
    def missing_count(self) -> int:
        return sum(1 for artifact in self.artifacts if artifact.status == "missing")

    @property
    def skipped_count(self) -> int:
        return sum(
            1
            for artifact in self.artifacts
            if artifact.status.startswith("skipped")
        )


def _outputs_dir(project_root: Path) -> Path:
    return project_root / "outputs"


def _orders_dir(project_root: Path) -> Path:
    return _outputs_dir(project_root) / "orders"


def _evidence_dir(project_root: Path) -> Path:
    return _outputs_dir(project_root) / "evidence"


def _resolve_project_path(project_root: Path, raw_path: str | None) -> Path | None:
    if not raw_path:
        return None
    path = Path(str(raw_path))
    return path if path.is_absolute() else project_root / path


def _is_sensitive_path(path: Path) -> bool:
    name = path.name.lower()
    return name.startswith(".env") or name == ".envrc" or name.endswith(".env")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return records
    for line in lines:
        text = line.strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            records.append(payload)
    return records


def _list_audit_logs(project_root: Path) -> list[Path]:
    directory = _orders_dir(project_root)
    if not directory.exists():
        return []
    return sorted(path for path in directory.glob("*.jsonl") if path.is_file())


def _find_run_audit(
    project_root: Path, run_id: str
) -> tuple[Path, list[dict[str, Any]], list[str]]:
    candidates: list[str] = []
    matches: list[tuple[Path, list[dict[str, Any]]]] = []
    for path in _list_audit_logs(project_root):
        records = _read_jsonl(path)
        for record in records:
            candidate = record.get("run_id")
            if candidate:
                candidates.append(str(candidate))
        if any(str(record.get("run_id") or "") == run_id for record in records):
            matches.append((path, records))
    if not matches:
        unique_candidates = sorted(set(candidates))
        searched = _orders_dir(project_root)
        candidate_text = ", ".join(unique_candidates[:20]) or "-"
        raise EvidenceBundleError(
            "run id not found in audit logs: "
            f"{run_id}; searched={searched}; candidates={candidate_text}"
        )
    if len(matches) > 1:
        paths = ", ".join(str(path) for path, _ in matches)
        raise EvidenceBundleError(
            f"run id matched multiple audit logs: {run_id}; {paths}"
        )
    return matches[0][0], matches[0][1], sorted(set(candidates))


def _find_smoke_evidence(
    project_root: Path,
    *,
    run_id: str,
    audit_log_path: Path,
    target_input_path: str | None,
) -> Path | None:
    directory = _evidence_dir(project_root)
    if not directory.exists():
        return None
    matches: list[Path] = []
    audit_resolved = str(audit_log_path.resolve())
    if audit_log_path.is_relative_to(project_root):
        audit_project_relative = str(audit_log_path.relative_to(project_root))
    else:
        audit_project_relative = str(audit_log_path)
    for path in directory.glob("*.json"):
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        if str(payload.get("audit_run_id") or "") == run_id:
            matches.append(path)
            continue
        raw_audit = str(payload.get("audit_log_path") or "")
        if raw_audit in {audit_resolved, audit_project_relative, str(audit_log_path)}:
            matches.append(path)
            continue
        if (
            target_input_path
            and str(payload.get("audit_target_input_path") or "") == target_input_path
        ):
            matches.append(path)
    if not matches:
        return None
    return sorted(matches, key=lambda item: (item.stat().st_mtime, item.name))[-1]


def _copy_artifact(
    *,
    project_root: Path,
    source_path: Path | None,
    bundle_path: Path,
    artifact_type: str,
    name: str,
    required: bool = False,
) -> EvidenceArtifact:
    if source_path is None:
        return EvidenceArtifact(
            name=name,
            artifact_type=artifact_type,
            status="missing",
            reason="artifact path was not available",
        )
    if _is_sensitive_path(source_path):
        return EvidenceArtifact(
            name=name,
            artifact_type=artifact_type,
            status="skipped_sensitive",
            source_path=str(source_path),
            reason=(
                "credential or environment files are not copied into "
                "evidence bundles"
            ),
        )
    if not source_path.exists() or not source_path.is_file():
        reason = (
            "required artifact was missing"
            if required
            else "optional artifact was missing"
        )
        return EvidenceArtifact(
            name=name,
            artifact_type=artifact_type,
            status="missing",
            source_path=str(source_path),
            reason=reason,
        )
    destination_dir = bundle_path / artifact_type
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / source_path.name
    shutil.copy2(source_path, destination)
    try:
        source_display = str(source_path.relative_to(project_root))
    except ValueError:
        source_display = str(source_path)
    return EvidenceArtifact(
        name=name,
        artifact_type=artifact_type,
        status="included",
        source_path=source_display,
        bundle_path=str(destination.relative_to(bundle_path)),
    )


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return {key: _jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if hasattr(value, "__fspath__"):
        return str(value)
    return value


def _write_generated_artifact(
    *,
    bundle_path: Path,
    artifact_type: str,
    name: str,
    filename: str,
    payload: Any,
    reason: str | None = None,
) -> EvidenceArtifact:
    destination_dir = bundle_path / artifact_type
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / filename
    destination.write_text(
        json.dumps(_jsonable(payload), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return EvidenceArtifact(
        name=name,
        artifact_type=artifact_type,
        status="included",
        source_path=None,
        bundle_path=str(destination.relative_to(bundle_path)),
        reason=reason,
    )


def _collect_trace_order_refs(records: list[dict[str, Any]]) -> list[str]:
    refs: list[str] = []
    for record in records:
        if record.get("record_type") != "order":
            continue
        for key in ("broker_order_id", "child_order_id", "client_order_id", "order_id"):
            value = str(record.get(key) or "").strip()
            if value:
                if value not in refs:
                    refs.append(value)
                break
    return refs


def _summarize_order_trace(trace: ExecutionOrderTrace) -> dict[str, Any]:
    return {
        "order_ref": trace.order_ref,
        "state_path": str(trace.state_path),
        "intent_id": trace.intent.intent_id if trace.intent else None,
        "parent_order_id": trace.parent.parent_order_id if trace.parent else None,
        "parent_status": trace.parent.status if trace.parent else None,
        "child_order_id": trace.child.child_order_id if trace.child else None,
        "broker_order_id": (
            trace.broker_order.broker_order_id if trace.broker_order else None
        ),
        "broker_status": trace.broker_order.status if trace.broker_order else None,
        "child_attempt_count": len(trace.child_orders),
        "tracked_broker_order_count": len(trace.tracked_broker_orders),
        "fill_event_count": len(trace.fill_events),
        "broker_history_order_count": len(trace.broker_history_orders),
        "broker_history_fill_count": len(trace.broker_history_fills),
        "warning_count": len(trace.warnings),
    }


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
    traces: list[ExecutionOrderTrace] = []
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
        reason = (
            f"{len(warnings)} trace(s) could not be resolved"
            if warnings
            else None
        )
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
        record
        for record in audit_records
        if str(record.get("run_id") or "") == normalized_run_id
    ]
    summary = next(
        (
            record
            for record in matching_records
            if record.get("record_type") == "rebalance_summary"
        ),
        matching_records[0],
    )
    broker_name = str(summary.get("broker_name") or "") or None
    account_label = str(summary.get("account_label") or "") or None
    target_input_path = (
        str(summary.get("target_input_path"))
        if summary.get("target_input_path")
        else None
    )
    state_path = None
    if broker_name and account_label:
        state_path = ExecutionStateStore(
            root_dir=_outputs_dir(root) / "state"
        ).path_for(broker_name, account_label)
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
    dry_run = (
        bool(summary.get("dry_run"))
        if summary.get("dry_run") is not None
        else None
    )

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
            note_values.extend(
                str(item)
                for item in (smoke_payload.get("operator_notes") or [])
            )
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
        "trace_summary": trace_capture.manifest_summary,
        "artifacts": [artifact.to_payload() for artifact in artifacts],
    }
    result.manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return result


def render_evidence_bundle_result(result: EvidenceBundleResult) -> str:
    """Render an evidence bundle result for operator review."""

    broker_account = (
        f"{result.broker_name or '-'} / {result.account_label or '-'}"
    )
    return "\n".join(
        [
            "Evidence bundle created:",
            f"- Run ID: {result.run_id}",
            f"- Broker / Account: {broker_account}",
            f"- Bundle path: {result.bundle_path}",
            f"- Manifest: {result.manifest_path}",
            f"- Included artifacts: {result.included_count}",
            f"- Missing artifacts: {result.missing_count}",
            f"- Skipped artifacts: {result.skipped_count}",
            "- Review: inspect manifest.json first, then compare "
            "audit/state/target/smoke/trace artifacts.",
        ]
    )
