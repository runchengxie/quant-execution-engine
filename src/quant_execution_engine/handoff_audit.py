"""Audit research-to-execution lineage without changing order semantics."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True)
class HandoffCheck:
    name: str
    status: str
    message: str
    path: str | None = None
    expected_sha256: str | None = None
    actual_sha256: str | None = None


@dataclass(frozen=True)
class HandoffAuditReport:
    schema_version: int
    status: str
    targets_path: str
    lineage_path: str | None
    checks: tuple[HandoffCheck, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "targets_path": self.targets_path,
            "lineage_path": self.lineage_path,
            "checks": [asdict(check) for check in self.checks],
        }


def sha256_file(path: str | Path) -> str:
    source = Path(path)
    digest = hashlib.sha256()
    with source.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def audit_research_handoff(
    targets_path: str | Path,
    *,
    lineage_path: str | Path | None = None,
    require_lineage: bool = True,
    require_release_protocol: bool = False,
) -> HandoffAuditReport:
    """Validate target schema and optional provenance hashes.

    This audit never reads research performance metrics and never changes target
    weights, quantities, symbols, or order plans.
    """

    targets_file = Path(targets_path).expanduser().resolve()
    lineage_file = (
        Path(lineage_path).expanduser().resolve()
        if lineage_path is not None
        else targets_file.with_suffix(f"{targets_file.suffix}.lineage.json")
    )
    checks: list[HandoffCheck] = []

    targets = _load_json_object(targets_file, "targets")
    checks.extend(_validate_targets_payload(targets, targets_file))

    lineage: dict[str, Any] | None = None
    if lineage_file.exists():
        lineage = _load_json_object(lineage_file, "lineage")
        checks.append(
            HandoffCheck(
                name="lineage_present",
                status="pass",
                message="Lineage sidecar is present.",
                path=str(lineage_file),
            )
        )
    elif require_lineage:
        checks.append(
            HandoffCheck(
                name="lineage_present",
                status="fail",
                message="Required lineage sidecar is missing.",
                path=str(lineage_file),
            )
        )
    else:
        checks.append(
            HandoffCheck(
                name="lineage_present",
                status="warning",
                message="Lineage sidecar is not present.",
                path=str(lineage_file),
            )
        )

    if lineage is not None:
        checks.extend(
            _audit_lineage(
                lineage,
                targets_file=targets_file,
                lineage_file=lineage_file,
                require_release_protocol=require_release_protocol,
            )
        )
    elif require_release_protocol:
        checks.append(
            HandoffCheck(
                name="release_protocol",
                status="fail",
                message="Release protocol cannot be verified without lineage.",
            )
        )

    status = "fail" if any(check.status == "fail" for check in checks) else "pass"
    return HandoffAuditReport(
        schema_version=1,
        status=status,
        targets_path=str(targets_file),
        lineage_path=str(lineage_file) if lineage_file.exists() or require_lineage else None,
        checks=tuple(checks),
    )


def write_handoff_audit(report: HandoffAuditReport, path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit targets and lineage without modifying execution inputs."
    )
    parser.add_argument("targets")
    parser.add_argument("--lineage")
    parser.add_argument("--output")
    parser.add_argument(
        "--require-lineage",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument("--require-release-protocol", action="store_true")
    args = parser.parse_args(argv)
    report = audit_research_handoff(
        args.targets,
        lineage_path=args.lineage,
        require_lineage=args.require_lineage,
        require_release_protocol=args.require_release_protocol,
    )
    if args.output:
        write_handoff_audit(report, args.output)
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    return 1 if report.status == "fail" else 0


def _validate_targets_payload(
    payload: Mapping[str, Any],
    targets_file: Path,
) -> list[HandoffCheck]:
    checks: list[HandoffCheck] = []
    rows = payload.get("targets")
    if not isinstance(rows, list) or not rows:
        return [
            HandoffCheck(
                name="targets_schema",
                status="fail",
                message="targets must be a non-empty list.",
                path=str(targets_file),
            )
        ]
    errors: list[str] = []
    keys: set[tuple[str, str]] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            errors.append(f"targets[{index}] must be an object")
            continue
        symbol = str(row.get("symbol") or "").strip()
        market = str(row.get("market") or "").strip().upper()
        has_weight = row.get("target_weight") is not None
        has_quantity = row.get("target_quantity") is not None
        if not symbol or not market:
            errors.append(f"targets[{index}] requires symbol and market")
        if has_weight == has_quantity:
            errors.append(
                f"targets[{index}] must provide exactly one of target_weight or target_quantity"
            )
        key = (symbol, market)
        if key in keys:
            errors.append(f"duplicate target: {symbol}.{market}")
        keys.add(key)
    checks.append(
        HandoffCheck(
            name="targets_schema",
            status="fail" if errors else "pass",
            message="; ".join(errors) if errors else f"Validated {len(rows)} target entries.",
            path=str(targets_file),
            actual_sha256=sha256_file(targets_file),
        )
    )
    return checks


def _audit_lineage(
    lineage: Mapping[str, Any],
    *,
    targets_file: Path,
    lineage_file: Path,
    require_release_protocol: bool,
) -> list[HandoffCheck]:
    checks: list[HandoffCheck] = []
    declared_targets = lineage.get("targets_file")
    if declared_targets:
        declared_name = Path(str(declared_targets)).name
        checks.append(
            HandoffCheck(
                name="targets_path_lineage",
                status="pass" if declared_name == targets_file.name else "warning",
                message=(
                    "Lineage targets_file matches the audited target filename."
                    if declared_name == targets_file.name
                    else f"Lineage refers to {declared_name}; audited file is {targets_file.name}."
                ),
                path=str(lineage_file),
            )
        )

    expected_targets_hash = _find_hash(lineage, ("targets_sha256", "target_artifact_sha256"))
    checks.append(
        _hash_check(
            name="targets_hash",
            path=targets_file,
            expected=expected_targets_hash,
            required=False,
        )
    )

    protocol = lineage.get("research_protocol")
    if isinstance(protocol, Mapping):
        protocol_status = str(protocol.get("status") or "").strip().lower()
        protocol_path = protocol.get("path")
        status = "pass" if protocol_status == "pass" else "fail"
        checks.append(
            HandoffCheck(
                name="release_protocol",
                status=status,
                message=(
                    "Release protocol is recorded as passed."
                    if status == "pass"
                    else f"Release protocol status is {protocol_status or 'missing'}."
                ),
                path=str(protocol_path) if protocol_path else None,
            )
        )
        if protocol_path:
            checks.append(
                _hash_check(
                    name="release_protocol_hash",
                    path=_resolve_artifact_path(str(protocol_path), lineage_file),
                    expected=_find_hash(protocol, ("sha256", "artifact_sha256")),
                    required=require_release_protocol,
                )
            )
    elif require_release_protocol:
        checks.append(
            HandoffCheck(
                name="release_protocol",
                status="fail",
                message="Lineage does not contain required release protocol evidence.",
            )
        )
    else:
        checks.append(
            HandoffCheck(
                name="release_protocol",
                status="warning",
                message="Lineage does not contain release protocol evidence.",
            )
        )

    for key, display_name in (
        ("sizing_receipt", "sizing_receipt"),
        ("strategy_risk", "strategy_risk"),
    ):
        item = lineage.get(key)
        if not isinstance(item, Mapping):
            continue
        artifact_path = item.get("path")
        if artifact_path:
            checks.append(
                _hash_check(
                    name=f"{display_name}_hash",
                    path=_resolve_artifact_path(str(artifact_path), lineage_file),
                    expected=_find_hash(item, ("sha256", "artifact_sha256")),
                    required=False,
                )
            )
    return checks


def _hash_check(
    *,
    name: str,
    path: Path,
    expected: str | None,
    required: bool,
) -> HandoffCheck:
    if not path.exists():
        return HandoffCheck(
            name=name,
            status="fail" if required else "warning",
            message=f"Artifact is missing: {path}",
            path=str(path),
            expected_sha256=expected,
        )
    actual = sha256_file(path)
    if expected is None:
        return HandoffCheck(
            name=name,
            status="warning",
            message="Artifact exists but lineage has no expected SHA-256.",
            path=str(path),
            actual_sha256=actual,
        )
    matched = actual.lower() == expected.lower()
    return HandoffCheck(
        name=name,
        status="pass" if matched else "fail",
        message="SHA-256 matched." if matched else "SHA-256 mismatch.",
        path=str(path),
        expected_sha256=expected,
        actual_sha256=actual,
    )


def _find_hash(payload: Mapping[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = payload.get(key)
        if value:
            return str(value).strip()
    return None


def _resolve_artifact_path(value: str, lineage_file: Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else (lineage_file.parent / path).resolve()


def _load_json_object(path: Path, name: str) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"{name} file not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{name} file must contain a JSON object: {path}")
    return payload


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "HandoffAuditReport",
    "HandoffCheck",
    "audit_research_handoff",
    "main",
    "sha256_file",
    "write_handoff_audit",
]
