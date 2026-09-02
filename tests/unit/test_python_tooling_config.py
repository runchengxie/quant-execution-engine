from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_ruff_target_matches_minimum_supported_python() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    requires_python = re.search(r'requires-python\s*=\s*"([^"]+)"', pyproject)
    ruff_target = re.search(
        r'\[tool\.ruff\][\s\S]*?target-version\s*=\s*"([^"]+)"',
        pyproject,
    )

    assert requires_python is not None
    assert requires_python.group(1).startswith(">=3.11")
    assert ruff_target is not None
    assert ruff_target.group(1) == "py311"
