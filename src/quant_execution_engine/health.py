"""Quick health check — combines preflight + state-doctor into one operator summary.

Intentionally lightweight: does NOT submit orders, does NOT mutate state.
"""

from __future__ import annotations

from dataclasses import dataclass

from .preflight import PreflightResult, run_preflight_checks
from .state_tools import StateDoctorResult, StateMaintenanceService


class HealthCheckError(RuntimeError):
    """Raised when a health check cannot complete."""


@dataclass(slots=True)
class HealthResult:
    """Combined health summary for operator consumption."""

    broker_name: str
    account_label: str
    preflight: PreflightResult | None = None
    state_doctor: StateDoctorResult | None = None
    preflight_error: str | None = None
    state_doctor_error: str | None = None

    @property
    def healthy(self) -> bool:
        """True when both preflight and state-doctor pass."""
        preflight_ok = self.preflight is not None and not self.preflight.has_failures
        state_ok = self.state_doctor is not None and self._state_issue_count == 0
        return preflight_ok and state_ok

    @property
    def _state_issue_count(self) -> int:
        if self.state_doctor is None:
            return 0
        return sum(1 for i in self.state_doctor.issues if i.severity != "INFO")

    @property
    def issues(self) -> list[str]:
        items: list[str] = []
        if self.preflight_error:
            items.append(f"preflight: {self.preflight_error}")
        if self.preflight and self.preflight.has_failures:
            failure_count = sum(
                1 for c in self.preflight.checks if c.outcome == "FAIL"
            )
            items.append(f"preflight: {failure_count} failure(s)")
        if self.state_doctor_error:
            items.append(f"state-doctor: {self.state_doctor_error}")
        if self.state_doctor is not None and self._state_issue_count > 0:
            items.append(
                f"state-doctor: {self._state_issue_count} issue(s)"
            )
        return items


def run_health(
    *,
    broker_name: str | None = None,
    account_label: str = "main",
) -> HealthResult:
    """Run preflight + state-doctor and return a combined health summary."""
    from .broker import resolve_broker_name

    resolved = resolve_broker_name(broker_name)
    result = HealthResult(
        broker_name=resolved,
        account_label=account_label,
    )

    # Preflight
    try:
        result.preflight = run_preflight_checks(
            broker_name=resolved,
            account_label=account_label,
            symbols=["AAPL"],
        )
    except Exception as exc:
        result.preflight_error = str(exc)

    # State doctor
    try:
        service = StateMaintenanceService()
        result.state_doctor = service.doctor(
            broker_name=resolved, account_label=account_label
        )
    except Exception as exc:
        result.state_doctor_error = str(exc)

    return result


def render_health_result(result: HealthResult) -> str:
    """Render a health result for the operator."""
    lines = [
        f"Health check: {result.broker_name} / {result.account_label}",
        f"Status: {'HEALTHY' if result.healthy else 'UNHEALTHY — see details below'}",
        "",
    ]

    # Preflight section
    if result.preflight_error:
        lines.append(f"  Preflight: ERROR — {result.preflight_error}")
    elif result.preflight is None:
        lines.append("  Preflight: (not run)")
    else:
        pf = result.preflight
        failed = [c for c in pf.checks if c.outcome == "FAIL"]
        warned = [c for c in pf.checks if c.outcome == "WARN"]
        ok_count = len(pf.checks) - len(failed) - len(warned)
        status = "PASS" if not pf.has_failures else "FAIL"
        flags = ""
        if warned:
            flags = f", {len(warned)} warning(s)"
        lines.append(
            f"  Preflight: {status} ({ok_count} ok, {len(failed)} failed{flags})"
        )
        for check in failed:
            lines.append(f"    FAIL - {check.name}: {check.message}")
        for check in warned:
            lines.append(f"    WARN - {check.name}: {check.message}")

    lines.append("")

    # State doctor section
    if result.state_doctor_error:
        lines.append(f"  State doctor: ERROR — {result.state_doctor_error}")
    elif result.state_doctor is None:
        lines.append("  State doctor: (not run)")
    else:
        sd = result.state_doctor
        real_issues = [i for i in sd.issues if i.severity != "INFO"]
        status = "PASS" if not real_issues else "ISSUES"
        lines.append(
            f"  State doctor: {status} ({len(real_issues)} issue(s))"
        )
        for issue in real_issues:
            lines.append(f"    - {issue.message}")

    lines.append("")
    if result.healthy:
        lines.append("No issues found — ready for execution.")
    else:
        issues = result.issues
        lines.append(f"Issues ({len(issues)}):")
        for issue in issues:
            lines.append(f"  - {issue}")

    return "\n".join(lines)
