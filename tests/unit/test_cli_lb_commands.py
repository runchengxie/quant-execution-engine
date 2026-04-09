from types import SimpleNamespace
from unittest.mock import Mock, patch

import logging
import sys
from pathlib import Path

import pytest
import stock_analysis.app.cli as cli


pytestmark = pytest.mark.unit


def test_cli_dispatch_lb_quote(monkeypatch):
    """Test CLI dispatch of lb-quote to run_lb_quote."""
    called = {}

    def fake_run_lb_quote(tickers):
        called["tickers"] = tickers
        return 0

    monkeypatch.setattr(
        "stock_analysis.app.commands.lb_quote.run_lb_quote", fake_run_lb_quote
    )

    with patch.object(sys, "argv", ["stockq", "lb-quote", "AAPL", "MSFT"]):
        result = cli.main()

    assert result == 0
    assert called["tickers"] == ["AAPL", "MSFT"]


def test_main_routes_lb_rebalance():
    """Test lb-rebalance routing and argument translation."""
    with patch.object(cli, "run_lb_rebalance", return_value=0) as mock_run:
        with patch.object(
            sys,
            "argv",
            [
                "stockq",
                "lb-rebalance",
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
    mock_run.assert_called_once_with("targets.json", "main-2", False, "real", 0.9)


def test_main_routes_lb_account():
    """Test lb-account routing."""
    with patch.object(cli, "run_lb_account", return_value=0) as mock_run:
        with patch.object(sys, "argv", ["stockq", "lb-account", "--format", "json"]):
            result = cli.main()

    assert result == 0
    mock_run.assert_called_once_with(only_funds=False, only_positions=False, fmt="json")


def test_main_routes_lb_config():
    """Test lb-config routing."""
    with patch.object(cli, "run_lb_config", return_value=0) as mock_run:
        with patch.object(sys, "argv", ["stockq", "lb-config"]):
            result = cli.main()

    assert result == 0
    mock_run.assert_called_once_with(True)


def test_main_no_command():
    """Test that help information is displayed when no command is provided."""
    args = SimpleNamespace()
    args.command = None

    with patch.object(cli, "create_parser") as mock_parser:
        mock_parser_instance = Mock()
        mock_parser.return_value = mock_parser_instance
        mock_parser_instance.parse_args.return_value = args

        result = cli.main()
        assert result == 0
        mock_parser_instance.print_help.assert_called_once()


def test_main_unknown_command(caplog):
    """Test the handling of an unknown command."""
    args = SimpleNamespace()
    args.command = "unknown-command"

    with patch.object(cli, "create_parser") as mock_parser:
        mock_parser_instance = Mock()
        mock_parser.return_value = mock_parser_instance
        mock_parser_instance.parse_args.return_value = args

        with caplog.at_level(logging.ERROR):
            result = cli.main()
        assert result == 1
        assert "Unknown command: unknown-command" in caplog.text


def test_run_lb_quote_import_error(caplog):
    """Test the handling of an ImportError in run_lb_quote."""
    original_import = __builtins__["__import__"]

    def mock_import(name, *args, **kwargs):
        if "longport_client" in name:
            raise ImportError("No module named 'longport'")
        return original_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=mock_import):
        with caplog.at_level(logging.ERROR):
            result = cli.run_lb_quote(["AAPL"])
    assert result == 1
    assert "longport" in caplog.text.lower()


def test_run_lb_rebalance_file_not_found(capsys):
    """Test the handling of a non-existent file in run_lb_rebalance."""
    result = cli.run_lb_rebalance("non_existent_file.xlsx")
    assert result == 1
    err = capsys.readouterr().err
    assert "File not found" in err


def test_run_lb_rebalance_rejects_legacy_workbook(tmp_path: Path, caplog):
    """Test that execution rejects legacy workbook inputs with a schema hint."""
    legacy_file = tmp_path / "legacy.xlsx"
    legacy_file.write_text("legacy workbook placeholder", encoding="utf-8")

    with caplog.at_level(logging.ERROR):
        result = cli.run_lb_rebalance(str(legacy_file))

    assert result == 1
    assert "deprecated" in caplog.text.lower()
    assert "schema-v2" in caplog.text.lower()


def test_app_function():
    """Test the app function as the entry point."""
    with patch.object(cli, "main", return_value=0) as mock_main:
        with patch.object(sys, "exit") as mock_exit:
            cli.app()
            mock_main.assert_called_once()
            mock_exit.assert_called_once_with(0)
