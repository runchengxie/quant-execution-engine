from __future__ import annotations

from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parents[2]


def test_optional_sdk_unresolved_import_ignore_is_scoped_to_longport_surfaces() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    ty = config["tool"]["ty"]

    assert ty.get("rules", {}).get("unresolved-import") is None

    unresolved_import_overrides = [
        override
        for override in ty.get("overrides", [])
        if override.get("rules", {}).get("unresolved-import") == "ignore"
    ]
    assert unresolved_import_overrides == [
        {
            "include": [
                "src/quant_execution_engine/broker/_longport_sdk.py",
                "tests/integration/test_longport_quote_integration.py",
            ],
            "rules": {"unresolved-import": "ignore"},
        }
    ]
