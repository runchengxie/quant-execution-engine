from pathlib import Path

import pytest

from quant_execution_engine.broker.longport_credentials import (
    probe_longport_credentials,
    resolve_longport_credentials,
    resolve_longport_runtime_value,
)


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
    assert creds.app_key_source == "repo-local .env (LONGPORT_APP_KEY)"
    assert creds.app_secret_source == "repo-local .env (LONGPORT_APP_SECRET)"
    assert creds.access_token_source == "repo-local .env (LONGPORT_ACCESS_TOKEN_TEST)"


def test_resolve_longport_real_credentials_uses_user_private_env_not_repo_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                'LONGPORT_APP_KEY="repo_app_key"',
                'LONGPORT_APP_SECRET="repo_app_secret"',
                'LONGPORT_ACCESS_TOKEN="repo_real_token"',
            ]
        ),
        encoding="utf-8",
    )
    user_env = tmp_path / "longport-live.env"
    user_env.write_text(
        "\n".join(
            [
                'export LONGPORT_APP_KEY="user_app_key"',
                'export LONGPORT_APP_SECRET="user_app_secret"',
                'export LONGPORT_ACCESS_TOKEN="user_real_token"',
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("LONGPORT_APP_KEY", raising=False)
    monkeypatch.delenv("LONGPORT_APP_SECRET", raising=False)
    monkeypatch.delenv("LONGPORT_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("LONGPORT_ACCESS_TOKEN_REAL", raising=False)

    creds = resolve_longport_credentials(
        "real",
        project_root=tmp_path,
        user_env_path=user_env,
    )

    assert creds.app_key == "user_app_key"
    assert creds.app_secret == "user_app_secret"
    assert creds.access_token == "user_real_token"
    assert creds.app_key_source == f"user-private {user_env} (LONGPORT_APP_KEY)"
    assert creds.app_secret_source == f"user-private {user_env} (LONGPORT_APP_SECRET)"
    assert creds.access_token_source == f"user-private {user_env} (LONGPORT_ACCESS_TOKEN)"


def test_resolve_longport_real_credentials_prefers_user_private_env_over_process_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_env = tmp_path / "longport-live.env"
    user_env.write_text(
        "\n".join(
            [
                'export LONGPORT_APP_KEY="user_app_key"',
                'export LONGPORT_APP_SECRET="user_app_secret"',
                'export LONGPORT_ACCESS_TOKEN="user_real_token"',
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("LONGPORT_APP_KEY", "process_app_key")
    monkeypatch.setenv("LONGPORT_APP_SECRET", "process_app_secret")
    monkeypatch.setenv("LONGPORT_ACCESS_TOKEN", "process_real_token")

    creds = resolve_longport_credentials(
        "real",
        project_root=tmp_path,
        user_env_path=user_env,
    )

    assert creds.app_key == "user_app_key"
    assert creds.app_secret == "user_app_secret"
    assert creds.access_token == "user_real_token"
    assert creds.access_token_source == f"user-private {user_env} (LONGPORT_ACCESS_TOKEN)"


def test_resolve_longport_real_credentials_requires_real_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_env = tmp_path / "longport-live.env"
    user_env.write_text(
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
        resolve_longport_credentials(
            "real",
            project_root=tmp_path,
            user_env_path=user_env,
        )


def test_probe_longport_paper_credentials_can_fall_back_to_user_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_env = tmp_path / "longport-live.env"
    user_env.write_text(
        "\n".join(
            [
                'export LONGPORT_APP_KEY="user_app_key"',
                'export LONGPORT_APP_SECRET="user_app_secret"',
                'export LONGPORT_ACCESS_TOKEN_TEST="user_paper_token"',
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("LONGPORT_APP_KEY", raising=False)
    monkeypatch.delenv("LONGPORT_APP_SECRET", raising=False)
    monkeypatch.delenv("LONGPORT_ACCESS_TOKEN_TEST", raising=False)

    probe = probe_longport_credentials(
        "paper",
        project_root=tmp_path,
        user_env_path=user_env,
    )

    assert probe.app_key == "user_app_key"
    assert probe.app_secret == "user_app_secret"
    assert probe.access_token == "user_paper_token"
    assert probe.app_key_source == f"user-private {user_env} (LONGPORT_APP_KEY)"
    assert probe.access_token_source == (
        f"user-private {user_env} (LONGPORT_ACCESS_TOKEN_TEST)"
    )


def test_resolve_longport_paper_runtime_prefers_repo_over_process_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / ".env").write_text(
        'LONGPORT_REGION="cn"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("LONGPORT_REGION", "hk")

    value, source = resolve_longport_runtime_value(
        ("LONGPORT_REGION",),
        env_name="paper",
        project_root=tmp_path,
    )

    assert value == "cn"
    assert source == "repo-local .env (LONGPORT_REGION)"


def test_resolve_longport_paper_runtime_can_fall_back_to_user_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_env = tmp_path / "longport-live.env"
    user_env.write_text(
        'export LONGPORT_ENABLE_OVERNIGHT="true"\n',
        encoding="utf-8",
    )
    monkeypatch.delenv("LONGPORT_ENABLE_OVERNIGHT", raising=False)

    value, source = resolve_longport_runtime_value(
        ("LONGPORT_ENABLE_OVERNIGHT",),
        env_name="paper",
        project_root=tmp_path,
        user_env_path=user_env,
    )

    assert value == "true"
    assert source == f"user-private {user_env} (LONGPORT_ENABLE_OVERNIGHT)"
