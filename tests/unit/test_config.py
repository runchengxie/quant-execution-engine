import logging

import pytest
import yaml

import quant_execution_engine.config as config


pytestmark = pytest.mark.unit


def test_load_cfg_prefers_config_dir_yaml(tmp_path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_file = config_dir / "config.yaml"
    config_file.write_text(
        yaml.safe_dump({"fees": {"commission": 1.23}}),
        encoding="utf-8",
    )

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(config, "PROJECT_ROOT", tmp_path)
        loaded = config.load_cfg()

    assert loaded["fees"]["commission"] == 1.23


def test_load_cfg_falls_back_to_root_yaml(tmp_path) -> None:
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        yaml.safe_dump({"fx": {"to_usd": {"HKD": 0.128}}}),
        encoding="utf-8",
    )

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(config, "PROJECT_ROOT", tmp_path)
        loaded = config.load_cfg()

    assert loaded["fx"]["to_usd"]["HKD"] == 0.128


def test_load_cfg_returns_empty_dict_when_missing(tmp_path) -> None:
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(config, "PROJECT_ROOT", tmp_path)
        loaded = config.load_cfg()

    assert loaded == {}


def test_load_cfg_returns_empty_dict_on_yaml_error(
    tmp_path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    config_file = tmp_path / "config.yaml"
    config_file.write_text("invalid: [yaml", encoding="utf-8")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(config, "PROJECT_ROOT", tmp_path)
        with caplog.at_level(logging.WARNING):
            loaded = config.load_cfg()

    assert loaded == {}
    assert "Failed to load config.yaml" in caplog.text
