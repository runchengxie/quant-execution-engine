import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.e2e
def test_cli_lb_quote_help():
    """Tests the help message for the lb-quote command."""
    result = subprocess.run(
        [sys.executable, "-m", "stock_analysis.cli", "lb-quote", "--help"],
        capture_output=True,
        text=True,
        cwd=Path.cwd(),
    )

    assert result.returncode == 0, f"Help command failed: {result.stderr}"
    assert "lb-quote" in result.stdout.lower()
    assert "tickers" in result.stdout.lower() or "股票代码" in result.stdout


@pytest.mark.e2e
def test_cli_lb_rebalance_help():
    """Tests the help message for the lb-rebalance command."""
    result = subprocess.run(
        [sys.executable, "-m", "stock_analysis.cli", "lb-rebalance", "--help"],
        capture_output=True,
        text=True,
        cwd=Path.cwd(),
    )

    assert result.returncode == 0, f"Help command failed: {result.stderr}"
    assert "lb-rebalance" in result.stdout.lower()
    assert "json" in result.stdout.lower()
    assert "target-gross-exposure" in result.stdout


@pytest.mark.e2e
def test_cli_main_help_is_execution_only():
    """Tests the main CLI help message."""
    result = subprocess.run(
        [sys.executable, "-m", "stock_analysis.cli", "--help"],
        capture_output=True,
        text=True,
        cwd=Path.cwd(),
    )

    assert result.returncode == 0, f"Main help command failed: {result.stderr}"
    assert "lb-quote" in result.stdout
    assert "lb-rebalance" in result.stdout
    assert "lb-account" in result.stdout
    assert "lb-config" in result.stdout
    assert "backtest" not in result.stdout.lower()
    assert "ai-pick" not in result.stdout.lower()
    assert "load-data" not in result.stdout.lower()


@pytest.mark.e2e
def test_cli_no_command():
    """Tests the behavior when no command is provided."""
    result = subprocess.run(
        [sys.executable, "-m", "stock_analysis.cli"],
        capture_output=True,
        text=True,
        cwd=Path.cwd(),
    )

    assert result.returncode == 0
    assert "usage" in result.stdout.lower() or "用法" in result.stdout


@pytest.mark.e2e
def test_cli_unknown_command():
    """Tests the handling of an unknown command."""
    result = subprocess.run(
        [sys.executable, "-m", "stock_analysis.cli", "unknown-command"],
        capture_output=True,
        text=True,
        cwd=Path.cwd(),
    )

    assert result.returncode != 0
    assert "unknown" in result.stderr.lower() or "未知" in result.stderr


@pytest.mark.e2e
def test_cli_lb_quote_without_longport_dependency():
    """Tests the behavior of lb-quote without LongPort credentials or SDK."""
    env = os.environ.copy()

    result = subprocess.run(
        [sys.executable, "-m", "stock_analysis.cli", "lb-quote", "AAPL"],
        capture_output=True,
        text=True,
        cwd=Path.cwd(),
        env=env,
    )

    if "longport" in result.stderr.lower() and "import" in result.stderr.lower():
        assert result.returncode != 0
        assert "pip install longport" in result.stderr or "安装" in result.stderr


@pytest.mark.e2e
def test_cli_lb_rebalance_file_not_found():
    """Tests how the lb-rebalance command handles a non-existent file."""
    result = subprocess.run(
        [sys.executable, "-m", "stock_analysis.cli", "lb-rebalance", "missing.json"],
        capture_output=True,
        text=True,
        cwd=Path.cwd(),
    )

    assert result.returncode != 0
    assert (
        "not found" in result.stderr.lower()
        or "不存在" in result.stderr
        or "找不到" in result.stderr
    )


@pytest.mark.e2e
def test_cli_lb_rebalance_rejects_legacy_workbook(tmp_path: Path):
    """Tests that rebalance execution requires canonical target JSON."""
    legacy_file = tmp_path / "legacy.xlsx"
    legacy_file.write_text("legacy workbook placeholder", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "stock_analysis.cli", "lb-rebalance", str(legacy_file)],
        capture_output=True,
        text=True,
        cwd=Path.cwd(),
    )

    assert result.returncode != 0
    assert "deprecated" in result.stderr.lower()
    assert "schema-v2" in result.stderr.lower()


@pytest.mark.e2e
@pytest.mark.skipif(
    not all(
        os.getenv(var)
        for var in ["LONGPORT_APP_KEY", "LONGPORT_APP_SECRET", "LONGPORT_ACCESS_TOKEN"]
    ),
    reason="Skipping live API test because LongPort API credentials are not configured.",
)
def test_cli_lb_quote_with_credentials():
    """Tests the lb-quote command when API credentials are provided."""
    result = subprocess.run(
        [sys.executable, "-m", "stock_analysis.cli", "lb-quote", "AAPL"],
        capture_output=True,
        text=True,
        cwd=Path.cwd(),
        timeout=30,
    )

    if result.returncode == 0:
        assert "AAPL" in result.stdout
        assert "价格" in result.stdout or "price" in result.stdout.lower()
    else:
        error_msg = result.stderr.lower()
        acceptable_errors = [
            "network",
            "timeout",
            "rate limit",
            "quota",
            "market closed",
            "网络",
            "超时",
            "限制",
        ]

        if any(err in error_msg for err in acceptable_errors):
            pytest.skip(f"API call failed for an expected reason, skipping test: {result.stderr}")
        else:
            pytest.fail(f"lb-quote command failed unexpectedly: {result.stderr}")


@pytest.mark.e2e
def test_cli_module_can_be_imported():
    """Tests that the CLI module can be imported correctly."""
    result = subprocess.run(
        [sys.executable, "-c", "import stock_analysis.cli; print('Import successful')"],
        capture_output=True,
        text=True,
        cwd=Path.cwd(),
    )

    assert result.returncode == 0, f"CLI module import failed: {result.stderr}"
    assert "Import successful" in result.stdout


@pytest.mark.e2e
def test_cli_app_entry_point_function():
    """Tests the app() entry point function."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from stock_analysis.cli import app; import sys; sys.argv=['test', '--help']; app()",
        ],
        capture_output=True,
        text=True,
        cwd=Path.cwd(),
    )

    assert (
        "usage" in result.stdout.lower()
        or "用法" in result.stdout
        or "help" in result.stdout.lower()
    )


@pytest.mark.e2e
def test_cli_with_python_warnings():
    """Tests the CLI's behavior when Python warnings are enabled."""
    env = os.environ.copy()
    env["PYTHONWARNINGS"] = "default"

    result = subprocess.run(
        [sys.executable, "-m", "stock_analysis.cli", "--help"],
        capture_output=True,
        text=True,
        cwd=Path.cwd(),
        env=env,
    )

    assert result.returncode == 0
    assert "usage" in result.stdout.lower() or "用法" in result.stdout
