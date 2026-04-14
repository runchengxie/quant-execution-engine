import json
from unittest.mock import patch

import pytest

import quant_execution_engine.cli as cli
from quant_execution_engine.models import AccountSnapshot, Position


def make_snapshot(
    cash: float,
    positions: list[tuple[str, int, float]],
) -> AccountSnapshot:
    rendered_positions = [
        Position(symbol=symbol, quantity=quantity, last_price=price, estimated_value=quantity * price, env="real")
        for symbol, quantity, price in positions
    ]
    return AccountSnapshot(env="real", cash_usd=cash, positions=rendered_positions)


@pytest.mark.unit
class TestAccountTableOutput:
    def test_account_prints_positions_table(self) -> None:
        snapshot = make_snapshot(1234.56, [("AAPL.US", 10, 199.99)])

        with patch("quant_execution_engine.cli.get_account_snapshot", return_value=snapshot):
            result = cli.run_account(only_funds=False, only_positions=False, fmt="table")

        assert result.exit_code == 0
        assert result.stdout is not None
        assert "Cash" in result.stdout
        assert "Positions" in result.stdout
        assert "AAPL.US" in result.stdout

    def test_table_output_only_funds(self) -> None:
        snapshot = make_snapshot(2500.75, [("AAPL.US", 10, 150.0)])

        with patch("quant_execution_engine.cli.get_account_snapshot", return_value=snapshot):
            result = cli.run_account(only_funds=True, only_positions=False, fmt="table")

        assert result.exit_code == 0
        assert result.stdout is not None
        assert "Cash (USD): $2,500.75" in result.stdout
        assert "AAPL.US" not in result.stdout

    def test_table_output_only_positions(self) -> None:
        snapshot = make_snapshot(1000.0, [("GOOGL.US", 2, 2500.0), ("AMZN.US", 1, 3000.0)])

        with patch("quant_execution_engine.cli.get_account_snapshot", return_value=snapshot):
            result = cli.run_account(only_funds=False, only_positions=True, fmt="table")

        assert result.exit_code == 0
        assert result.stdout is not None
        assert "Cash (USD)" not in result.stdout
        assert "GOOGL.US" in result.stdout
        assert "AMZN.US" in result.stdout

    def test_table_output_no_positions(self) -> None:
        snapshot = make_snapshot(1000.0, [])

        with patch("quant_execution_engine.cli.get_account_snapshot", return_value=snapshot):
            result = cli.run_account(only_funds=False, only_positions=False, fmt="table")

        assert result.exit_code == 0
        assert result.stdout is not None
        assert "No positions held" in result.stdout


@pytest.mark.unit
class TestAccountJsonOutput:
    def test_json_output(self) -> None:
        snapshot = make_snapshot(1500.5, [("AAPL.US", 10, 150.05)])

        with patch("quant_execution_engine.cli.get_account_snapshot", return_value=snapshot):
            result = cli.run_account(fmt="json")

        assert result.exit_code == 0
        assert result.stdout is not None
        data = json.loads(result.stdout)
        assert isinstance(data, list)
        assert data[0]["env"] == "real"
        assert data[0]["cash_usd"] == 1500.5
        assert data[0]["positions"][0]["symbol"] == "AAPL.US"


@pytest.mark.unit
class TestAccountErrorHandling:
    def test_import_error_handling(self) -> None:
        with patch(
            "quant_execution_engine.cli.get_account_snapshot",
            side_effect=ImportError("No module named 'longport'"),
        ):
            result = cli.run_account()

        assert result.exit_code == 1
        assert result.stderr is not None
        assert "longport" in result.stderr.lower()

    def test_client_connection_error(self) -> None:
        with patch(
            "quant_execution_engine.cli.get_account_snapshot",
            side_effect=Exception("Connection failed"),
        ):
            result = cli.run_account(fmt="table")

        assert result.exit_code == 1
        assert result.stderr == "Failed to get account overview: Connection failed"


@pytest.mark.unit
class TestAccountParameterValidation:
    def test_invalid_format_falls_back_to_table(self) -> None:
        snapshot = make_snapshot(1000.0, [])

        with patch("quant_execution_engine.cli.get_account_snapshot", return_value=snapshot):
            result = cli.run_account(fmt="xml")

        assert result.exit_code == 0
        assert result.stdout is not None
        assert "Cash (USD)" in result.stdout
        assert "{" not in result.stdout

    def test_conflicting_flags_prefer_funds_view(self) -> None:
        snapshot = make_snapshot(1000.0, [("AAPL.US", 10, 150.0)])

        with patch("quant_execution_engine.cli.get_account_snapshot", return_value=snapshot):
            result = cli.run_account(
                only_funds=True,
                only_positions=True,
                fmt="table",
            )

        assert result.exit_code == 0
        assert result.stdout is not None
        assert "Cash (USD)" in result.stdout
        assert "AAPL.US" not in result.stdout
