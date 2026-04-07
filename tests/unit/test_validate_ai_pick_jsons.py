"""Unit tests for project_tools/validate_ai_pick_jsons.py

Covers:
- AI picks are subset of preliminary candidates when prelim exists
- Error when extra tickers outside preliminary
- Warning when preliminary file is missing for the trade date
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TOOLS_PATH = PROJECT_ROOT / "project_tools" / "validate_ai_pick_jsons.py"

pytestmark = pytest.mark.unit


def _import_validator():
    spec = importlib.util.spec_from_file_location(
        "validate_ai_pick_jsons", str(TOOLS_PATH)
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[attr-defined]
    return module


def _write_json(p: Path, obj: Any) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(__import__("json").dumps(obj, ensure_ascii=False, indent=2), "utf-8")


def test_validate_subset_ok(tmp_path: Path, monkeypatch) -> None:
    mod = _import_validator()
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "AI_DIR", tmp_path / "ai_pick")
    monkeypatch.setattr(mod, "PRELIM_DIR", tmp_path / "preliminary")

    trade_date = "2099-01-02"
    year = trade_date[:4]

    # Prepare preliminary candidates
    prelim_rows = [{"ticker": "AAPL"}, {"ticker": "MSFT"}, {"ticker": "GOOGL"}]
    prelim_path = mod.PRELIM_DIR / year / f"{trade_date}.json"
    _write_json(prelim_path, {"rows": prelim_rows})

    # Prepare AI picks that are a subset of prelim
    ai_picks = [
        {"rank": 1, "ticker": "AAPL", "confidence": 8},
        {"rank": 2, "ticker": "MSFT", "confidence": 7.5},
    ]
    ai_obj = {
        "schema_version": 1,
        "source": "ai_pick",
        "trade_date": trade_date,
        "data_cutoff_date": trade_date,
        "universe": "US",
        "model": "gpt-4o-mini",
        "prompt_version": "v1",
        "params": {"top_n": len(ai_picks)},
        "picks": ai_picks,
    }
    ai_path = mod.AI_DIR / year / f"{trade_date}.json"
    _write_json(ai_path, ai_obj)

    issues = mod.validate_ai_file(ai_path)
    assert issues == [], f"Unexpected issues: {issues}"


def test_validate_extra_ticker_error(tmp_path: Path, monkeypatch) -> None:
    mod = _import_validator()
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "AI_DIR", tmp_path / "ai_pick")
    monkeypatch.setattr(mod, "PRELIM_DIR", tmp_path / "preliminary")

    trade_date = "2099-01-03"
    year = trade_date[:4]

    # Preliminary only includes AAPL
    prelim_path = mod.PRELIM_DIR / year / f"{trade_date}.json"
    _write_json(prelim_path, {"rows": [{"ticker": "AAPL"}]})

    # AI picks include AAPL and an extra outside prelim
    ai_picks = [
        {"rank": 1, "ticker": "AAPL", "confidence": 9},
        {"rank": 2, "ticker": "TSLA", "confidence": 8},
    ]
    ai_obj = {
        "schema_version": 1,
        "source": "ai_pick",
        "trade_date": trade_date,
        "data_cutoff_date": trade_date,
        "universe": "US",
        "model": "gpt-4o-mini",
        "prompt_version": "v1",
        "params": {"top_n": len(ai_picks)},
        "picks": ai_picks,
    }
    ai_path = mod.AI_DIR / year / f"{trade_date}.json"
    _write_json(ai_path, ai_obj)

    issues = mod.validate_ai_file(ai_path)
    # Should complain TSLA not in preliminary
    assert any("not in preliminary candidates" in s for s in issues), issues


def test_validate_prelim_missing_warning(tmp_path: Path, monkeypatch) -> None:
    mod = _import_validator()
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "AI_DIR", tmp_path / "ai_pick")
    monkeypatch.setattr(mod, "PRELIM_DIR", tmp_path / "preliminary")

    trade_date = "2099-01-04"
    year = trade_date[:4]

    # Only AI file, no preliminary file
    ai_picks = [
        {"rank": 1, "ticker": "AAPL", "confidence": 7},
    ]
    ai_obj = {
        "schema_version": 1,
        "source": "ai_pick",
        "trade_date": trade_date,
        "data_cutoff_date": trade_date,
        "universe": "US",
        "model": "gpt-4o-mini",
        "prompt_version": "v1",
        "params": {"top_n": len(ai_picks)},
        "picks": ai_picks,
    }
    ai_path = mod.AI_DIR / year / f"{trade_date}.json"
    _write_json(ai_path, ai_obj)

    issues = mod.validate_ai_file(ai_path)
    assert any("preliminary candidates not found" in s for s in issues), issues


def test_filename_trade_date_mismatch(tmp_path: Path, monkeypatch) -> None:
    mod = _import_validator()
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "AI_DIR", tmp_path / "ai_pick")
    monkeypatch.setattr(mod, "PRELIM_DIR", tmp_path / "preliminary")

    file_date = "2099-01-05"
    trade_date = "2099-01-06"  # intentionally different from file name
    year = file_date[:4]

    # Minimal valid picks
    ai_picks = [
        {"rank": 1, "ticker": "AAPL", "confidence": 7},
    ]
    ai_obj = {
        "schema_version": 1,
        "source": "ai_pick",
        "trade_date": trade_date,
        "data_cutoff_date": trade_date,
        "universe": "US",
        "model": "gpt-4o-mini",
        "prompt_version": "v1",
        "params": {"top_n": len(ai_picks)},
        "picks": ai_picks,
    }
    ai_path = mod.AI_DIR / year / f"{file_date}.json"
    _write_json(ai_path, ai_obj)

    issues = mod.validate_ai_file(ai_path)
    assert any("file name/date mismatch" in s for s in issues), issues
