import pytest

from quant_execution_engine.broker.longport import _to_lb_symbol


@pytest.mark.unit
@pytest.mark.parametrize(
    ("raw", "expect"),
    [
        ("AAPL", "AAPL.US"),
        ("MSFT", "MSFT.US"),
        ("700.HK", "700.HK"),
        ("TSLA.US", "TSLA.US"),
        ("aapl", "AAPL.US"),
        ("  GOOGL  ", "GOOGL.US"),
        ("BABA.HK", "BABA.HK"),
        ("SE.SG", "SE.SG"),
        ("nvda", "NVDA.US"),
        ("\tAMZN\n", "AMZN.US"),
    ],
)
def test_to_lb_symbol(raw: str, expect: str) -> None:
    assert _to_lb_symbol(raw) == expect


@pytest.mark.unit
def test_to_lb_symbol_edge_cases() -> None:
    assert _to_lb_symbol("") == ".US"
    assert _to_lb_symbol("   ") == ".US"
    assert _to_lb_symbol("TsLa.us") == "TSLA.US"
    assert _to_lb_symbol("baba.hk") == "BABA.HK"
    assert _to_lb_symbol("se.sg") == "SE.SG"
