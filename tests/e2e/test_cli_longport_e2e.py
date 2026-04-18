import os
import subprocess
import sys
from pathlib import Path

import pytest

from quant_execution_engine.broker.longport_credentials import probe_longport_credentials


def _cli_env() -> dict[str, str]:
    env = os.environ.copy()
    src_path = str(Path.cwd() / "src")
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        src_path if not existing else f"{src_path}{os.pathsep}{existing}"
    )
    return env


def _has_longport_real_credentials() -> bool:
    creds = probe_longport_credentials("real")
    return bool(creds.app_key and creds.app_secret and creds.access_token)


def _is_runtime_network_issue(message: str) -> bool:
    lowered = str(message or "").lower()
    return any(
        token in lowered
        for token in (
            "network",
            "timeout",
            "connect",
            "dns",
            "region configuration",
            "网络",
        )
    )


@pytest.mark.e2e
def test_cli_quote_help() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "quant_execution_engine.cli", "quote", "--help"],
        capture_output=True,
        text=True,
        cwd=Path.cwd(),
        env=_cli_env(),
    )

    assert result.returncode == 0, result.stderr
    assert "quote" in result.stdout.lower()
    assert "tickers" in result.stdout.lower()


@pytest.mark.e2e
def test_cli_rebalance_help() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "quant_execution_engine.cli", "rebalance", "--help"],
        capture_output=True,
        text=True,
        cwd=Path.cwd(),
        env=_cli_env(),
    )

    assert result.returncode == 0, result.stderr
    assert "rebalance" in result.stdout.lower()
    assert "json" in result.stdout.lower()
    assert "target-gross-exposure" in result.stdout
    assert "--broker" in result.stdout


@pytest.mark.e2e
def test_cli_main_help_is_execution_only() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "quant_execution_engine.cli", "--help"],
        capture_output=True,
        text=True,
        cwd=Path.cwd(),
        env=_cli_env(),
    )

    assert result.returncode == 0, result.stderr
    assert "quote" in result.stdout
    assert "rebalance" in result.stdout
    assert "account" in result.stdout
    assert "config" in result.stdout
    assert "backtest" not in result.stdout.lower()
    assert "ai-pick" not in result.stdout.lower()
    assert "load-data" not in result.stdout.lower()


@pytest.mark.e2e
def test_cli_no_command() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "quant_execution_engine.cli"],
        capture_output=True,
        text=True,
        cwd=Path.cwd(),
        env=_cli_env(),
    )

    assert result.returncode == 0
    assert "usage" in result.stdout.lower()


@pytest.mark.e2e
def test_cli_unknown_command() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "quant_execution_engine.cli", "unknown-command"],
        capture_output=True,
        text=True,
        cwd=Path.cwd(),
        env=_cli_env(),
    )

    assert result.returncode != 0
    assert "unknown-command" in result.stderr


@pytest.mark.e2e
def test_cli_quote_without_credentials() -> None:
    env = _cli_env()
    for var in [
        "LONGPORT_APP_KEY",
        "LONGPORT_APP_SECRET",
        "LONGPORT_ACCESS_TOKEN",
        "LONGPORT_ACCESS_TOKEN_REAL",
    ]:
        env.pop(var, None)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "quant_execution_engine.cli",
            "quote",
            "AAPL",
            "--broker",
            "longport",
        ],
        capture_output=True,
        text=True,
        cwd=Path.cwd(),
        env=env,
    )

    assert result.returncode != 0
    assert result.stderr.strip()


@pytest.mark.e2e
def test_cli_rebalance_file_not_found() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "quant_execution_engine.cli", "rebalance", "missing.json"],
        capture_output=True,
        text=True,
        cwd=Path.cwd(),
        env=_cli_env(),
    )

    assert result.returncode != 0
    assert "not found" in result.stderr.lower()


@pytest.mark.e2e
def test_cli_rebalance_rejects_legacy_workbook(tmp_path: Path) -> None:
    legacy_file = tmp_path / "legacy.xlsx"
    legacy_file.write_text("legacy workbook placeholder", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "quant_execution_engine.cli", "rebalance", str(legacy_file)],
        capture_output=True,
        text=True,
        cwd=Path.cwd(),
        env=_cli_env(),
    )

    assert result.returncode != 0
    assert "deprecated" in result.stderr.lower()
    assert "canonical targets json" in result.stderr.lower()


@pytest.mark.e2e
@pytest.mark.skipif(
    not _has_longport_real_credentials(),
    reason="Skipping live API test because LongPort API credentials are not configured.",
)
def test_cli_quote_with_credentials() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "quant_execution_engine.cli",
            "quote",
            "AAPL",
            "--broker",
            "longport",
        ],
        capture_output=True,
        text=True,
        cwd=Path.cwd(),
        env=_cli_env(),
        timeout=30,
    )

    if result.returncode == 0:
        assert "AAPL" in result.stdout
    else:
        error_msg = result.stderr.lower()
        if _is_runtime_network_issue(error_msg) or any(
            err in error_msg for err in ["rate limit", "quota", "market closed"]
        ):
            pytest.skip(f"Live quote skipped due to runtime constraint: {result.stderr}")
        pytest.fail(f"quote command failed unexpectedly: {result.stderr}")


@pytest.mark.e2e
def test_cli_module_can_be_imported() -> None:
    result = subprocess.run(
        [sys.executable, "-c", "import quant_execution_engine.cli; print('Import successful')"],
        capture_output=True,
        text=True,
        cwd=Path.cwd(),
        env=_cli_env(),
    )

    assert result.returncode == 0, result.stderr
    assert "Import successful" in result.stdout


@pytest.mark.e2e
def test_cli_app_entry_point_function() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from quant_execution_engine.cli import app; import sys; sys.argv=['test', '--help']; app()",
        ],
        capture_output=True,
        text=True,
        cwd=Path.cwd(),
        env=_cli_env(),
    )

    assert "usage" in result.stdout.lower()


@pytest.mark.e2e
def test_cli_with_python_warnings() -> None:
    env = _cli_env()
    env["PYTHONWARNINGS"] = "default"

    result = subprocess.run(
        [sys.executable, "-m", "quant_execution_engine.cli", "--help"],
        capture_output=True,
        text=True,
        cwd=Path.cwd(),
        env=env,
    )

    assert result.returncode == 0
    assert "usage" in result.stdout.lower()
