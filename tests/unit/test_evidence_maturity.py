import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from quant_execution_engine import evidence_maturity

pytestmark = pytest.mark.unit


def _write_evidence(root: Path, filename: str, broker: str) -> Path:
    path = root / "outputs" / "evidence" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"broker": broker}), encoding="utf-8")
    return path


def test_build_broker_evidence_maturity_report_uses_local_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paper_path = _write_evidence(
        tmp_path,
        "longport-paper-smoke.json",
        "longport-paper",
    )
    ibkr_path = _write_evidence(tmp_path, "ibkr-paper-smoke.json", "ibkr-paper")

    monkeypatch.setattr(
        evidence_maturity,
        "get_broker_capabilities",
        lambda broker_name: SimpleNamespace(
            supports_live_submit=broker_name != "longport-paper",
            supports_cancel=True,
            supports_order_query=True,
            supports_reconcile=True,
            notes=(
                {"submit_mode": "paper"}
                if broker_name == "longport-paper"
                else {}
            ),
        ),
    )

    records = evidence_maturity.build_broker_evidence_maturity_report(
        project_root=tmp_path
    )

    by_broker = {record.broker_name: record for record in records}
    assert by_broker["longport"].evidence_state == "supervised-incomplete"
    assert by_broker["longport-paper"].evidence_state == "complete"
    assert by_broker["longport-paper"].code_path_state == "present"
    assert by_broker["longport-paper"].latest_evidence_path == str(paper_path)
    assert by_broker["ibkr-paper"].evidence_state == "incomplete"
    assert by_broker["ibkr-paper"].latest_evidence_path == str(ibkr_path)
    assert (
        "effective-market-data broker submit/query/cancel or fill evidence"
        in by_broker["ibkr-paper"].missing_evidence
    )


def test_render_broker_evidence_maturity_surfaces_next_smoke() -> None:
    record = evidence_maturity.BrokerEvidenceMaturity(
        broker_name="ibkr-paper",
        broker_mode="paper",
        code_path_state="present",
        evidence_state="incomplete",
        latest_evidence_path=None,
        missing_evidence=["broker order evidence"],
        recommended_next_smoke="Run valid-market-data smoke.",
        notes=["Gateway is reachable."],
    )

    output = evidence_maturity.render_broker_evidence_maturity([record])

    assert "ibkr-paper" in output
    assert "missing: broker order evidence" in output
    assert "next: Run valid-market-data smoke." in output
    assert "note: Gateway is reachable." in output
