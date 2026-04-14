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
    env["PYTHONPATH"] = (
        src_path if not existing else f"{src_path}{os.pathsep}{existing}"
    )
    return env


@pytest.mark.e2e
def test_smoke_signal_harness_writes_targets(tmp_path: Path) -> None:
    output_path = tmp_path / "signal.json"
    result = subprocess.run(
        [
            sys.executable,
            "project_tools/smoke_signal_harness.py",
            "--output",
            str(output_path),
        ],
        capture_output=True,
        text=True,
        cwd=Path.cwd(),
        env=_cli_env(),
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["source"] == "smoke-signal-harness"
    assert payload["targets"][0]["symbol"] == "AAPL"


@pytest.mark.e2e
def test_smoke_target_harness_prints_json(tmp_path: Path) -> None:
    output_path = tmp_path / "targets.json"
    result = subprocess.run(
        [
            sys.executable,
            "project_tools/smoke_target_harness.py",
            "--scenario",
            "carry-over",
            "--output",
            str(output_path),
            "--print-json",
        ],
        capture_output=True,
        text=True,
        cwd=Path.cwd(),
        env=_cli_env(),
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["source"] == "smoke-target-harness"
    assert payload["targets"][0]["target_quantity"] == 2000
    assert "carry-over" in result.stdout
