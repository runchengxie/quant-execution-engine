from unittest.mock import patch

import pytest

import quant_execution_engine.account as account


pytestmark = pytest.mark.unit


def test_get_multiple_account_snapshots() -> None:
    with patch("quant_execution_engine.account.get_account_snapshot") as mock_get:
        mock_get.side_effect = ["snap1", "snap2"]

        snapshots = account.get_multiple_account_snapshots(["real", "paper"])

    assert snapshots == ["snap1", "snap2"]
    mock_get.assert_any_call(env="real")
    mock_get.assert_any_call(env="paper")
