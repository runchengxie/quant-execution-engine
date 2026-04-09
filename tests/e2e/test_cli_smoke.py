import pytest

from quant_execution_engine.cli import create_parser


pytestmark = pytest.mark.e2e


def test_create_parser_execution_help() -> None:
    parser = create_parser()

    assert parser.prog == "qexec"
    assert "Quant Execution Engine" in parser.description


@pytest.mark.parametrize(
    "argv",
    [
        ["quote", "AAPL"],
        ["account"],
        ["account", "--format", "json"],
        ["config"],
        ["rebalance", "targets.json"],
        ["rebalance", "targets.json", "--execute"],
    ],
)
def test_execution_subcommand_parsing(argv: list[str]) -> None:
    parser = create_parser()
    args = parser.parse_args(argv)

    assert args.command == argv[0]
