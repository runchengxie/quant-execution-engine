from pathlib import Path

import pytest

from quant_execution_engine.broker.longport_credentials import resolve_longport_credentials


pytestmark = pytest.mark.unit


def test_resolve_longport_paper_credentials_prefers_non_placeholder_repo_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                'LONGPORT_APP_KEY="paper_app_key_real"',
                'LONGPORT_APP_SECRET="paper_app_secret_real"',
                'LONGPORT_ACCESS_TOKEN_TEST="paper_access_token_real"',
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("LONGPORT_APP_KEY", "your_app_key_here")
    monkeypatch.setenv("LONGPORT_APP_SECRET", "your_app_secret_here")
    monkeypatch.setenv("LONGPORT_ACCESS_TOKEN_TEST", "your_paper_access_token_here")

    creds = resolve_longport_credentials("paper", project_root=tmp_path)

    assert creds.app_key == "paper_app_key_real"
    assert creds.app_secret == "paper_app_secret_real"
    assert creds.access_token == "paper_access_token_real"
    assert creds.token_var_name == "LONGPORT_ACCESS_TOKEN_TEST"


def test_resolve_longport_real_credentials_requires_real_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / ".env").write_text(
        '\n'.join(
            [
                'LONGPORT_APP_KEY="real_app_key"',
                'LONGPORT_APP_SECRET="real_app_secret"',
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("LONGPORT_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("LONGPORT_ACCESS_TOKEN_REAL", raising=False)

    with pytest.raises(RuntimeError, match="LONGPORT_ACCESS_TOKEN"):
        resolve_longport_credentials("real", project_root=tmp_path)
