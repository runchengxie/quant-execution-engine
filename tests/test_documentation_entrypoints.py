from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTRY_DOCS = (
    ROOT / "README.md",
    ROOT / "AGENTS.md",
    ROOT / "docs" / "README.md",
    ROOT / "docs" / "testing.md",
)
FORBIDDEN_FRAGMENTS = ("不是", "而是", "**", "；", "——", "“", "”")


def test_entry_docs_use_concise_chinese_style() -> None:
    offenders: list[str] = []

    for path in ENTRY_DOCS:
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            for fragment in FORBIDDEN_FRAGMENTS:
                if fragment in line:
                    offenders.append(f"{path.relative_to(ROOT)}:{line_number}:{fragment}")

    assert offenders == []


def test_testing_docs_match_makefile_targets() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    docs = (ROOT / "docs" / "testing.md").read_text(encoding="utf-8")

    for target in (
        "test",
        "test-all",
        "test-integration",
        "test-e2e",
        "lint",
        "format",
        "typecheck",
        "basedpyright",
        "quality",
    ):
        assert f"`make {target}`" in docs
        assert f"{target}:" in makefile


def test_docs_match_current_type_tools_and_automation() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8").lower()
    docs = (ROOT / "docs" / "testing.md").read_text(encoding="utf-8")

    assert "mypy" not in pyproject
    assert "当前工具链不使用 `mypy`" in docs
    assert "当前仓库没有启用 GitHub Actions 测试 workflow" in docs
    assert ".github/workflows/tests.yml" not in docs
