import pytest

from stock_analysis.app.cli import create_parser


pytestmark = pytest.mark.e2e


def test_create_parser_execution_help():
    """Smoke test for the execution parser."""
    parser = create_parser()

    assert parser.prog == "stockq"
    assert "Execution Engine" in parser.description


@pytest.mark.parametrize(
    "argv",
    [
        ["lb-quote", "AAPL"],
        ["lb-account"],
        ["lb-account", "--format", "json"],
        ["lb-config"],
        ["lb-rebalance", "targets.json"],
        ["lb-rebalance", "targets.json", "--execute"],
    ],
)
def test_execution_subcommand_parsing(argv):
    """Smoke test for supported execution-only subcommands."""
    parser = create_parser()
    args = parser.parse_args(argv)

    assert args.command == argv[0]
