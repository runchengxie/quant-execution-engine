"""RebalanceService core: client lifecycle + symbol/currency helpers.

This is the base layer of :class:`RebalanceService` (broker-client lifecycle and
symbol canonicalization / quote-currency lookup). Pricing, planning, and
execution layers build on top in the sibling ``_rebalance_*`` modules.
"""

from __future__ import annotations

from typing import Any

from .broker.base import BrokerAdapter, BrokerReconcileReport
from .broker.factory import (
    get_broker_adapter,
    peek_broker_name,
    resolve_broker_name,
    resolve_default_account_label,
)
from .logging import get_logger
from .targets import KNOWN_MARKETS, TargetEntry

logger = get_logger(__name__)

QUOTE_CURRENCY_BY_MARKET = {
    "US": "USD",
    "HK": "HKD",
    "CN": "CNY",
    "SG": "SGD",
}


class RebalanceCoreMixin:
    """Client lifecycle + symbol/currency helpers (base layer)."""

    def __init__(
        self,
        env: str = "real",
        client: Any | BrokerAdapter | None = None,
        *,
        broker_name: str | None = None,
        account_label: str | None = None,
    ):
        self.env = env
        self.client = client
        self.broker_name = peek_broker_name(broker_name) or ""
        self.account_label = resolve_default_account_label(account_label)
        self._last_reconcile_report: BrokerReconcileReport | None = None

    def _resolved_broker_name(self) -> str:
        return self.broker_name or resolve_broker_name()

    def _get_client(self) -> Any:
        """Get client instance"""
        if not self.client:
            self.client = get_broker_adapter(broker_name=self._resolved_broker_name())
        return self.client

    def _get_adapter(self) -> BrokerAdapter:
        return get_broker_adapter(
            broker_name=self._resolved_broker_name(),
            client=self._get_client(),
        )

    def close(self):
        """Close client connection"""
        if self.client:
            close_fn = getattr(self.client, "close", None)
            if callable(close_fn):
                close_fn()
            self.client = None

    @staticmethod
    def _coerce_lb_symbol(target: str | TargetEntry) -> str:
        if isinstance(target, TargetEntry):
            if target.market == "CN" and target.symbol.endswith((".SH", ".SZ", ".BJ")):
                return f"{target.symbol}.CN"
            return f"{target.symbol}.{target.market}"
        normalized = str(target).upper().strip()
        if "." in normalized:
            parts = normalized.split(".")
            if len(parts) == 3 and parts[-1] in KNOWN_MARKETS:
                return normalized
            base, suffix = normalized.rsplit(".", 1)
            if base and suffix in KNOWN_MARKETS:
                return f"{base}.{suffix}"
            if suffix in {"SH", "SZ", "BJ"}:
                return f"{base.zfill(6) if base.isdigit() else base}.{suffix}.CN"
            if suffix == "XSHG":
                return f"{base.zfill(6) if base.isdigit() else base}.SH.CN"
            if suffix == "XSHE":
                return f"{base.zfill(6) if base.isdigit() else base}.SZ.CN"
        return f"{normalized}.US"

    @staticmethod
    def _quote_currency(symbol: str) -> str:
        suffix = str(symbol).upper().rsplit(".", 1)[-1]
        return QUOTE_CURRENCY_BY_MARKET.get(suffix, "USD")
