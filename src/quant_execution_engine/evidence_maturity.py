"""Broker evidence maturity reporting."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .broker.factory import get_broker_capabilities
from .paths import PROJECT_ROOT


@dataclass(slots=True)
class BrokerEvidenceMaturity:
    """Evidence status for one broker backend."""

    broker_name: str
    broker_mode: str
    code_path_state: str
    evidence_state: str
    latest_evidence_path: str | None
    missing_evidence: list[str] = field(default_factory=list)
    recommended_next_smoke: str | None = None
    notes: list[str] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        return {
            "broker_name": self.broker_name,
            "broker_mode": self.broker_mode,
            "code_path_state": self.code_path_state,
            "evidence_state": self.evidence_state,
            "latest_evidence_path": self.latest_evidence_path,
            "missing_evidence": list(self.missing_evidence),
            "recommended_next_smoke": self.recommended_next_smoke,
            "notes": list(self.notes),
        }


def _evidence_dir(project_root: Path) -> Path:
    return project_root / "outputs" / "evidence"


def _candidate_evidence_files(project_root: Path, broker_name: str) -> list[Path]:
    directory = _evidence_dir(project_root)
    if not directory.exists():
        return []
    candidates: list[Path] = []
    for path in directory.glob("*.json"):
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        payload_broker = str(payload.get("broker") or "").strip()
        if payload_broker == broker_name:
            candidates.append(path)
    return sorted(candidates, key=lambda item: (item.stat().st_mtime, item.name))


def _latest_evidence_path(project_root: Path, broker_name: str) -> str | None:
    candidates = _candidate_evidence_files(project_root, broker_name)
    if not candidates:
        return None
    return str(candidates[-1])


def _code_path_state(broker_name: str) -> str:
    capabilities = get_broker_capabilities(broker_name)
    notes = getattr(capabilities, "notes", {}) or {}
    submit_mode = str(notes.get("submit_mode") or "").lower()
    supports_broker_submit = (
        capabilities.supports_live_submit or submit_mode == "paper"
    )
    required = (
        supports_broker_submit,
        capabilities.supports_cancel,
        capabilities.supports_order_query,
        capabilities.supports_reconcile,
    )
    return "present" if all(required) else "partial"


def build_broker_evidence_maturity_report(
    *, project_root: Path | None = None
) -> list[BrokerEvidenceMaturity]:
    """Return evidence maturity records for supported execution backends."""

    root = project_root or PROJECT_ROOT
    longport_real_evidence = _latest_evidence_path(root, "longport")
    longport_paper_evidence = _latest_evidence_path(root, "longport-paper")
    alpaca_evidence = (
        _latest_evidence_path(root, "alpaca-paper")
        or _latest_evidence_path(root, "alpaca")
    )
    ibkr_evidence = _latest_evidence_path(root, "ibkr-paper")

    return [
        BrokerEvidenceMaturity(
            broker_name="longport",
            broker_mode="real",
            code_path_state=_code_path_state("longport"),
            evidence_state="supervised-incomplete",
            latest_evidence_path=longport_real_evidence,
            missing_evidence=[
                "minimal supervised live submit/query/cancel/reconcile evidence"
            ],
            recommended_next_smoke=(
                "Run a supervised LongPort real minimal `rebalance --execute` smoke "
                "with audit log, evidence JSON, and operator note."
            ),
            notes=[
                "Read-only config/preflight/account/quote evidence is weaker "
                "than broker-order evidence.",
                "Live execution remains operator-supervised.",
            ],
        ),
        BrokerEvidenceMaturity(
            broker_name="longport-paper",
            broker_mode="paper",
            code_path_state=_code_path_state("longport-paper"),
            evidence_state="complete" if longport_paper_evidence else "missing",
            latest_evidence_path=longport_paper_evidence,
            missing_evidence=(
                [] if longport_paper_evidence else ["paper smoke evidence JSON"]
            ),
            recommended_next_smoke=None
            if longport_paper_evidence
            else (
                "Run `smoke_operator_harness.py --broker longport-paper "
                "--execute --evidence-output ...`."
            ),
            notes=[
                "Paper backend is the strongest LongPort broker-order "
                "evidence path."
            ],
        ),
        BrokerEvidenceMaturity(
            broker_name="alpaca-paper",
            broker_mode="paper",
            code_path_state=_code_path_state("alpaca-paper"),
            evidence_state="baseline" if alpaca_evidence else "missing",
            latest_evidence_path=alpaca_evidence,
            missing_evidence=(
                []
                if alpaca_evidence
                else ["repeatable Alpaca paper smoke evidence JSON"]
            ),
            recommended_next_smoke=None
            if alpaca_evidence
            else (
                "Run `smoke_operator_harness.py --broker alpaca-paper "
                "--execute --evidence-output ...`."
            ),
            notes=["Use as a stable low-cost regression and smoke baseline."],
        ),
        BrokerEvidenceMaturity(
            broker_name="ibkr-paper",
            broker_mode="paper",
            code_path_state=_code_path_state("ibkr-paper"),
            evidence_state="incomplete",
            latest_evidence_path=ibkr_evidence,
            missing_evidence=[
                "effective-market-data broker submit/query/cancel or fill evidence"
            ],
            recommended_next_smoke=(
                "Run an IBKR paper smoke with valid market data that captures "
                "submit/query/cancel or fill evidence."
            ),
            notes=[
                "Gateway/account/reconcile evidence proves runtime reachability "
                "but not full broker-order maturity."
            ],
        ),
    ]


def render_broker_evidence_maturity(records: list[BrokerEvidenceMaturity]) -> str:
    """Render broker evidence maturity for operators."""

    lines = [
        "Broker evidence maturity:",
        "Broker          | Mode  | Code Path | Evidence             | Latest Evidence",
        "-" * 92,
    ]
    for record in records:
        lines.append(
            f"{record.broker_name[:15]:15s} | "
            f"{record.broker_mode[:5]:5s} | "
            f"{record.code_path_state[:9]:9s} | "
            f"{record.evidence_state[:20]:20s} | "
            f"{record.latest_evidence_path or '-'}"
        )
        if record.missing_evidence:
            lines.append("  missing: " + "; ".join(record.missing_evidence))
        if record.recommended_next_smoke:
            lines.append("  next: " + record.recommended_next_smoke)
        for note in record.notes:
            lines.append("  note: " + note)
    return "\n".join(lines)
