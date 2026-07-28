"""RebalanceService pricing layer.

Builds on :class:`RebalanceCoreMixin`: quote fetching, USD normalization, and
effective-total / position valuation computation.
"""

from __future__ import annotations

from typing import Any

from ._rebalance_core import RebalanceCoreMixin
from .logging import get_logger
from .models import AccountSnapshot

logger = get_logger(__name__)

# Public ``rebalance`` module (loaded lazily via sys.modules; only used at call
# time). Tests monkeypatch ``quant_execution_engine.rebalance.get_quotes`` and
# ``get_rate_to_usd``, so resolve those names through this module so the patches
# take effect (behavior-preserving after the split).
from . import rebalance as _rebalance_public_module  # noqa: E402


class RebalancePricingMixin(RebalanceCoreMixin):
    """Quote fetching + USD normalization + valuation (pricing layer)."""

    def _fetch_quotes(self, targets: list[str] | list[Any]) -> dict[str, float]:
        """Fetch quotes for given tickers or canonical targets."""
        lb_symbols = [self._coerce_lb_symbol(target) for target in targets]
        quote_objs = _rebalance_public_module.get_quotes(
            lb_symbols,
            client=self._get_client(),
            broker_name=self.broker_name,
        )
        return {sym: q.price for sym, q in quote_objs.items()}

    def _normalize_quotes_to_usd(self, quotes: dict[str, float]) -> dict[str, float]:
        """Normalize native market quote prices into the USD valuation currency."""
        normalized: dict[str, float] = {}
        for symbol, price in quotes.items():
            numeric_price = float(price or 0.0)
            currency = self._quote_currency(symbol)
            if numeric_price <= 0 or currency == "USD":
                normalized[symbol] = numeric_price
                continue
            rate = _rebalance_public_module.get_rate_to_usd(currency)
            if rate is None:
                raise ValueError(
                    f"missing FX rate for {currency} quote valuation ({symbol}); "
                    f"set FX_{currency}_USD or configure fx.to_usd.{currency}"
                )
            normalized[symbol] = numeric_price * rate
        return normalized

    def _refresh_positions_from_usd_quotes(
        self,
        account_snapshot: AccountSnapshot,
        quotes: dict[str, float],
    ) -> None:
        """Refresh existing positions using quotes already normalized to USD."""
        for position in account_snapshot.positions:
            price = float(quotes.get(position.symbol, 0.0) or 0.0)
            if price > 0:
                position.last_price = price
                position.estimated_value = price * float(position.quantity)
                continue
            if position.quantity > 0 and self._quote_currency(position.symbol) != "USD":
                raise ValueError(
                    "positive quote required to value existing non-USD position "
                    f"in USD: {position.symbol}"
                )
        account_snapshot.total_market_value = sum(
            float(position.estimated_value) for position in account_snapshot.positions
        )

    def _compute_effective_total(
        self,
        account_snapshot: AccountSnapshot,
        quotes: dict[str, float],
        target_gross_exposure: float,
    ) -> float:
        """Compute effective total portfolio value after applying exposure."""
        total_pos_value_recomp = 0.0
        any_zero_priced = False
        for pos in account_snapshot.positions:
            px = float(quotes.get(pos.symbol, 0.0) or 0.0)
            if px <= 0:
                px = float(pos.last_price or 0.0)
            if px <= 0 and pos.quantity > 0:
                any_zero_priced = True
                if float(pos.estimated_value or 0.0) > 0 and pos.quantity > 0:
                    try:
                        px = float(pos.estimated_value) / float(pos.quantity)
                    except Exception:
                        px = 0.0
            val = px * float(pos.quantity)
            if val <= 0 and float(pos.estimated_value or 0.0) > 0:
                val = float(pos.estimated_value)
            total_pos_value_recomp += val

        cash_usd = float(account_snapshot.cash_usd or 0.0)
        recomputed_total = cash_usd + float(total_pos_value_recomp)

        snapshot_total = float(account_snapshot.total_portfolio_value or 0.0)

        def _close(a: float, b: float) -> bool:
            if a <= 0 and b <= 0:
                return True
            denom = max(1.0, abs(b))
            return abs(a - b) <= 0.01 * denom

        if snapshot_total > 0 and _close(snapshot_total, recomputed_total) and not any_zero_priced:
            effective_total = snapshot_total
        else:
            effective_total = recomputed_total

        exposure = max(0.0, float(target_gross_exposure))
        return effective_total * exposure
