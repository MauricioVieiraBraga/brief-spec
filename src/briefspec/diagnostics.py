from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from briefspec.installers import (
    _project_targets,
    _user_targets,
    host_executable,
    receipt_path,
)
from briefspec.models import Runtime


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    status: str
    detail: str
    remediation: str | None = None


def _contains_hook(path: Path) -> bool:
    try:
        return "briefspec.pyz" in path.read_text(encoding="utf-8")
    except OSError:
        return False


def doctor_runtime(
    runtime: Runtime,
    *,
    scope: str = "user",
    project: Path | None = None,
    probe: bool = False,
) -> dict[str, Any]:
    project = (project or Path.cwd()).resolve() if scope == "project" else None
    skills, pyz, hook = _project_targets(runtime, project) if project else _user_targets(runtime)
    checks: list[Check] = []
    checks.append(
        Check("core", "PASS", f"Python {sys.version_info.major}.{sys.version_info.minor}")
    )
    receipt = receipt_path(runtime, scope, project)
    checks.append(
        Check(
            "receipt",
            "PASS" if receipt.is_file() else "FAIL",
            str(receipt),
            (
                None
                if receipt.is_file()
                else f"Run: briefspec install {runtime.value} --scope {scope}"
            ),
        )
    )
    installed_skills = all(
        (skills / name / "SKILL.md").is_file() for name in ("outcome-brief", "session-checkpoint")
    )
    checks.append(
        Check(
            "skills",
            "PASS" if installed_skills else "FAIL",
            str(skills),
            None if installed_skills else "Re-run the installer",
        )
    )
    checks.append(
        Check(
            "runtime bundle",
            "PASS" if pyz.is_file() else "FAIL",
            str(pyz),
            None if pyz.is_file() else "Re-run the installer",
        )
    )
    hook_ok = hook.is_file() and _contains_hook(hook)
    checks.append(
        Check(
            "hook configuration",
            "PASS" if hook_ok else "FAIL",
            str(hook),
            None if hook_ok else "Re-run the installer after resolving config conflicts",
        )
    )
    executable = host_executable(runtime)
    checks.append(
        Check(
            "host executable",
            "PASS" if executable else "WARN",
            executable or f"{runtime.value} is not on PATH",
            None if executable else f"Install/authenticate {runtime.value} for live host testing",
        )
    )

    if probe and pyz.is_file():
        payload = {
            "hook_event_name": "SessionStart",
            "session_id": "briefspec-doctor",
            "timestamp": "2026-01-01T00:00:00Z",
            "cwd": str(project or Path.cwd()),
        }
        with tempfile.TemporaryDirectory() as temporary:
            env = dict(os.environ)
            env["BRIEFSPEC_HOME"] = temporary
            result = subprocess.run(
                [
                    sys.executable,
                    str(pyz),
                    "hook",
                    "--provider",
                    runtime.value,
                    "--event",
                    "SessionStart",
                ],
                input=json.dumps(payload),
                text=True,
                capture_output=True,
                env=env,
                timeout=15,
                check=False,
            )
        probe_ok = result.returncode == 0
        checks.append(
            Check(
                "synthetic hook",
                "PASS" if probe_ok else "FAIL",
                result.stdout.strip() or result.stderr.strip() or f"exit {result.returncode}",
                None if probe_ok else "Run the hook command directly for diagnostics",
            )
        )
    status = (
        "FAIL"
        if any(item.status == "FAIL" for item in checks)
        else ("WARN" if any(item.status == "WARN" for item in checks) else "PASS")
    )
    return {
        "runtime": runtime.value,
        "scope": scope,
        "status": status,
        "checks": [asdict(item) for item in checks],
    }
