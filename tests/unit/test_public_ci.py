from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_public_ci_audits_dependencies_before_unit_tests() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    audit = "uv run pip-audit --progress-spinner off"
    tests = "make test"
    assert "- name: Dependency audit" in workflow
    assert audit in workflow
    assert workflow.index(audit) < workflow.index(tests)
