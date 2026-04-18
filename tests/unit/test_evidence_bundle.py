import json
from pathlib import Path

import pytest

from quant_execution_engine.evidence_bundle import (
    EvidenceBundleError,
    create_evidence_bundle,
)
from quant_execution_engine.execution_state import ExecutionStateStore

pytestmark = pytest.mark.unit


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_audit_log(root: Path, run_id: str, target_path: Path) -> Path:
    path = root / "outputs" / "orders" / "20260416.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    summary = {
        "record_type": "rebalance_summary",
        "run_id": run_id,
        "broker_name": "longport-paper",
        "account_label": "main",
        "dry_run": False,
        "target_input_path": str(target_path.relative_to(root)),
    }
    order = {
        "record_type": "order",
        "run_id": run_id,
        "symbol": "AAPL.US",
    }
    path.write_text(
        "\n".join(json.dumps(record) for record in [summary, order]) + "\n",
        encoding="utf-8",
    )
    return path


def test_create_evidence_bundle_collects_run_artifacts(tmp_path: Path) -> None:
    run_id = "run-123"
    target_path = tmp_path / "outputs" / "targets" / "targets.json"
    _write_json(target_path, {"targets": []})
    audit_path = _write_audit_log(tmp_path, run_id, target_path)
    state_path = ExecutionStateStore(
        root_dir=tmp_path / "outputs" / "state"
    ).path_for("longport-paper", "main")
    _write_json(state_path, {"broker_name": "longport-paper", "account_label": "main"})
    smoke_path = tmp_path / "outputs" / "evidence" / "smoke.json"
    _write_json(
        smoke_path,
        {
            "audit_run_id": run_id,
            "audit_log_path": str(audit_path.relative_to(tmp_path)),
            "operator_notes": ["observed pending cancel"],
        },
    )

    result = create_evidence_bundle(
        run_id=run_id,
        project_root=tmp_path,
        created_at="2026-04-16T00:00:00+00:00",
    )

    assert result.missing_count == 0
    assert result.included_count == 5
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["run_id"] == run_id
    assert manifest["audit_record_count"] == 2
    assert manifest["included_artifact_count"] == 5
    bundled_notes = json.loads(
        (result.bundle_path / "operator_notes.json").read_text(encoding="utf-8")
    )
    assert bundled_notes["operator_notes"] == ["observed pending cancel"]


def test_create_evidence_bundle_skips_sensitive_paths(tmp_path: Path) -> None:
    run_id = "run-sensitive"
    env_path = tmp_path / ".env"
    env_path.write_text("LONGPORT_ACCESS_TOKEN=secret", encoding="utf-8")
    audit_path = tmp_path / "outputs" / "orders" / "20260416.jsonl"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(
        json.dumps(
            {
                "record_type": "rebalance_summary",
                "run_id": run_id,
                "broker_name": "longport-paper",
                "account_label": "main",
                "target_input_path": ".env",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = create_evidence_bundle(run_id=run_id, project_root=tmp_path)

    target_artifact = next(
        artifact for artifact in result.artifacts if artifact.name == "target_input"
    )
    assert target_artifact.status == "skipped_sensitive"
    assert target_artifact.bundle_path is None


def test_create_evidence_bundle_marks_absent_optional_artifacts(tmp_path: Path) -> None:
    run_id = "run-minimal"
    audit_path = tmp_path / "outputs" / "orders" / "20260416.jsonl"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(
        json.dumps(
            {
                "record_type": "rebalance_summary",
                "run_id": run_id,
                "broker_name": "longport-paper",
                "account_label": "main",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = create_evidence_bundle(run_id=run_id, project_root=tmp_path)

    by_name = {artifact.name: artifact for artifact in result.artifacts}
    assert by_name["audit_log"].status == "included"
    assert by_name["target_input"].status == "missing"
    assert by_name["local_state"].status == "missing"
    assert by_name["smoke_evidence"].status == "missing"
    assert by_name["operator_notes"].status == "missing"


def test_create_evidence_bundle_reports_missing_run_candidates(tmp_path: Path) -> None:
    target_path = tmp_path / "outputs" / "targets" / "targets.json"
    _write_json(target_path, {})
    _write_audit_log(tmp_path, "known-run", target_path)

    with pytest.raises(EvidenceBundleError, match="known-run"):
        create_evidence_bundle(run_id="missing-run", project_root=tmp_path)
