from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from briefspec import __version__
from briefspec.bundle import build_zipapp
from briefspec.config import briefspec_home
from briefspec.errors import InstallConflict
from briefspec.models import Runtime
from briefspec.resources import resource_root
from briefspec.state import atomic_write


@dataclass(frozen=True, slots=True)
class InstallOperation:
    action: str
    path: str
    detail: str


@dataclass(frozen=True, slots=True)
class _FileSnapshot:
    path: Path
    content: bytes | None
    mode: int


def _hash_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _hash_file(path: Path) -> str:
    return _hash_bytes(path.read_bytes())


def _owned_marker(content: bytes) -> bool:
    return b"Managed by BriefSpec" in content or b"briefspec:" in content


def _safe_write(
    path: Path,
    content: bytes,
    operations: list[InstallOperation],
    written: list[dict[str, Any]],
    dry_run: bool,
) -> None:
    if path.exists():
        existing = path.read_bytes()
        if existing == content:
            operations.append(InstallOperation("unchanged", str(path), "already current"))
            written.append({"path": str(path), "sha256": _hash_bytes(content), "kind": "owned"})
            return
        if not _owned_marker(existing):
            raise InstallConflict(f"Refusing to overwrite foreign file: {path}")
    operations.append(InstallOperation("write", str(path), f"{len(content)} bytes"))
    if not dry_run:
        atomic_write(path, content)
    written.append({"path": str(path), "sha256": _hash_bytes(content), "kind": "owned"})


def _copy_tree(
    source: Path,
    destination: Path,
    operations: list[InstallOperation],
    written: list[dict[str, Any]],
    dry_run: bool,
) -> None:
    for path in sorted(source.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        target = destination / path.relative_to(source)
        content = path.read_bytes()
        if (
            target.exists()
            and target.read_bytes() != content
            and (
                target.name not in {"SKILL.md", "openai.yaml"}
                or not _owned_marker(target.read_bytes())
            )
        ):
            raise InstallConflict(f"Refusing to overwrite foreign skill file: {target}")
        operations.append(InstallOperation("write", str(target), "skill asset"))
        if not dry_run:
            atomic_write(target, content)
        written.append({"path": str(target), "sha256": _hash_bytes(content), "kind": "owned"})


def _ensure_copy_tree_safe(source: Path, destination: Path) -> None:
    for path in sorted(source.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        target = destination / path.relative_to(source)
        if not target.exists() or target.read_bytes() == path.read_bytes():
            continue
        if target.name in {"SKILL.md", "openai.yaml"} and _owned_marker(target.read_bytes()):
            continue
        raise InstallConflict(f"Refusing to overwrite foreign skill file: {target}")


def _managed_skill_paths(source: Path, destination: Path) -> list[Path]:
    return [
        destination / path.relative_to(source)
        for path in sorted(source.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts
    ]


def _snapshot_files(paths: list[Path]) -> list[_FileSnapshot]:
    snapshots: list[_FileSnapshot] = []
    for path in dict.fromkeys(paths):
        if path.exists():
            snapshots.append(
                _FileSnapshot(
                    path=path,
                    content=path.read_bytes(),
                    mode=path.stat().st_mode & 0o777,
                )
            )
        else:
            snapshots.append(_FileSnapshot(path=path, content=None, mode=0o600))
    return snapshots


def _restore_files(snapshots: list[_FileSnapshot]) -> None:
    for snapshot in reversed(snapshots):
        if snapshot.content is None:
            snapshot.path.unlink(missing_ok=True)
            continue
        atomic_write(snapshot.path, snapshot.content, mode=snapshot.mode)


def _runtime_home(runtime: Runtime) -> Path:
    if runtime is Runtime.CODEX:
        return Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser()
    if runtime is Runtime.CLAUDE:
        return Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude")).expanduser()
    return Path(os.environ.get("COPILOT_HOME", Path.home() / ".copilot")).expanduser()


def _user_targets(runtime: Runtime) -> tuple[Path, Path, Path]:
    root = _runtime_home(runtime)
    skills = root / "skills"
    pyz = root / "briefspec" / "briefspec.pyz"
    if runtime is Runtime.CODEX:
        hook = root / "hooks.json"
    elif runtime is Runtime.CLAUDE:
        hook = root / "settings.json"
    else:
        hook = root / "hooks" / "briefspec.json"
    return skills, pyz, hook


def _project_targets(runtime: Runtime, project: Path) -> tuple[Path, Path, Path]:
    skills = project / ".agents" / "skills"
    if runtime is Runtime.CODEX:
        return (
            skills,
            project / ".codex" / "briefspec" / "briefspec.pyz",
            project / ".codex" / "hooks.json",
        )
    if runtime is Runtime.CLAUDE:
        return (
            skills,
            project / ".claude" / "briefspec" / "briefspec.pyz",
            project / ".claude" / "settings.json",
        )
    return (
        skills,
        project / ".github" / "briefspec" / "briefspec.pyz",
        project / ".github" / "hooks" / "briefspec.json",
    )


def _command(
    pyz: Path,
    runtime: Runtime,
    event: str,
    project: Path | None = None,
    output_profile: str = "native",
) -> str:
    if project:
        executable = "python3"
        runtime_path = pyz.relative_to(project).as_posix()
    else:
        executable = sys.executable
        runtime_path = str(pyz)
    command = (
        f"{shlex.quote(executable)} {shlex.quote(runtime_path)} "
        f"hook --provider {runtime.value} --event {event}"
    )
    if output_profile != "native":
        command += f" --output-profile {shlex.quote(output_profile)}"
    return command


def _powershell_command(
    pyz: Path,
    runtime: Runtime,
    event: str,
    project: Path | None = None,
    output_profile: str = "native",
) -> str:
    if project:
        executable = "python"
        runtime_path = pyz.relative_to(project).as_posix()
    else:
        executable = str(Path(sys.executable))
        runtime_path = str(pyz)

    def quote(value: str) -> str:
        return "'" + value.replace("'", "''") + "'"

    command = (
        f"& {quote(executable)} {quote(runtime_path)} "
        f"hook --provider {runtime.value} --event {event}"
    )
    if output_profile != "native":
        command += f" --output-profile {quote(output_profile)}"
    return command


_EVENTS = (
    ("SessionStart", "sessionStart"),
    ("UserPromptSubmit", "userPromptSubmitted"),
    ("PostToolUse", "postToolUse"),
    ("PreCompact", "preCompact"),
    ("Stop", "agentStop"),
)


def _nested_hook_block(
    runtime: Runtime,
    pyz: Path,
    project: Path | None = None,
) -> dict[str, list[dict[str, Any]]]:
    hooks: dict[str, list[dict[str, Any]]] = {}
    for pascal, _ in _EVENTS:
        hooks[pascal] = [
            {
                "matcher": "",
                "hooks": [
                    {
                        "type": "command",
                        "command": _command(pyz, runtime, pascal, project),
                        "timeout": 10,
                    }
                ],
            }
        ]
    return hooks


def _copilot_hook_block(pyz: Path, project: Path | None = None) -> dict[str, Any]:
    hooks: dict[str, list[dict[str, Any]]] = {}
    for pascal, camel in _EVENTS:
        command = _command(pyz, Runtime.COPILOT, pascal, project)
        hooks[camel] = [
            {
                "type": "command",
                "bash": command,
                "powershell": _powershell_command(
                    pyz,
                    Runtime.COPILOT,
                    pascal,
                    project,
                ),
                "timeoutSec": 10,
                "cwd": ".",
            }
        ]
    return {"version": 1, "hooks": hooks}


def _copilot_project_hook_block(pyz: Path, project: Path) -> dict[str, Any]:
    hooks: dict[str, list[dict[str, Any]]] = {}
    for pascal, _ in _EVENTS:
        hooks[pascal] = [
            {
                "type": "command",
                "bash": _command(
                    pyz,
                    Runtime.COPILOT,
                    pascal,
                    project,
                    output_profile="vscode",
                ),
                "powershell": _powershell_command(
                    pyz,
                    Runtime.COPILOT,
                    pascal,
                    project,
                    output_profile="vscode",
                ),
                "timeoutSec": 10,
                "cwd": ".",
            }
        ]
    return {"version": 1, "hooks": hooks}


def _command_from_item(item: Any) -> str:
    if not isinstance(item, dict):
        return ""
    if "hooks" in item and isinstance(item["hooks"], list):
        return "\n".join(_command_from_item(child) for child in item["hooks"])
    return str(item.get("command") or item.get("bash") or "")


def _remove_briefspec_entries(value: dict[str, Any]) -> dict[str, Any]:
    hooks = value.get("hooks")
    if not isinstance(hooks, dict):
        return value
    for event, entries in list(hooks.items()):
        if not isinstance(entries, list):
            continue
        hooks[event] = [
            entry for entry in entries if "briefspec.pyz" not in _command_from_item(entry)
        ]
        if not hooks[event]:
            hooks.pop(event, None)
    return value


def _empty_hook_file(value: dict[str, Any]) -> bool:
    allowed = {"hooks", "version"}
    return (
        not (set(value) - allowed)
        and value.get("hooks") in ({}, None)
        and value.get("version") in (1, None)
    )


def _merge_hook_file(
    runtime: Runtime,
    path: Path,
    pyz: Path,
    project: Path | None = None,
) -> bytes:
    try:
        existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except json.JSONDecodeError as exc:
        raise InstallConflict(f"Cannot merge malformed JSON: {path}: {exc}") from exc
    if not isinstance(existing, dict):
        raise InstallConflict(f"Cannot merge non-object JSON: {path}")
    existing = _remove_briefspec_entries(existing)
    if runtime is Runtime.COPILOT:
        block = (
            _copilot_project_hook_block(pyz, project)
            if project is not None
            else _copilot_hook_block(pyz)
        )
        existing["version"] = 1
        hooks = existing.setdefault("hooks", {})
        for event, entries in block["hooks"].items():
            hooks.setdefault(event, []).extend(entries)
    else:
        hooks = existing.setdefault("hooks", {})
        for event, entries in _nested_hook_block(runtime, pyz, project).items():
            hooks.setdefault(event, []).extend(entries)
    return json.dumps(existing, indent=2, sort_keys=True).encode() + b"\n"


def _instruction_content() -> bytes:
    return b"""\
---
applyTo: "**"
---

<!-- Managed by BriefSpec. -->

Use the `outcome-brief` skill when substantive work reaches a terminal handoff.
Use `session-checkpoint` when the user asks to orient, teach, or receive a spoken recap.
Keep claims attached to inspectable proof, state unverified gaps explicitly, and never
treat the brief as more authoritative than the underlying repository or runtime evidence.
"""


def _receipt_name(runtime: Runtime, scope: str, project: Path | None) -> str:
    suffix = ""
    if project:
        suffix = "-" + hashlib.sha256(str(project.resolve()).encode()).hexdigest()[:12]
    return f"{runtime.value}-{scope}{suffix}.json"


def receipt_path(runtime: Runtime, scope: str, project: Path | None = None) -> Path:
    return briefspec_home() / "receipts" / _receipt_name(runtime, scope, project)


def _receipt_created_path(receipt: Path, path: Path) -> bool:
    try:
        value = json.loads(receipt.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return any(
        Path(entry.get("path", "")) == path and bool(entry.get("created"))
        for entry in value.get("files", [])
        if isinstance(entry, dict)
    )


def install_runtime(
    runtime: Runtime,
    *,
    scope: str = "user",
    project: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    if scope not in {"user", "project"}:
        raise ValueError("scope must be user or project")
    project = (project or Path.cwd()).resolve() if scope == "project" else None
    skills_target, pyz_target, hook_target = (
        _project_targets(runtime, project) if project else _user_targets(runtime)
    )
    operations: list[InstallOperation] = []
    written: list[dict[str, Any]] = []
    resources = resource_root()
    target_receipt = receipt_path(runtime, scope, project)
    _ensure_copy_tree_safe(resources / "skills", skills_target)
    hook_created = not hook_target.exists() or _receipt_created_path(
        target_receipt,
        hook_target,
    )
    hook_content = _merge_hook_file(runtime, hook_target, pyz_target, project)
    if runtime is Runtime.COPILOT and project:
        instruction = project / ".github" / "instructions" / "briefspec.instructions.md"
        if instruction.exists():
            existing_instruction = instruction.read_bytes()
            if existing_instruction != _instruction_content() and not _owned_marker(
                existing_instruction
            ):
                raise InstallConflict(f"Refusing to overwrite foreign file: {instruction}")

    managed_paths = _managed_skill_paths(resources / "skills", skills_target)
    managed_paths.extend((pyz_target, hook_target, target_receipt))
    if runtime is Runtime.COPILOT and project:
        managed_paths.append(instruction)
    snapshots = [] if dry_run else _snapshot_files(managed_paths)

    try:
        _copy_tree(resources / "skills", skills_target, operations, written, dry_run)
        operations.append(InstallOperation("write", str(pyz_target), "self-contained runtime"))
        if not dry_run:
            build_zipapp(pyz_target)
            written.append(
                {"path": str(pyz_target), "sha256": _hash_file(pyz_target), "kind": "owned"}
            )
        else:
            written.append({"path": str(pyz_target), "sha256": "dry-run", "kind": "owned"})

        operations.append(InstallOperation("merge", str(hook_target), "lifecycle hooks"))
        if not dry_run:
            atomic_write(hook_target, hook_content)
        written.append(
            {
                "path": str(hook_target),
                "sha256": _hash_bytes(hook_content),
                "kind": "merged",
                "created": hook_created,
            }
        )

        if runtime is Runtime.COPILOT and project:
            _safe_write(instruction, _instruction_content(), operations, written, dry_run)

        receipt = {
            "schema_version": 1,
            "briefspec_version": __version__,
            "runtime": runtime.value,
            "scope": scope,
            "project": str(project) if project else None,
            "files": written,
        }
        operations.append(InstallOperation("write", str(target_receipt), "installation receipt"))
        if not dry_run:
            atomic_write(
                target_receipt,
                json.dumps(receipt, indent=2, sort_keys=True).encode() + b"\n",
            )
    except Exception as exc:
        if snapshots:
            try:
                _restore_files(snapshots)
            except Exception as rollback_error:
                exc.add_note(f"BriefSpec rollback also failed: {rollback_error}")
        raise
    return {
        "runtime": runtime.value,
        "scope": scope,
        "project": str(project) if project else None,
        "dry_run": dry_run,
        "operations": [asdict(item) for item in operations],
        "receipt": str(target_receipt),
    }


def uninstall_runtime(
    runtime: Runtime,
    *,
    scope: str = "user",
    project: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    project = (project or Path.cwd()).resolve() if scope == "project" else None
    target_receipt = receipt_path(runtime, scope, project)
    if not target_receipt.exists():
        return {
            "runtime": runtime.value,
            "scope": scope,
            "dry_run": dry_run,
            "operations": [],
            "warnings": ["No installation receipt found"],
        }
    receipt = json.loads(target_receipt.read_text(encoding="utf-8"))
    operations: list[InstallOperation] = []
    warnings: list[str] = []
    for entry in receipt.get("files", []):
        path = Path(entry["path"])
        if entry.get("kind") == "merged":
            if not path.exists():
                continue
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                cleaned = _remove_briefspec_entries(value)
                if entry.get("created") and _empty_hook_file(cleaned):
                    operations.append(
                        InstallOperation("remove", str(path), "BriefSpec-created hook file")
                    )
                    if not dry_run:
                        path.unlink(missing_ok=True)
                else:
                    content = json.dumps(cleaned, indent=2, sort_keys=True).encode() + b"\n"
                    operations.append(
                        InstallOperation("merge-remove", str(path), "BriefSpec hooks")
                    )
                    if not dry_run:
                        atomic_write(path, content)
            except (OSError, json.JSONDecodeError):
                warnings.append(f"Preserved unreadable merged file: {path}")
            continue
        if not path.exists():
            continue
        expected = entry.get("sha256")
        if expected != "dry-run" and _hash_file(path) != expected:
            warnings.append(f"Preserved modified file: {path}")
            continue
        if _referenced_by_other_receipt(path, target_receipt):
            warnings.append(f"Preserved shared file still used by another install: {path}")
            continue
        operations.append(InstallOperation("remove", str(path), "receipt-owned file"))
        if not dry_run:
            path.unlink()
    operations.append(InstallOperation("remove", str(target_receipt), "installation receipt"))
    if not dry_run:
        target_receipt.unlink(missing_ok=True)
        _prune_empty_parents(receipt)
    return {
        "runtime": runtime.value,
        "scope": scope,
        "dry_run": dry_run,
        "operations": [asdict(item) for item in operations],
        "warnings": warnings,
    }


def _referenced_by_other_receipt(path: Path, current_receipt: Path) -> bool:
    root = briefspec_home() / "receipts"
    if not root.exists():
        return False
    for receipt in root.glob("*.json"):
        if receipt == current_receipt:
            continue
        try:
            value = json.loads(receipt.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if any(Path(item.get("path", "")) == path for item in value.get("files", [])):
            return True
    return False


def _prune_empty_parents(receipt: dict[str, Any]) -> None:
    for entry in receipt.get("files", []):
        path = Path(entry["path"]).parent
        for _ in range(4):
            try:
                path.rmdir()
            except OSError:
                break
            path = path.parent


def host_executable(runtime: Runtime) -> str | None:
    return shutil.which(runtime.value)
