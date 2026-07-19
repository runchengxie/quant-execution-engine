from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTRY_DOCS = (
    ROOT / "README.md",
    ROOT / "AGENTS.md",
    *sorted((ROOT / "docs").glob("*.md")),
)
STYLE_PATTERNS = (
    re.compile(r"不是.{0,40}而是"),
    re.compile(r"并非.{0,40}而是"),
    re.compile(r"\*\*"),
    re.compile("；"),
    re.compile("——"),
    re.compile("[“”]"),
)


def test_entry_docs_use_concise_chinese_style() -> None:
    offenders: list[str] = []

    for path in ENTRY_DOCS:
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            for pattern in STYLE_PATTERNS:
                if pattern.search(line):
                    offenders.append(f"{path.relative_to(ROOT)}:{line_number}:{pattern.pattern}")

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
        "maintainability",
        "quality",
    ):
        assert f"`make {target}`" in docs
        assert f"{target}:" in makefile


def test_makefile_static_checks_cover_repository_python_roots() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert "PYTHON_PATHS := src tests scripts project_tools" in makefile
    assert "ruff check $(PYTHON_PATHS)" in makefile
    assert "ruff format --check $(PYTHON_PATHS)" in makefile
    assert "quality: lint format typecheck maintainability test" in makefile


def test_readme_local_dry_run_example_is_versioned() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    example = ROOT / "examples" / "targets.local-dry-run.json"

    assert "examples/targets.local-dry-run.json" in readme
    assert example.is_file()


def test_docs_match_current_type_tools_and_automation() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8").lower()
    docs = (ROOT / "docs" / "testing.md").read_text(encoding="utf-8")

    assert "mypy" not in pyproject
    assert "当前工具链不使用 `mypy`" in docs
    assert "当前仓库没有启用 GitHub Actions 测试工作流" in docs
    assert ".github/workflows/tests.yml" not in docs


def test_docs_record_current_framework_boundary() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    architecture = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
    capabilities = (ROOT / "docs" / "current-capabilities.md").read_text(encoding="utf-8")
    docs = "\n".join((readme, agents, architecture, capabilities))

    assert "通用 `BrokerAdapter`" in docs
    assert "当前 `main` 没有 vn.py 适配器、依赖或已注册后端" in docs
    assert "Qlib、LEAN、Backtrader" in docs
    assert "不在本仓库范围内" in docs or "不在执行仓库范围内" in docs

    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8").lower()
    broker_dir = ROOT / "src" / "quant_execution_engine" / "broker"
    for framework in ("qlib", "lean", "backtrader", "vnpy"):
        assert framework not in pyproject
        assert not any(framework in path.name.lower() for path in broker_dir.glob("*.py"))
