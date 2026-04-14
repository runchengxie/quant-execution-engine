import logging
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

import quant_execution_engine.cli as cli


pytestmark = pytest.mark.unit


def test_cli_dispatch_quote(monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict[str, object] = {}

    def fake_run_quote(
        tickers: list[str], broker: str | None = None
    ) -> cli.CommandResult:
        called["tickers"] = tickers
        called["broker"] = broker
        return cli.CommandResult(exit_code=0)

    monkeypatch.setattr(cli, "run_quote", fake_run_quote)

    with patch.object(sys, "argv", ["qexec", "quote", "AAPL", "MSFT"]):
        result = cli.main()

    assert result == 0
    assert called["tickers"] == ["AAPL", "MSFT"]
    assert called["broker"] is None


def test_main_routes_rebalance() -> None:
    with patch.object(
        cli,
        "run_rebalance",
        return_value=cli.CommandResult(exit_code=0),
    ) as mock_run:
        with patch.object(
            sys,
            "argv",
            [
                "qexec",
                "rebalance",
                "targets.json",
                "--account",
                "main-2",
                "--execute",
                "--target-gross-exposure",
                "0.9",
            ],
        ):
            result = cli.main()

    assert result == 0
    mock_run.assert_called_once_with(
        "targets.json",
        "main-2",
        dry_run=False,
        target_gross_exposure=0.9,
        broker=None,
    )


def test_main_routes_account() -> None:
    with patch.object(
        cli,
        "run_account",
        return_value=cli.CommandResult(exit_code=0),
    ) as mock_run:
        with patch.object(sys, "argv", ["qexec", "account", "--format", "json"]):
            result = cli.main()

    assert result == 0
    mock_run.assert_called_once_with(
        only_funds=False,
        only_positions=False,
        fmt="json",
        account="main",
        broker=None,
    )


def test_main_routes_config() -> None:
    with patch.object(
        cli,
        "run_config",
        return_value=cli.CommandResult(exit_code=0),
    ) as mock_run:
        with patch.object(sys, "argv", ["qexec", "config"]):
            result = cli.main()

    assert result == 0
    mock_run.assert_called_once_with(True, broker=None)


def test_main_no_command() -> None:
    args = SimpleNamespace(command=None)

    with patch.object(cli, "create_parser") as mock_parser:
        parser = Mock()
        mock_parser.return_value = parser
        parser.parse_args.return_value = args

        result = cli.main()

    assert result == 0
    parser.print_help.assert_called_once()


def test_main_unknown_command(caplog: pytest.LogCaptureFixture) -> None:
    args = SimpleNamespace(command="unknown-command")

    with patch.object(cli, "create_parser") as mock_parser:
        parser = Mock()
        mock_parser.return_value = parser
        parser.parse_args.return_value = args

        with caplog.at_level(logging.ERROR):
            result = cli.main()

    assert result == 1
    assert "Unknown command: unknown-command" in caplog.text


def test_run_quote_import_error() -> None:
    with patch(
        "quant_execution_engine.cli.get_quotes",
        side_effect=ImportError("No module named 'longport'"),
    ):
        result = cli.run_quote(["AAPL"])

    assert result.exit_code == 1
    assert result.stderr is not None
    assert "longport" in result.stderr.lower()


def test_run_rebalance_file_not_found() -> None:
    result = cli.run_rebalance("non_existent_file.json")

    assert result.exit_code == 1
    assert result.stderr == "File not found: non_existent_file.json"


def test_run_rebalance_rejects_legacy_workbook(tmp_path: Path) -> None:
    legacy_file = tmp_path / "legacy.xlsx"
    legacy_file.write_text("legacy workbook placeholder", encoding="utf-8")

    result = cli.run_rebalance(str(legacy_file))

    assert result.exit_code == 1
    assert result.stderr is not None
    assert "deprecated" in result.stderr.lower()
    assert "schema-v2" in result.stderr.lower()


def test_app_function() -> None:
    with patch.object(cli, "main", return_value=0) as mock_main:
        with patch.object(sys, "exit") as mock_exit:
            cli.app()

    mock_main.assert_called_once()
    mock_exit.assert_called_once_with(0)
