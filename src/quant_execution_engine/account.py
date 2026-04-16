"""Account snapshot service

Provides business logic for account snapshots, returning structured data.
"""

from __future__ import annotations

from typing import Any

from .broker.base import BrokerAdapter
from .broker.factory import get_broker_adapter, resolve_default_account_label
from .logging import get_logger
from .models import AccountSnapshot, Quote

logger = get_logger(__name__)


def _resolve_adapter(
    *,
    broker_name: str | None = None,
    client: Any | BrokerAdapter | None = None,
) -> tuple[BrokerAdapter, bool]:
    created_here = client is None
    adapter = get_broker_adapter(broker_name=broker_name, client=client)
    return adapter, created_here


def get_account_snapshot(
    env: str = "real",
    include_quotes: bool = True,
    pre_quotes: dict[str, tuple[float, str]] | None = None,
    client: Any | BrokerAdapter | None = None,
    *,
    broker_name: str | None = None,
    account_label: str | None = None,
) -> AccountSnapshot:
    """Get account snapshot

    Args:
        env: Environment selection (only 'real' is supported, parameter kept for compatibility)

    Returns:
        AccountSnapshot: Account snapshot data

    Raises:
        Exception: When unable to retrieve account data
    """
    try:
        adapter, created_here = _resolve_adapter(broker_name=broker_name, client=client)
        account = adapter.resolve_account(account_label or resolve_default_account_label())
        snapshot = adapter.get_account_snapshot(account, include_quotes=include_quotes)
        snapshot.env = env
        if pre_quotes:
            for position in snapshot.positions:
                price, _ = pre_quotes.get(position.symbol, (position.last_price, ""))
                price_float = float(price or 0.0)
                if price_float > 0:
                    position.last_price = price_float
                    position.estimated_value = float(position.quantity) * price_float
        if created_here:
            adapter.close()
        return snapshot

    except ImportError as e:  # Surface missing dependency clearly
        logger.error(f"Failed to import broker module: {e}")
        raise
    except Exception as e:
        logger.error(f"Failed to get account data: {e}")
        raise RuntimeError(f"Failed to get account data: {e}") from e


def get_multiple_account_snapshots(envs: list[str]) -> list[AccountSnapshot]:
    """Get account snapshots for multiple environments."""
    return [get_account_snapshot(env=env) for env in envs]


def get_quotes(
    symbols: list[str],
    client: Any | BrokerAdapter | None = None,
    *,
    broker_name: str | None = None,
) -> dict[str, Quote]:
    """Get stock quotes

    Args:
        symbols: List of stock symbols
        env: Environment selection

    Returns:
        Dict[str, Quote]: Mapping from stock symbols to quotes

    Raises:
        Exception: When unable to retrieve quotes
    """
    try:
        adapter, created_here = _resolve_adapter(broker_name=broker_name, client=client)
        quote_data = adapter.get_quotes(symbols)
        if created_here:
            adapter.close()
        return quote_data

    except ImportError as e:  # pragma: no cover - same reason as above
        logger.error(f"Failed to import broker module: {e}")
        raise
    except Exception as e:
        logger.error(f"Failed to get quotes: {e}")
        raise
