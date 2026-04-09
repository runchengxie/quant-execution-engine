from pathlib import Path

import pytest


def _longport_impl_file() -> Path:
    return Path("src/quant_execution_engine/broker/longport.py")


@pytest.mark.unit
def test_pyproject_metadata_and_scripts() -> None:
    content = Path("pyproject.toml").read_text(encoding="utf-8")

    assert 'name = "quant-execution-engine"' in content
    assert 'longport>=0.2.77' in content
    assert 'qexec = "quant_execution_engine.cli:app"' in content


@pytest.mark.unit
def test_package_structure() -> None:
    broker_dir = Path("src/quant_execution_engine/broker")
    cli_file = Path("src/quant_execution_engine/cli.py")

    assert broker_dir.exists()
    assert (broker_dir / "__init__.py").exists()
    assert (broker_dir / "longport.py").exists()
    assert cli_file.exists()


@pytest.mark.unit
def test_cli_contains_execution_commands() -> None:
    content = Path("src/quant_execution_engine/cli.py").read_text(encoding="utf-8")

    assert 'subparsers.add_parser("quote"' in content
    assert 'subparsers.add_parser("rebalance"' in content
    assert 'subparsers.add_parser("account"' in content
    assert 'subparsers.add_parser("config"' in content
    assert "def run_quote" in content
    assert "def run_rebalance" in content
    assert 'prog="qexec"' in content


@pytest.mark.unit
def test_longport_client_exports() -> None:
    content = _longport_impl_file().read_text(encoding="utf-8")

    assert "def _to_lb_symbol" in content
    assert "def getenv_both" in content
    assert "class LongPortClient" in content
    assert "def quote_last" in content
    assert "def place_order" in content


@pytest.mark.unit
def test_pytest_markers_configured() -> None:
    content = Path("pyproject.toml").read_text(encoding="utf-8")

    assert "markers" in content
    assert "unit" in content
    assert "integration" in content
    assert "e2e" in content


@pytest.mark.unit
def test_longport_imports() -> None:
    content = _longport_impl_file().read_text(encoding="utf-8")

    assert "from longport.openapi import" in content
    assert "from longbridge.openapi import" in content
    assert "except ImportError" in content
    for name in ["Config", "QuoteContext", "TradeContext"]:
        assert name in content


@pytest.mark.unit
def test_environment_compatibility() -> None:
    content = _longport_impl_file().read_text(encoding="utf-8")

    assert "def getenv_both" in content
    assert "LONGPORT_" in content
    assert "LONGBRIDGE_" in content


@pytest.mark.unit
def test_env_example_file() -> None:
    env_example = Path(".env.example")
    if not env_example.exists():
        return

    content = env_example.read_text(encoding="utf-8")
    for var in ["LONGPORT_APP_KEY", "LONGPORT_APP_SECRET", "LONGPORT_ACCESS_TOKEN"]:
        if var in content:
            break
    else:
        pytest.fail("If .env.example exists, it should include LongPort environment variables.")
