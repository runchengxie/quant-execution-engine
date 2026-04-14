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


def test_main_routes_orders() -> None:
    with patch.object(
        cli,
        "run_orders",
        return_value=cli.CommandResult(exit_code=0),
    ) as mock_run:
        with patch.object(sys, "argv", ["qexec", "orders", "--account", "main"]):
            result = cli.main()

    assert result == 0
    mock_run.assert_called_once_with(account="main", broker=None)


def test_main_routes_reconcile() -> None:
    with patch.object(
        cli,
        "run_reconcile",
        return_value=cli.CommandResult(exit_code=0),
    ) as mock_run:
        with patch.object(sys, "argv", ["qexec", "reconcile", "--broker", "alpaca-paper"]):
            result = cli.main()

    assert result == 0
    mock_run.assert_called_once_with(account="main", broker="alpaca-paper")


def test_main_routes_cancel() -> None:
    with patch.object(
        cli,
        "run_cancel",
        return_value=cli.CommandResult(exit_code=0),
    ) as mock_run:
        with patch.object(
            sys,
            "argv",
            ["qexec", "cancel", "fake-order-1", "--account", "main"],
        ):
            result = cli.main()

    assert result == 0
    mock_run.assert_called_once_with(
        order_ref="fake-order-1",
        account="main",
        broker=None,
    )


def test_main_routes_order() -> None:
    with patch.object(
        cli,
        "run_order",
        return_value=cli.CommandResult(exit_code=0),
    ) as mock_run:
        with patch.object(
            sys,
            "argv",
            ["qexec", "order", "fake-order-1", "--broker", "alpaca-paper"],
        ):
            result = cli.main()

    assert result == 0
    mock_run.assert_called_once_with(
        order_ref="fake-order-1",
        account="main",
        broker="alpaca-paper",
    )


def test_main_routes_retry() -> None:
    with patch.object(
        cli,
        "run_retry",
        return_value=cli.CommandResult(exit_code=0),
    ) as mock_run:
        with patch.object(
            sys,
            "argv",
            ["qexec", "retry", "fake-order-1", "--account", "main"],
        ):
            result = cli.main()

    assert result == 0
    mock_run.assert_called_once_with(
        order_ref="fake-order-1",
        account="main",
        broker=None,
    )


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


def test_run_rebalance_live_requires_explicit_enable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target_file = tmp_path / "targets.json"
    target_file.write_text("{}", encoding="utf-8")
    monkeypatch.delenv("QEXEC_ENABLE_LIVE", raising=False)

    with patch.object(cli, "read_targets_json") as mock_read_targets:
        result = cli.run_rebalance(str(target_file), dry_run=False)

    assert result.exit_code == 1
    assert result.stderr is not None
    assert "QEXEC_ENABLE_LIVE=1" in result.stderr
    mock_read_targets.assert_not_called()


def test_run_rebalance_live_rejects_repo_local_longport_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target_file = tmp_path / "targets.json"
    target_file.write_text("{}", encoding="utf-8")
    (tmp_path / ".env").write_text(
        'LONGPORT_ACCESS_TOKEN="real_token_value"\n'
        'LONGPORT_APP_SECRET="real_secret_value"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("QEXEC_ENABLE_LIVE", "1")
    monkeypatch.setattr(cli, "PROJECT_ROOT", tmp_path)

    with patch.object(cli, "read_targets_json") as mock_read_targets:
        result = cli.run_rebalance(str(target_file), dry_run=False)

    assert result.exit_code == 1
    assert result.stderr is not None
    assert ".env" in result.stderr
    assert "LONGPORT_ACCESS_TOKEN" in result.stderr
    assert "LONGPORT_APP_SECRET" in result.stderr
    mock_read_targets.assert_not_called()


def test_run_rebalance_live_ignores_placeholder_repo_env_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target_file = tmp_path / "targets.json"
    target_file.write_text("{}", encoding="utf-8")
    (tmp_path / ".env").write_text(
        'LONGPORT_APP_KEY="your_app_key_here"\n'
        'LONGPORT_APP_SECRET="your_app_secret_here"\n'
        'LONGPORT_ACCESS_TOKEN="your_real_access_token_here"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("QEXEC_ENABLE_LIVE", "1")
    monkeypatch.setattr(cli, "PROJECT_ROOT", tmp_path)

    with patch.object(cli, "read_targets_json", side_effect=RuntimeError("after-guard")):
        result = cli.run_rebalance(str(target_file), dry_run=False)

    assert result.exit_code == 1
    assert result.stderr == "after-guard"


def test_run_rebalance_live_ignores_repo_envrc_secret_references(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target_file = tmp_path / "targets.json"
    target_file.write_text("{}", encoding="utf-8")
    (tmp_path / ".envrc").write_text(
        "export LONGPORT_APP_KEY=$LONGPORT_APP_KEY\n"
        "export LONGPORT_APP_SECRET=${LONGPORT_APP_SECRET}\n"
        "export LONGPORT_ACCESS_TOKEN=$(op read secret://longport/token)\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("QEXEC_ENABLE_LIVE", "1")
    monkeypatch.setattr(cli, "PROJECT_ROOT", tmp_path)

    with patch.object(cli, "read_targets_json", side_effect=RuntimeError("after-guard")):
        result = cli.run_rebalance(str(target_file), dry_run=False)

    assert result.exit_code == 1
    assert result.stderr == "after-guard"


def test_run_rebalance_paper_execute_does_not_require_live_enable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target_file = tmp_path / "targets.json"
    target_file.write_text("{}", encoding="utf-8")
    monkeypatch.delenv("QEXEC_ENABLE_LIVE", raising=False)

    with patch.object(cli, "read_targets_json", side_effect=RuntimeError("after-guard")):
        result = cli.run_rebalance(
            str(target_file),
            dry_run=False,
            broker="alpaca-paper",
        )

    assert result.exit_code == 1
    assert result.stderr == "after-guard"


def test_app_function() -> None:
    with patch.object(cli, "main", return_value=0) as mock_main:
        with patch.object(sys, "exit") as mock_exit:
            cli.app()

    mock_main.assert_called_once()
    mock_exit.assert_called_once_with(0)
