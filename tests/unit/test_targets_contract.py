from __future__ import annotations

import json
from pathlib import Path

import pytest

from quant_execution_engine.targets import (
    normalize_execution_symbol,
    prune_target_weights,
    read_targets_json,
    resolve_target_output_path,
    write_targets_json,
)

pytestmark = pytest.mark.unit


def test_normalize_execution_symbol_maps_exchange_symbols() -> None:
    assert normalize_execution_symbol("600519.SH", "CN") == ("600519.SH", "CN")
    assert normalize_execution_symbol("858.SZ", "CN") == ("000858.SZ", "CN")
    assert normalize_execution_symbol("700.HK", None) == ("700", "HK")
    assert normalize_execution_symbol("AAPL", "US") == ("AAPL", "US")


def test_resolve_target_output_path_uses_current_directory(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    assert resolve_target_output_path("artifacts/targets.json") == (
        tmp_path / "artifacts" / "targets.json"
    ).resolve()


def test_prune_target_weights_keeps_cumulative_boundary_and_order() -> None:
    result = prune_target_weights(
        [0.1, 0.5, 0.3, 0.1],
        cumulative_target_weight=0.6,
    )

    assert result.retained_indices == (1, 2)
    assert result.output_weights == (0.5, 0.3)
    assert result.metadata["dropped_count"] == 2


def test_prune_target_weights_can_apply_minimum_and_renormalize() -> None:
    result = prune_target_weights(
        [0.1, 0.2, 0.7],
        min_target_weight=0.2,
        renormalize_target_weights=True,
    )

    assert result.retained_indices == (1, 2)
    assert result.output_weights == pytest.approx((0.2222222222, 0.7777777778))
    assert result.metadata["output_weight_sum"] == pytest.approx(1.0)


def test_normalize_execution_symbol_rejects_market_conflicts() -> None:
    with pytest.raises(ValueError, match="conflicts with market"):
        normalize_execution_symbol("600519.SH", "HK")


def test_write_targets_json_canonical_roundtrip(tmp_path: Path) -> None:
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
    assert "schema_version" not in raw
    assert raw["target_gross_exposure"] == 0.9
    assert raw["targets"][1]["market"] == "HK"

    parsed = read_targets_json(out_path, require_canonical=True)
    assert parsed.target_gross_exposure == pytest.approx(0.9)
    assert [target.key for target in parsed.targets] == ["AAPL.US", "700.HK"]


def test_read_targets_json_accepts_canonical_without_schema_version(
    tmp_path: Path,
) -> None:
    target_path = tmp_path / "targets.json"
    target_path.write_text(
        json.dumps(
            {
                "source": "manual",
                "asof": "2025-09-05",
                "targets": [
                    {"symbol": "AAPL", "market": "US", "target_weight": 1.0},
                ],
            }
        ),
        encoding="utf-8",
    )

    parsed = read_targets_json(target_path, require_canonical=True)

    assert parsed.source == "manual"
    assert [target.key for target in parsed.targets] == ["AAPL.US"]


def test_read_targets_json_rejects_ticker_list_for_live_execution(
    tmp_path: Path,
) -> None:
    legacy_path = tmp_path / "legacy_targets.json"
    legacy_path.write_text(
        json.dumps(
            {
                "source": "research-core",
                "asof": "2025-09-05",
                "tickers": ["AAPL", "MSFT"],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="targets JSON with a 'targets' array"):
        read_targets_json(legacy_path, require_canonical=True)


def test_read_targets_json_rejects_ticker_list_by_default(tmp_path: Path) -> None:
    target_path = tmp_path / "legacy_targets.json"
    target_path.write_text(
        json.dumps({"tickers": ["AAPL"]}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="targets JSON with a 'targets' array"):
        read_targets_json(target_path)


def test_write_targets_json_ticker_helper_defaults_to_equal_weights(
    tmp_path: Path,
) -> None:
    out_path = tmp_path / "targets.json"

    write_targets_json(
        out_path,
        asof="2025-09-05",
        tickers=["AAPL", "700.HK"],
    )

    parsed = read_targets_json(out_path, require_canonical=True)
    assert parsed.asof == "2025-09-05"
    assert [target.key for target in parsed.targets] == ["AAPL.US", "700.HK"]
    assert parsed.targets[0].target_weight == pytest.approx(0.5)
    assert parsed.targets[1].target_weight == pytest.approx(0.5)


def test_read_targets_json_accepts_a_share_suffixes_and_market_alias(
    tmp_path: Path,
) -> None:
    target_path = tmp_path / "cn_targets.json"
    target_path.write_text(
        json.dumps(
            {
                "source": "strategy-pipeline",
                "asof": "2026-05-29",
                "targets": [
                    {"symbol": "600519.SH", "target_weight": 0.35},
                    {"symbol": "858.SZ", "target_weight": 0.25},
                    {"symbol": "430047.BJ", "target_weight": 0.2},
                    {"symbol": "600000.XSHG", "target_weight": 0.1},
                    {"symbol": "1.XSHE", "target_weight": 0.1},
                ],
            }
        ),
        encoding="utf-8",
    )

    parsed = read_targets_json(target_path, default_market="a_share")

    assert [target.key for target in parsed.targets] == [
        "600519.SH.CN",
        "000858.SZ.CN",
        "430047.BJ.CN",
        "600000.SH.CN",
        "000001.SZ.CN",
    ]
    assert all(target.market == "CN" for target in parsed.targets)


def test_write_targets_json_preserves_cn_exchange_suffix(tmp_path: Path) -> None:
    out_path = tmp_path / "targets.json"

    write_targets_json(
        out_path,
        targets=[
            {"symbol": "600519.SH", "market": "CN", "target_weight": 0.6},
            {"symbol": "000858.SZ", "market": "a_share", "target_weight": 0.4},
        ],
    )

    raw = json.loads(out_path.read_text(encoding="utf-8"))
    assert raw["targets"] == [
        {"symbol": "600519.SH", "market": "CN", "target_weight": 0.6},
        {"symbol": "000858.SZ", "market": "CN", "target_weight": 0.4},
    ]
