"""Evidence bundle data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class EvidenceBundleError(RuntimeError):
    """Raised when an evidence bundle cannot be produced safely."""


@dataclass(slots=True)
class EvidenceArtifact:
    """Single artifact recorded in an evidence bundle manifest."""

    name: str
    artifact_type: str
    status: str
    source_path: str | None = None
    bundle_path: str | None = None
    reason: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "artifact_type": self.artifact_type,
            "status": self.status,
            "source_path": self.source_path,
            "bundle_path": self.bundle_path,
            "reason": self.reason,
        }


@dataclass(slots=True)
class GeneratedArtifactCapture:
    """Generated artifact plus a compact manifest summary."""

    artifact: EvidenceArtifact
    manifest_summary: dict[str, Any] | None = None


@dataclass(slots=True)
class EvidenceBundleResult:
    """Summary of a generated evidence bundle."""

    run_id: str
    broker_name: str | None
    account_label: str | None
    dry_run: bool | None
    bundle_path: Path
    manifest_path: Path
    trace_summary: dict[str, Any] | None = None
    artifacts: list[EvidenceArtifact] = field(default_factory=list)

    @property
    def included_count(self) -> int:
        return sum(1 for artifact in self.artifacts if artifact.status == "included")

    @property
    def missing_count(self) -> int:
        return sum(1 for artifact in self.artifacts if artifact.status == "missing")

    @property
    def skipped_count(self) -> int:
        return sum(1 for artifact in self.artifacts if artifact.status.startswith("skipped"))


__all__ = [
    "EvidenceArtifact",
    "EvidenceBundleError",
    "EvidenceBundleResult",
    "GeneratedArtifactCapture",
]
