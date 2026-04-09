from __future__ import annotations

import json
from pathlib import Path

import pytest

from quant_execution_engine.targets import read_targets_json, write_targets_json


pytestmark = pytest.mark.unit


def test_write_targets_json_schema_v2_roundtrip(tmp_path: Path) -> None:
    out_path = tmp_path / "targets.json"

    write_targets_json(
        out_path,
        asof="2025-09-05",
        source="research-core",
        target_gross_exposure=0.9,
        targets=[
            {"symbol": "AAPL", "market": "US", "target_weight": 0.6},
            {"symbol": "700", "market": "HK", "target_weight": 0.3},
        ],
    )

    raw = json.loads(out_path.read_text(encoding="utf-8"))
    assert raw["schema_version"] == 2
    assert raw["target_gross_exposure"] == 0.9
    assert raw["targets"][1]["market"] == "HK"

    parsed = read_targets_json(out_path, require_schema_v2=True)
    assert parsed.schema_version == 2
    assert parsed.target_gross_exposure == pytest.approx(0.9)
    assert [target.key for target in parsed.targets] == ["AAPL.US", "700.HK"]


def test_read_targets_json_rejects_legacy_for_live_execution(tmp_path: Path) -> None:
    legacy_path = tmp_path / "legacy_targets.json"
    legacy_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "source": "research-core",
                "asof": "2025-09-05",
                "tickers": ["AAPL", "MSFT"],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="schema-v2"):
        read_targets_json(legacy_path, require_schema_v2=True)


def test_write_targets_json_legacy_tickers_defaults_to_equal_weights(
    tmp_path: Path,
) -> None:
    out_path = tmp_path / "targets.json"

    write_targets_json(
        out_path,
        asof="2025-09-05",
        tickers=["AAPL", "700.HK"],
    )

    parsed = read_targets_json(out_path, require_schema_v2=True)
    assert parsed.asof == "2025-09-05"
    assert [target.key for target in parsed.targets] == ["AAPL.US", "700.HK"]
    assert parsed.targets[0].target_weight == pytest.approx(0.5)
    assert parsed.targets[1].target_weight == pytest.approx(0.5)
