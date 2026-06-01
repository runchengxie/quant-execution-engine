"""Local offline broker adapter for file-contract dry-run evidence."""

from __future__ import annotations

import os

from ..models import AccountSnapshot, Quote
from .base import BrokerAdapter, BrokerCapabilityMatrix, ResolvedBrokerAccount, utc_now_iso


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw in (None, ""):
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


class LocalDryRunBrokerAdapter(BrokerAdapter):
    """Deterministic no-network adapter used only for dry-run target parsing."""

    backend_name = "local-dry-run"
    capabilities = BrokerCapabilityMatrix(
        name="local-dry-run",
        supports_live_submit=False,
        supports_cancel=False,
        supports_order_query=False,
        supports_open_order_listing=False,
        supports_reconcile=False,
        supports_account_selection=True,
        supports_fractional=False,
        supports_short=False,
        supported_order_types=("MARKET",),
        supported_time_in_force=("DAY",),
        notes={
            "mode": "offline",
            "scope": "file-contract dry-run only",
            "cash_env": "QEXEC_LOCAL_DRY_RUN_CASH_USD",
            "price_env": "QEXEC_LOCAL_DRY_RUN_PRICE",
        },
    )

    def resolve_account(self, account_label: str | None = None) -> ResolvedBrokerAccount:
        return ResolvedBrokerAccount(label=str(account_label or "main").strip() or "main")

    def get_account_snapshot(
        self,
        account: ResolvedBrokerAccount | None = None,
        *,
        include_quotes: bool = True,
    ) -> AccountSnapshot:
        cash_usd = _env_float("QEXEC_LOCAL_DRY_RUN_CASH_USD", 1_000_000.0)
        return AccountSnapshot(
            env="paper",
            cash_usd=cash_usd,
            positions=[],
            total_portfolio_value=cash_usd,
            base_currency="USD",
        )

    def get_quotes(self, symbols: list[str], *, include_depth: bool = False) -> dict[str, Quote]:
        price = _env_float("QEXEC_LOCAL_DRY_RUN_PRICE", 10.0)
        timestamp = utc_now_iso()
        return {
            str(symbol): Quote(symbol=str(symbol), price=price, timestamp=timestamp)
            for symbol in symbols
        }

    def lot_size(self, symbol: str) -> int:
        return 100 if str(symbol).upper().endswith(".CN") else 1
