import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


def _cli_env() -> dict[str, str]:
    env = os.environ.copy()
    src_path = str(Path.cwd() / "src")
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = src_path if not existing else f"{src_path}{os.pathsep}{existing}"
    return env


@pytest.mark.e2e
def test_offline_chain_local_dry_run_writes_isolated_artifacts(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    result = subprocess.run(
        [
            sys.executable,
            "project_tools/evidence_offline_chain.py",
            "--broker",
            "local-dry-run",
            "--run-dir",
            str(run_dir),
        ],
        capture_output=True,
        text=True,
        cwd=Path.cwd(),
        env=_cli_env(),
    )

    assert result.returncode == 0, result.stderr
    evidence_path = run_dir / "evidence" / "local-dry-run-offline-chain.json"
    assert evidence_path.is_file()
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert payload["broker"] == "local-dry-run"
    assert payload["success"] is True
    assert [step["name"] for step in payload["steps"]] == [
        "config",
        "preflight",
        "quote",
        "account",
        "rebalance-dry-run",
    ]
    assert (run_dir / "orders").glob("*.jsonl")
    assert (run_dir / "state").glob("*.json")


@pytest.mark.e2e
def test_offline_chain_mock_sim_execute_with_restart_check(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    result = subprocess.run(
        [
            sys.executable,
            "project_tools/evidence_offline_chain.py",
            "--broker",
            "mock-sim",
            "--execute",
            "--restart-check",
            "--target-quantity",
            "7",
            "--run-dir",
            str(run_dir),
        ],
        capture_output=True,
        text=True,
        cwd=Path.cwd(),
        env=_cli_env(),
    )

    assert result.returncode == 0, result.stderr
    evidence_path = run_dir / "evidence" / "mock-sim-offline-chain.json"
    assert evidence_path.is_file()
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert payload["broker"] == "mock-sim"
    assert payload["success"] is True
    assert payload["execute"] is True
    assert [step["name"] for step in payload["steps"]] == [
        "config",
        "preflight",
        "quote",
        "account",
        "rebalance-execute",
        "orders",
    ]
    restart = payload["restart_check"]
    assert restart is not None
    assert restart["state_loaded"] is True
    assert restart["broker_orders"] == 1
    assert restart["positions"] == {"AAPL.US": 7}
