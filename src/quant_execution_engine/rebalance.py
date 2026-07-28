"""Rebalancing service (public facade).

The implementation is split into behavior-preserving submodules:

* ``_rebalance_core`` -- broker-client lifecycle + symbol/currency helpers.
* ``_rebalance_pricing`` -- quote fetch, USD normalization, valuation.
* ``_rebalance_plan`` -- order construction + ``plan_rebalance``.
* ``_rebalance_exec`` -- order execution + audit-log persistence.

External imports (``RebalanceService``, and ``FeeSchedule`` re-exported from
``.fees``) resolve through this shell so public behavior is unchanged.
"""

from ._rebalance_exec import RebalanceExecutionMixin
from .account import get_quotes
from .fees import FeeSchedule
from .fx import get_rate_to_usd

__all__ = ["FeeSchedule", "RebalanceService", "get_quotes", "get_rate_to_usd"]


class RebalanceService(RebalanceExecutionMixin):
    """Rebalancing service class"""
