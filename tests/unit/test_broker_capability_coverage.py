"""Coverage test for per-broker capability declarations (X1).

X1 requires each registered broker backend to declare its capability range
independently, so that one backend's evidence is never inferred onto another.
This test locks that contract: every backend resolvable by the factory must
return a valid :class:`BrokerCapabilityMatrix`, and the live flag must match
the paper/simulated classification already enforced by ``is_paper_broker``.
"""

from __future__ import annotations

import pytest

from quant_execution_engine.broker import (
    get_broker_capabilities,
    is_paper_broker,
)
from quant_execution_engine.broker.base import BrokerCapabilityMatrix
from quant_execution_engine.broker.factory import PAPER_BROKERS

# Every backend the factory can resolve, including the ``alpaca`` alias of
# ``alpaca-paper``. Kept explicit (not derived from private sets) so a newly
# registered backend without a capability declaration fails loudly here.
KNOWN_BACKENDS = (
    "local-dry-run",
    "mock-sim",
    "alpaca-paper",
    "alpaca",
    "longport-paper",
    "longport",
    "ibkr-paper",
)


@pytest.mark.parametrize("backend", KNOWN_BACKENDS)
def test_backend_declares_valid_capability_matrix(backend: str) -> None:
    matrix = get_broker_capabilities(backend)
    assert isinstance(matrix, BrokerCapabilityMatrix)
    # Aliased backends (e.g. ``alpaca`` resolves to the ``alpaca-paper``
    # adapter) may report the canonical name; only assert name for the
    # non-aliased entries so the alias contract stays flexible.
    if backend not in ("alpaca",):
        assert matrix.name == backend
    # A capability matrix with no capability flags would be a silent gap that
    # another backend's evidence could be misread onto; require at least one
    # declared capability or an explicit notes entry explaining the gap.
    declared = (
        matrix.supports_live_submit
        or matrix.supports_cancel
        or matrix.supports_order_query
        or matrix.supports_open_order_listing
        or matrix.supports_order_history
        or matrix.supports_fill_history
        or matrix.supports_reconcile
        or matrix.supports_account_selection
    )
    assert declared or matrix.notes, f"{backend} declares neither capability nor notes"


def test_live_capability_matches_paper_classification() -> None:
    """Live submission is only allowed for backends the factory treats as live.

    ``local-dry-run`` and ``mock-sim`` prove offline behaviour only and must
    never declare live submission, so their evidence cannot be read as real
    broker capability (the A-share known_gap guard in current-capabilities.md).
    """
    for backend in ("local-dry-run", "mock-sim"):
        assert not get_broker_capabilities(backend).supports_live_submit
        assert is_paper_broker(backend)


def test_paper_backends_are_consistent_with_factory_set() -> None:
    """The tested backend set covers every paper/simulated broker."""
    for backend in PAPER_BROKERS:
        assert backend in KNOWN_BACKENDS, f"{backend} missing from coverage list"
