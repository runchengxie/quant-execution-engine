import logging
from pathlib import Path
from unittest.mock import patch

import pytest

import quant_execution_engine.paths as paths
from quant_execution_engine.logging import StrategyLogger, get_run_id, set_run_id, setup_logging


pytestmark = pytest.mark.unit


def test_get_project_root_returns_existing_absolute_path() -> None:
    root = paths.get_project_root()

    assert isinstance(root, Path)
    assert root.is_absolute()
    assert root.exists()


def test_outputs_dir_exists_under_project_root() -> None:
    assert paths.OUTPUTS_DIR == paths.PROJECT_ROOT / "outputs"
    assert paths.OUTPUTS_DIR.exists()
    assert paths.OUTPUTS_DIR.is_dir()


def test_setup_logging_writes_file(tmp_path: Path) -> None:
    with patch("quant_execution_engine.logging.OUTPUTS_DIR", tmp_path):
        logger = setup_logging("qexec_file_logger", log_file="engine.log")
        logger.info("hello execution engine")

    content = (tmp_path / "engine.log").read_text(encoding="utf-8")
    assert "hello execution engine" in content
    assert "qexec_file_logger" in content


def test_setup_logging_avoids_duplicate_handlers(tmp_path: Path) -> None:
    with patch("quant_execution_engine.logging.OUTPUTS_DIR", tmp_path):
        logger1 = setup_logging("qexec_duplicate_logger", log_file="duplicate.log")
        handler_count = len(logger1.handlers)

        logger2 = setup_logging("qexec_duplicate_logger", log_file="duplicate.log")

    assert logger1 is logger2
    assert len(logger2.handlers) == handler_count


def test_setup_logging_honors_custom_level() -> None:
    logger = setup_logging("qexec_debug_logger", level=logging.DEBUG)

    assert logger.level == logging.DEBUG
    for handler in logger.handlers:
        assert handler.level == logging.DEBUG


def test_strategy_logger_falls_back_to_print(capsys: pytest.CaptureFixture[str]) -> None:
    logger = StrategyLogger(use_logging=False)

    logger.info("hello")
    logger.warning("warn")
    logger.error("bad")

    captured = capsys.readouterr()
    assert "hello" in captured.out
    assert "WARNING: warn" in captured.out
    assert "ERROR: bad" in captured.err


def test_run_id_helpers_roundtrip() -> None:
    set_run_id("fixed-run-id")

    assert get_run_id() == "fixed-run-id"
