from __future__ import annotations

import hashlib
import importlib
import json
import socket
import sys
from pathlib import Path

import pytest

from quant_execution_engine import cli
from quant_execution_engine.recovery_matrix import (
    RECOVERY_MATRIX_SCHEMA,
    RECOVERY_SCENARIO_IDS,
    RecoveryMatrixInvariantError,
    RecoveryMatrixMode,
    RecoveryMatrixValidationError,
    execution_recovery_matrix_bytes,
    load_execution_recovery_matrix_bytes,
    run_execution_recovery_matrix,
    validate_execution_recovery_matrix_payload,
    write_execution_recovery_matrix,
)

pytestmark = pytest.mark.unit


def _scenarios(matrix_bytes: bytes) -> dict[str, dict[str, object]]:
    payload = json.loads(matrix_bytes)
    return {item["id"]: item for item in payload["scenarios"]}


def test_complete_fault_matrix_is_byte_stable_and_strict(tmp_path: Path) -> None:
    assert RECOVERY_SCENARIO_IDS == (
        "accepted_but_timeout",
        "duplicate_submission",
        "duplicate_callback",
        "out_of_order_callback",
        "partial_fill_restart",
        "cancel_fill_race",
        "reconnect_replay",
        "position_drift",
    )
    first = run_execution_recovery_matrix(
        mode=RecoveryMatrixMode.SHADOW,
        workspace=tmp_path / "first-workspace",
    )
    second = run_execution_recovery_matrix(
        mode=RecoveryMatrixMode.SHADOW,
        workspace=tmp_path / "second-workspace",
    )
    first_bytes = execution_recovery_matrix_bytes(first)
    second_bytes = execution_recovery_matrix_bytes(second)

    assert first_bytes == second_bytes
    assert first_bytes.endswith(b"\n")
    assert hashlib.sha256(first_bytes).hexdigest() == (
        "55393cc227c79fc9b3f702a80e09d78e1e507fe27ea1e748498ddbbf5100a54f"
    )
    assert all(prefix not in first_bytes for prefix in (b"vnpy.", b"qlib.", b"QuantConnect."))
    assert load_execution_recovery_matrix_bytes(first_bytes) == first
    payload = json.loads(first_bytes)
    assert set(payload) == {
        "schema",
        "mode",
        "deterministic",
        "live_broker_access",
        "scenarios",
    }
    assert payload["schema"] == RECOVERY_MATRIX_SCHEMA
    assert payload["mode"] == "shadow"
    assert payload["deterministic"] is True
    assert payload["live_broker_access"] is False
    assert tuple(item["id"] for item in payload["scenarios"]) == RECOVERY_SCENARIO_IDS
    assert all(item["status"] == "passed" for item in payload["scenarios"])


def test_scenarios_publish_expected_state_and_reconciliation_results() -> None:
    rendered = execution_recovery_matrix_bytes(run_execution_recovery_matrix())
    scenarios = _scenarios(rendered)

    for scenario in scenarios.values():
        expected = scenario["expected_state"]
        assert expected["transport_submit_calls"] == 1
        assert expected["submission_attempt_count"] == 1
        assert expected["idempotent_retry_blocked"] is True
        assert expected["state_monotonic"] is True

    timeout = scenarios["accepted_but_timeout"]
    assert timeout["expected_state"]["submission_state"] == "ACCEPTED"
    assert timeout["reconciliation"]["result"] == "broker_order_found_after_timeout"
    assert timeout["reconciliation"]["evidence_count"] == 1

    duplicate = scenarios["duplicate_callback"]
    assert duplicate["expected_state"]["order_event_count"] == 2
    assert duplicate["expected_state"]["fill_count"] == 1
    assert duplicate["reconciliation"]["result"] == "duplicate_facts_deduplicated"

    out_of_order = scenarios["out_of_order_callback"]
    assert out_of_order["expected_state"]["submission_state"] == "FILLED"
    assert out_of_order["expected_state"]["filled_quantity"] == "10"

    restart = scenarios["partial_fill_restart"]
    assert restart["expected_state"]["submission_state"] == "PARTIALLY_FILLED"
    assert restart["reconciliation"]["status"] == "manual_intervention_required"

    race = scenarios["cancel_fill_race"]
    assert race["expected_state"]["submission_state"] == "FILLED"
    assert race["reconciliation"]["result"] == "late_fill_wins_over_cancel_ack"

    replay = scenarios["reconnect_replay"]
    assert replay["reconciliation"]["result"] == "reconnect_replay_is_idempotent"

    drift = scenarios["position_drift"]
    assert drift["reconciliation"]["position_drift"] == "-3"
    assert drift["reconciliation"]["kill_switch"] is True
    assert drift["reconciliation"]["status"] == "manual_intervention_required"


def test_strict_validator_rejects_unknown_fields_and_noncanonical_decimals() -> None:
    payload = json.loads(execution_recovery_matrix_bytes(run_execution_recovery_matrix()))
    payload["generated_at"] = "2026-07-13T12:00:00Z"
    with pytest.raises(RecoveryMatrixValidationError, match="extra=generated_at"):
        validate_execution_recovery_matrix_payload(payload)

    payload.pop("generated_at")
    payload["scenarios"][0]["expected_state"]["filled_quantity"] = "0.0"
    with pytest.raises(RecoveryMatrixValidationError, match="canonical Decimal"):
        validate_execution_recovery_matrix_payload(payload)


def test_writer_is_atomic_byte_stable_and_supports_paper_mode(tmp_path: Path) -> None:
    output = tmp_path / "evidence" / "execution_recovery_matrix.v1.json"
    first = write_execution_recovery_matrix(output, mode=RecoveryMatrixMode.PAPER)
    first_bytes = output.read_bytes()
    second = write_execution_recovery_matrix(output, mode=RecoveryMatrixMode.PAPER)

    assert output.read_bytes() == first_bytes
    assert execution_recovery_matrix_bytes(first) == execution_recovery_matrix_bytes(second)
    assert load_execution_recovery_matrix_bytes(first_bytes).mode is RecoveryMatrixMode.PAPER
    assert not output.with_name(f".{output.name}.tmp").exists()


def test_retained_workspace_fails_closed_instead_of_mixing_runs(tmp_path: Path) -> None:
    workspace = tmp_path / "journals"
    run_execution_recovery_matrix(workspace=workspace)
    assert len(tuple(workspace.glob("*.sqlite3"))) == len(RECOVERY_SCENARIO_IDS)

    with pytest.raises(RecoveryMatrixInvariantError, match="already exists"):
        run_execution_recovery_matrix(workspace=workspace)


def test_cli_path_is_offline_and_does_not_load_vnpy_or_a_broker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "cli-matrix.json"

    def forbidden_import(name: str, package: str | None = None) -> object:
        raise AssertionError(f"optional SDK import forbidden: {name} {package}")

    def forbidden_broker(*args: object, **kwargs: object) -> object:
        raise AssertionError(f"broker construction forbidden: {args!r} {kwargs!r}")

    def forbidden_socket(*args: object, **kwargs: object) -> socket.socket:
        raise AssertionError(f"network access forbidden: {args!r} {kwargs!r}")

    bindings = importlib.import_module("quant_execution_engine._vnpy_bindings")
    monkeypatch.setattr(bindings, "import_module", forbidden_import)
    monkeypatch.setattr(cli, "get_broker_adapter", forbidden_broker)
    monkeypatch.setattr(socket, "socket", forbidden_socket)

    result = cli.run_recovery_matrix(mode="shadow", output_path=str(output))

    assert result.exit_code == 0
    assert result.stderr is None
    assert result.stdout is not None and "live_broker_access=false" in result.stdout
    matrix = load_execution_recovery_matrix_bytes(output.read_bytes())
    assert matrix.mode is RecoveryMatrixMode.SHADOW
    assert matrix.live_broker_access is False


def test_main_routes_recovery_matrix_without_broker_configuration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "main-matrix.json"
    monkeypatch.setattr(
        sys,
        "argv",
        ["qexec", "recovery-matrix", "--mode", "paper", "--output", str(output)],
    )
    monkeypatch.setattr(
        cli,
        "get_broker_adapter",
        lambda *args, **kwargs: pytest.fail(f"broker called: {args!r} {kwargs!r}"),
    )

    assert cli.main() == 0
    assert "Recovery matrix passed: 8 scenarios" in capsys.readouterr().out
    assert (
        load_execution_recovery_matrix_bytes(output.read_bytes()).mode is RecoveryMatrixMode.PAPER
    )
