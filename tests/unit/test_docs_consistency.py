from __future__ import annotations

import argparse
import re
from pathlib import Path

import pytest

from quant_execution_engine.broker.factory import (
    ALPACA_BROKERS,
    IBKR_BROKERS,
    LONGPORT_BROKERS,
    PAPER_BROKERS,
)
from quant_execution_engine.cli_parser import create_parser

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]


def _top_level_commands() -> set[str]:
    parser = create_parser()
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return set(action.choices)
    raise AssertionError("qexec parser does not declare subcommands")


def _pytest_markers() -> set[str]:
    marker_names: set[str] = set()
    in_markers = False
    for line in (ROOT / "pyproject.toml").read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped == "markers = [":
            in_markers = True
            continue
        if in_markers and stripped == "]":
            break
        if in_markers:
            match = re.match(r'"([^:]+):', stripped)
            if match:
                marker_names.add(match.group(1).strip())
    assert marker_names
    return marker_names


def test_cli_docs_cover_top_level_qexec_commands() -> None:
    docs = (ROOT / "docs" / "cli.md").read_text(encoding="utf-8")

    missing = sorted(
        command
        for command in _top_level_commands()
        if f"### `{command}`" not in docs and f"qexec {command}" not in docs
    )

    assert missing == []


def test_testing_docs_cover_pytest_markers() -> None:
    docs = (ROOT / "docs" / "testing.md").read_text(encoding="utf-8")

    missing = sorted(marker for marker in _pytest_markers() if f"`{marker}`" not in docs)

    assert missing == []


def test_broker_smoke_docs_cover_registered_backends() -> None:
    capabilities = (ROOT / "docs" / "current-capabilities.md").read_text(encoding="utf-8")
    docs_index = (ROOT / "docs" / "README.md").read_text(encoding="utf-8")
    testing = (ROOT / "docs" / "testing.md").read_text(encoding="utf-8")

    registered = sorted(ALPACA_BROKERS | IBKR_BROKERS | LONGPORT_BROKERS | PAPER_BROKERS)
    missing_from_matrix = [broker for broker in registered if f"`{broker}`" not in capabilities]
    assert missing_from_matrix == []

    smoke_docs = {
        "alpaca-paper": "alpaca-paper-smoke.md",
        "ibkr-paper": "ibkr-paper-smoke.md",
        "longport-paper": "longport-paper-failure-smoke.md",
        "longport": "longport-real-smoke.md",
    }
    missing_docs: list[str] = []
    missing_links: list[str] = []
    missing_backend_mentions: list[str] = []
    for broker, doc_name in smoke_docs.items():
        doc_path = ROOT / "docs" / doc_name
        if not doc_path.is_file():
            missing_docs.append(doc_name)
            continue
        if doc_name not in docs_index or doc_name not in testing:
            missing_links.append(doc_name)
        doc_text = doc_path.read_text(encoding="utf-8")
        if f"`{broker}`" not in doc_text and f"--broker {broker}" not in doc_text:
            missing_backend_mentions.append(doc_name)

    assert missing_docs == []
    assert missing_links == []
    assert missing_backend_mentions == []
