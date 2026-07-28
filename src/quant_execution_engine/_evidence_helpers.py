"""Evidence bundle collection helpers (filesystem + artifact IO)."""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, cast

from ._evidence_models import EvidenceArtifact


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
        raise EvidenceBundleError(f"run id matched multiple audit logs: {run_id}; {paths}")
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
            reason=("credential or environment files are not copied into evidence bundles"),
        )
    if not source_path.exists() or not source_path.is_file():
        reason = "required artifact was missing" if required else "optional artifact was missing"
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
        return {key: _jsonable(item) for key, item in asdict(cast(Any, value)).items()}
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


def _summarize_order_trace(trace) -> dict[str, Any]:
    return {
        "order_ref": trace.order_ref,
        "state_path": str(trace.state_path),
        "intent_id": trace.intent.intent_id if trace.intent else None,
        "parent_order_id": trace.parent.parent_order_id if trace.parent else None,
        "parent_status": trace.parent.status if trace.parent else None,
        "child_order_id": trace.child.child_order_id if trace.child else None,
        "broker_order_id": (trace.broker_order.broker_order_id if trace.broker_order else None),
        "broker_status": trace.broker_order.status if trace.broker_order else None,
        "child_attempt_count": len(trace.child_orders),
        "tracked_broker_order_count": len(trace.tracked_broker_orders),
        "fill_event_count": len(trace.fill_events),
        "broker_history_order_count": len(trace.broker_history_orders),
        "broker_history_fill_count": len(trace.broker_history_fills),
        "warning_count": len(trace.warnings),
    }


# Re-exported so the public surface of ``evidence_bundle`` stays stable.
from ._evidence_models import EvidenceBundleError  # noqa: E402

__all__ = [
    "EvidenceBundleError",
    "_collect_trace_order_refs",
    "_copy_artifact",
    "_evidence_dir",
    "_find_run_audit",
    "_find_smoke_evidence",
    "_jsonable",
    "_list_audit_logs",
    "_orders_dir",
    "_outputs_dir",
    "_read_jsonl",
    "_resolve_project_path",
    "_summarize_order_trace",
    "_write_generated_artifact",
]
