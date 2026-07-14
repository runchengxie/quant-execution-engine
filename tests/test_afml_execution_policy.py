from __future__ import annotations

import json
from pathlib import Path

import pytest

from quant_execution_engine.execution_policy import (
    DynamicLimitConfig,
    average_limit_price,
    build_dynamic_execution_decision,
    calibrate_sigmoid_width,
    inverse_price_for_size,
    sigmoid_bet_size,
)
from quant_execution_engine.handoff_audit import audit_research_handoff, sha256_file


def test_sigmoid_size_and_inverse_price_round_trip() -> None:
    omega = calibrate_sigmoid_width(price_divergence=10.0, target_size=0.95)
    size = sigmoid_bet_size(forecast_price=110.0, market_price=100.0, omega=omega)
    price = inverse_price_for_size(forecast_price=110.0, target_size=size, omega=omega)

    assert size == pytest.approx(0.95)
    assert price == pytest.approx(100.0)


def test_average_limit_price_is_between_market_and_forecast_for_buy() -> None:
    omega = calibrate_sigmoid_width(price_divergence=10.0, target_size=0.95)
    target_size = sigmoid_bet_size(forecast_price=115.0, market_price=100.0, omega=omega)
    limit = average_limit_price(
        forecast_price=115.0,
        current_size=0.0,
        target_size=target_size,
        omega=omega,
    )

    assert limit is not None
    assert 100.0 < limit < 115.0


def test_dynamic_decision_applies_lots_and_participation_cap() -> None:
    omega = calibrate_sigmoid_width(price_divergence=10.0, target_size=0.95)
    decision = build_dynamic_execution_decision(
        current_price=100.0,
        forecast_price=110.0,
        current_quantity=0,
        omega=omega,
        config=DynamicLimitConfig(
            max_position=1000,
            lot_size=100,
            max_participation_rate=0.05,
        ),
        recent_market_volume=4000,
    )

    assert decision.target_quantity == 1000
    assert decision.order_quantity == 1000
    assert decision.participation_capped_quantity == 200
    assert decision.limit_price is not None


def test_handoff_audit_checks_schema_and_optional_hashes(tmp_path: Path) -> None:
    targets_path = tmp_path / "targets.json"
    targets_path.write_text(
        json.dumps(
            {
                "asof": "2026-07-14",
                "source": "strategy-pipeline",
                "targets": [{"symbol": "600000.SH", "market": "CN", "target_weight": 0.1}],
            }
        )
    )
    protocol_path = tmp_path / "research_protocol_report.json"
    protocol_path.write_text(json.dumps({"level": "release", "status": "pass"}))
    lineage_path = tmp_path / "targets.json.lineage.json"
    lineage_path.write_text(
        json.dumps(
            {
                "targets_file": str(targets_path),
                "targets_sha256": sha256_file(targets_path),
                "research_protocol": {
                    "status": "pass",
                    "path": protocol_path.name,
                    "sha256": sha256_file(protocol_path),
                },
            }
        )
    )

    report = audit_research_handoff(
        targets_path,
        lineage_path=lineage_path,
        require_release_protocol=True,
    )

    assert report.status == "pass"
    assert any(
        check.name == "release_protocol_hash" and check.status == "pass" for check in report.checks
    )
