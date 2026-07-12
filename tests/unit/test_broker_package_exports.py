import pytest

import quant_execution_engine.broker as broker


def test_lazy_broker_exports_remain_resolvable() -> None:
    lazy_exports = {
        "IbkrPaperBrokerAdapter",
        "LocalDryRunBrokerAdapter",
        "LongPortBrokerAdapter",
        "LongPortClient",
        "LongPortPaperBrokerAdapter",
        "_to_lb_symbol",
        "get_config",
        "getenv_both",
        "probe_ibkr_runtime_config",
        "resolve_ibkr_runtime_config",
    }

    assert lazy_exports <= set(broker.__all__)
    assert all(getattr(broker, name) is not None for name in lazy_exports)


def test_broker_package_rejects_unknown_lazy_export() -> None:
    missing_name = "missing_broker_export"
    with pytest.raises(AttributeError, match="has no attribute"):
        getattr(broker, missing_name)
