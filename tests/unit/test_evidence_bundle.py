import json
from pathlib import Path

import pytest

import quant_execution_engine.evidence_bundle as evidence_bundle
from quant_execution_engine.broker.base import BrokerOrderRecord
from quant_execution_engine.evidence_bundle import (
    EvidenceBundleError,
    create_evidence_bundle,
)
from quant_execution_engine.execution_state import (
    ChildOrder,
    ExecutionOrderTrace,
    ExecutionStateStore,
    OrderIntent,
    ParentOrder,
)

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
        "child_order_id": "child-1",
    }
    path.write_text(
        "\n".join(json.dumps(record) for record in [summary, order]) + "\n",
        encoding="utf-8",
    )
    return path


class _FakeTraceAdapter:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _FakeTraceService:
    def __init__(self, adapter: object, *, state_store: object) -> None:
        self.adapter = adapter
        self.state_store = state_store

    def get_order_trace(
        self,
        *,
        account_label: str,
        order_ref: str,
    ) -> ExecutionOrderTrace:
        return ExecutionOrderTrace(
            broker_name="longport-paper",
            account_label=account_label,
            order_ref=order_ref,
            state_path=Path("/tmp/state.json"),
            intent=OrderIntent(
                intent_id="intent-1",
                symbol="AAPL.US",
                side="BUY",
                quantity=10,
                order_type="LIMIT",
                broker_name="longport-paper",
                account_label=account_label,
            ),
            parent=ParentOrder(
                parent_order_id="parent-1",
                intent_id="intent-1",
                symbol="AAPL.US",
                side="BUY",
                requested_quantity=10,
                remaining_quantity=0,
                status="FILLED",
                child_order_ids=["child-1"],
            ),
            child=ChildOrder(
                child_order_id="child-1",
                parent_order_id="parent-1",
                intent_id="intent-1",
                quantity=10,
                attempt=1,
                broker_order_id="broker-1",
                status="FILLED",
            ),
            broker_order=BrokerOrderRecord(
                broker_order_id="broker-1",
                symbol="AAPL.US",
                side="BUY",
                quantity=10,
                filled_quantity=10,
                status="FILLED",
                broker_name="longport-paper",
                account_label=account_label,
            ),
        )


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
    fake_adapter = _FakeTraceAdapter()
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        evidence_bundle,
        "get_broker_adapter",
        lambda broker_name=None: fake_adapter,
    )
    monkeypatch.setattr(evidence_bundle, "OrderLifecycleService", _FakeTraceService)

    try:
        result = create_evidence_bundle(
            run_id=run_id,
            project_root=tmp_path,
            created_at="2026-04-16T00:00:00+00:00",
        )
    finally:
        monkeypatch.undo()

    assert result.missing_count == 0
    assert result.included_count == 6
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["run_id"] == run_id
    assert manifest["audit_record_count"] == 2
    assert manifest["included_artifact_count"] == 6
    trace_payload = json.loads(
        (result.bundle_path / "trace" / "order_traces.json").read_text(encoding="utf-8")
    )
    assert trace_payload["trace_order_refs"] == ["child-1"]
    assert trace_payload["trace_count"] == 1
    bundled_notes = json.loads(
        (result.bundle_path / "operator_notes.json").read_text(encoding="utf-8")
    )
    assert bundled_notes["operator_notes"] == ["observed pending cancel"]
    assert fake_adapter.closed is True


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
    assert by_name["order_traces"].status == "skipped_not_applicable"
    assert by_name["operator_notes"].status == "missing"


def test_create_evidence_bundle_reports_missing_run_candidates(tmp_path: Path) -> None:
    target_path = tmp_path / "outputs" / "targets" / "targets.json"
    _write_json(target_path, {})
    _write_audit_log(tmp_path, "known-run", target_path)

    with pytest.raises(EvidenceBundleError, match="known-run"):
        create_evidence_bundle(run_id="missing-run", project_root=tmp_path)
