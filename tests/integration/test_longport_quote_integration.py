from datetime import date, timedelta

import pytest


pytestmark = [pytest.mark.integration, pytest.mark.requires_api]

pytest.importorskip("longport")

from quant_execution_engine.broker.longport_credentials import probe_longport_credentials
from quant_execution_engine.broker.longport import LongPortClient, get_config


def is_runtime_network_issue(message: str) -> bool:
    lowered = str(message or "").lower()
    return any(
        token in lowered
        for token in (
            "network",
            "timeout",
            "connect",
            "dns",
            "region configuration",
            "网络",
        )
    )


def check_longport_credentials() -> bool:
    creds = probe_longport_credentials("real")
    return bool(creds.app_key and creds.app_secret and creds.access_token)


@pytest.mark.skipif(
    not check_longport_credentials(),
    reason="LongPort API credentials are not configured, skipping integration tests",
)
def test_get_config_from_env() -> None:
    config = get_config()
    assert config is not None


@pytest.mark.skipif(
    not check_longport_credentials(),
    reason="LongPort API credentials are not configured, skipping integration tests",
)
def test_longport_client_initialization() -> None:
    try:
        client = LongPortClient()
        assert client.config is not None
        assert client.q is not None
        assert client.t is not None
    except Exception as exc:
        message = str(exc).lower()
        if is_runtime_network_issue(message):
            pytest.skip(f"Network/endpoint issue, skipping: {exc}")
        pytest.fail(f"LongPortClient initialization failed: {exc}")


@pytest.mark.skipif(
    not check_longport_credentials(),
    reason="LongPort API credentials are not configured, skipping integration tests",
)
def test_quote_last_real_api() -> None:
    try:
        client = LongPortClient()
        quotes = client.quote_last(["AAPL", "MSFT"])

        assert isinstance(quotes, dict)
        assert len(quotes) <= 2
        for symbol, (price, timestamp) in quotes.items():
            assert isinstance(symbol, str)
            assert symbol.endswith((".US", ".HK", ".SG"))
            assert isinstance(price, int | float)
            assert price > 0
            assert isinstance(timestamp, int)
            assert timestamp > 0
    except Exception as exc:
        message = str(exc).lower()
        if is_runtime_network_issue(message):
            pytest.skip(f"Network connection issue, skipping test: {exc}")
        if "rate limit" in message or "quota" in message:
            pytest.skip(f"API limit reached, skipping test: {exc}")
        pytest.fail(f"Failed to get quotes: {exc}")


@pytest.mark.skipif(
    not check_longport_credentials(),
    reason="LongPort API credentials are not configured, skipping integration tests",
)
def test_candles_real_api() -> None:
    end_date = date.today()
    start_date = end_date - timedelta(days=30)

    try:
        try:
            from longport.openapi import Period  # type: ignore
        except Exception:
            pytest.skip("LongPort Period enum unavailable in installed SDK")

        client = LongPortClient()
        candles = client.candles("AAPL", start_date, end_date, period=Period.Day)
        assert candles is not None
    except Exception as exc:
        message = str(exc).lower()
        if is_runtime_network_issue(message):
            pytest.skip(f"Network connection issue, skipping test: {exc}")
        if "rate limit" in message or "quota" in message:
            pytest.skip(f"API limit reached, skipping test: {exc}")
        if "market closed" in message or "no data" in message:
            pytest.skip(f"Market closed or no data, skipping test: {exc}")
        pytest.fail(f"Failed to get candlestick data: {exc}")


@pytest.mark.skipif(
    not check_longport_credentials(),
    reason="LongPort API credentials are not configured, skipping integration tests",
)
def test_symbol_conversion_integration() -> None:
    client = LongPortClient()

    for ticker in ["AAPL", "MSFT.US", "700.HK"]:
        try:
            quotes = client.quote_last([ticker])
            for symbol in quotes:
                assert symbol.endswith((".US", ".HK", ".SG"))
        except Exception as exc:
            message = str(exc).lower()
            if is_runtime_network_issue(message):
                pytest.skip(f"Network connection issue, skipping: {exc}")
            if "permission" in message or "access" in message:
                pytest.skip(f"No permission to access {ticker}, skipping: {exc}")
            if "not found" in message or "invalid" in message:
                pytest.skip(f"Ticker {ticker} is invalid or not found, skipping: {exc}")
            pytest.fail(f"Error while testing {ticker}: {exc}")


@pytest.mark.skipif(
    not check_longport_credentials(),
    reason="LongPort API credentials are not configured, skipping integration tests",
)
def test_api_error_handling() -> None:
    try:
        client = LongPortClient()
        quotes = client.quote_last(["INVALID_TICKER_12345"])
        assert isinstance(quotes, dict)
    except Exception as exc:
        message = str(exc).lower()
        if is_runtime_network_issue(message):
            pytest.skip(f"Network connection issue, skipping test: {exc}")
        assert "invalid" in message or "not found" in message or "error" in message
