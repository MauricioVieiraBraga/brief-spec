from __future__ import annotations

import json
from pathlib import Path

import pytest

import briefspec.installers as installers
from briefspec.errors import InstallConflict
from briefspec.models import Runtime


def test_invalid_install_scope_is_rejected_before_writes(
    isolated_homes: dict[str, Path],
) -> None:
    with pytest.raises(ValueError, match="scope must be user or project"):
        installers.install_runtime(Runtime.CODEX, scope="system")
    assert not isolated_homes["codex"].exists()


def test_non_object_hook_configuration_is_a_conflict(
    isolated_homes: dict[str, Path],
) -> None:
    _, _, hook = installers._user_targets(Runtime.CODEX)
    hook.parent.mkdir(parents=True)
    hook.write_text("[]", encoding="utf-8")
    with pytest.raises(InstallConflict, match="non-object JSON"):
        installers.install_runtime(Runtime.CODEX)
    assert hook.read_text(encoding="utf-8") == "[]"


def test_foreign_copilot_instruction_aborts_before_any_project_mutation(
    isolated_homes: dict[str, Path],
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    instruction = project / ".github" / "instructions" / "briefspec.instructions.md"
    instruction.parent.mkdir(parents=True)
    instruction.write_text("Repository-owned instructions.", encoding="utf-8")
    skills, pyz, hook = installers._project_targets(Runtime.COPILOT, project)

    with pytest.raises(InstallConflict, match="foreign file"):
        installers.install_runtime(Runtime.COPILOT, scope="project", project=project)

    assert instruction.read_text(encoding="utf-8") == "Repository-owned instructions."
    assert not skills.exists()
    assert not pyz.exists()
    assert not hook.exists()


def test_install_transaction_rolls_back_all_partial_writes(
    isolated_homes: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    skills, pyz, hook = installers._user_targets(Runtime.CLAUDE)
    receipt = installers.receipt_path(Runtime.CLAUDE, "user")
    original_atomic_write = installers.atomic_write
    failed = False

    def fail_once_at_receipt(path: Path, content: bytes, mode: int = 0o600) -> None:
        nonlocal failed
        if path == receipt and not failed:
            failed = True
            raise OSError("simulated receipt failure")
        original_atomic_write(path, content, mode)

    monkeypatch.setattr(installers, "atomic_write", fail_once_at_receipt)
    with pytest.raises(OSError, match="simulated receipt failure"):
        installers.install_runtime(Runtime.CLAUDE)

    assert not receipt.exists()
    assert not pyz.exists()
    assert not hook.exists()
    assert not any(path.is_file() for path in skills.rglob("*"))


def test_install_rollback_restores_preexisting_hook_bytes(
    isolated_homes: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, hook = installers._user_targets(Runtime.CODEX)
    hook.parent.mkdir(parents=True)
    original_hook = b'{"hooks":{"Stop":[]},"owner":"repository"}\n'
    hook.write_bytes(original_hook)
    receipt = installers.receipt_path(Runtime.CODEX, "user")
    original_atomic_write = installers.atomic_write
    failed = False

    def fail_once_at_receipt(path: Path, content: bytes, mode: int = 0o600) -> None:
        nonlocal failed
        if path == receipt and not failed:
            failed = True
            raise OSError("simulated receipt failure")
        original_atomic_write(path, content, mode)

    monkeypatch.setattr(installers, "atomic_write", fail_once_at_receipt)
    with pytest.raises(OSError, match="simulated receipt failure"):
        installers.install_runtime(Runtime.CODEX)
    assert hook.read_bytes() == original_hook


def test_rollback_failure_is_attached_to_original_error(
    isolated_homes: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        installers,
        "build_zipapp",
        lambda destination: (_ for _ in ()).throw(OSError("build failed")),
    )
    monkeypatch.setattr(
        installers,
        "_restore_files",
        lambda snapshots: (_ for _ in ()).throw(OSError("rollback failed")),
    )
    with pytest.raises(OSError, match="build failed") as raised:
        installers.install_runtime(Runtime.COPILOT)
    assert raised.value.__notes__ == ["BriefSpec rollback also failed: rollback failed"]


def test_second_project_install_recognizes_unchanged_managed_instruction(
    isolated_homes: dict[str, Path],
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    installers.install_runtime(Runtime.COPILOT, scope="project", project=project)
    result = installers.install_runtime(Runtime.COPILOT, scope="project", project=project)
    instruction = project / ".github" / "instructions" / "briefspec.instructions.md"
    operations = [
        operation for operation in result["operations"] if operation["path"] == str(instruction)
    ]
    assert operations == [
        {
            "action": "unchanged",
            "path": str(instruction),
            "detail": "already current",
        }
    ]


@pytest.mark.parametrize(
    ("runtime", "relative_bundle"),
    [
        (Runtime.CODEX, ".codex/briefspec/briefspec.pyz"),
        (Runtime.CLAUDE, ".claude/briefspec/briefspec.pyz"),
    ],
)
def test_project_hooks_use_portable_relative_bundle_paths(
    runtime: Runtime,
    relative_bundle: str,
    isolated_homes: dict[str, Path],
    tmp_path: Path,
) -> None:
    project = tmp_path / runtime.value
    project.mkdir()
    installers.install_runtime(runtime, scope="project", project=project)
    _, _, hook = installers._project_targets(runtime, project.resolve())
    text = hook.read_text(encoding="utf-8")
    assert relative_bundle in text
    assert str(project.resolve()) not in text


def test_copilot_project_hook_is_vscode_compatible_while_user_hook_stays_native(
    isolated_homes: dict[str, Path],
    tmp_path: Path,
) -> None:
    project = tmp_path / "copilot-project"
    project.mkdir()
    installers.install_runtime(Runtime.COPILOT, scope="project", project=project)
    _, _, project_hook = installers._project_targets(Runtime.COPILOT, project.resolve())
    project_value = json.loads(project_hook.read_text(encoding="utf-8"))
    assert set(project_value["hooks"]) == {
        "SessionStart",
        "UserPromptSubmit",
        "PostToolUse",
        "PreCompact",
        "Stop",
    }
    for entries in project_value["hooks"].values():
        command_text = json.dumps(entries)
        assert "--output-profile vscode" in command_text

    installers.install_runtime(Runtime.COPILOT)
    _, _, user_hook = installers._user_targets(Runtime.COPILOT)
    user_value = json.loads(user_hook.read_text(encoding="utf-8"))
    assert set(user_value["hooks"]) == {
        "sessionStart",
        "userPromptSubmitted",
        "postToolUse",
        "preCompact",
        "agentStop",
    }
    assert "--output-profile vscode" not in json.dumps(user_value)


def test_uninstall_without_receipt_is_an_explainable_noop(
    isolated_homes: dict[str, Path],
) -> None:
    result = installers.uninstall_runtime(Runtime.COPILOT)
    assert result["operations"] == []
    assert result["warnings"] == ["No installation receipt found"]


def test_uninstall_dry_run_keeps_every_installed_file(
    isolated_homes: dict[str, Path],
) -> None:
    installers.install_runtime(Runtime.CODEX)
    skills, pyz, hook = installers._user_targets(Runtime.CODEX)
    receipt = installers.receipt_path(Runtime.CODEX, "user")
    result = installers.uninstall_runtime(Runtime.CODEX, dry_run=True)
    assert result["operations"]
    assert (skills / "outcome-brief" / "SKILL.md").exists()
    assert pyz.exists()
    assert hook.exists()
    assert receipt.exists()


def test_uninstall_tolerates_already_missing_receipt_owned_files(
    isolated_homes: dict[str, Path],
) -> None:
    installers.install_runtime(Runtime.COPILOT)
    _, pyz, hook = installers._user_targets(Runtime.COPILOT)
    pyz.unlink()
    hook.unlink()
    result = installers.uninstall_runtime(Runtime.COPILOT)
    assert not result["warnings"]
    assert not installers.receipt_path(Runtime.COPILOT, "user").exists()


def test_uninstall_preserves_malformed_merged_hook_with_warning(
    isolated_homes: dict[str, Path],
) -> None:
    installers.install_runtime(Runtime.CLAUDE)
    _, _, hook = installers._user_targets(Runtime.CLAUDE)
    hook.write_text("{broken", encoding="utf-8")
    result = installers.uninstall_runtime(Runtime.CLAUDE)
    assert hook.exists()
    assert any("Preserved unreadable merged file" in item for item in result["warnings"])


def test_uninstall_preserves_skills_shared_by_another_runtime_receipt(
    isolated_homes: dict[str, Path],
) -> None:
    installers.install_runtime(Runtime.CODEX)
    installers.install_runtime(Runtime.CLAUDE)
    shared_skill = (
        isolated_homes["codex"].parent / "codex" / "skills" / "outcome-brief" / "SKILL.md"
    )
    # User runtime homes differ in the test fixture, so model a second receipt
    # referencing the Codex-owned skill exactly as a real shared installation would.
    claude_receipt = installers.receipt_path(Runtime.CLAUDE, "user")
    receipt_value = json.loads(claude_receipt.read_text(encoding="utf-8"))
    receipt_value["files"].append(
        {
            "path": str(shared_skill),
            "sha256": installers._hash_file(shared_skill),
            "kind": "owned",
        }
    )
    claude_receipt.write_text(json.dumps(receipt_value), encoding="utf-8")

    result = installers.uninstall_runtime(Runtime.CODEX)
    assert shared_skill.exists()
    assert any("Preserved shared file" in item for item in result["warnings"])


def test_corrupt_unrelated_receipt_does_not_break_uninstall(
    isolated_homes: dict[str, Path],
) -> None:
    installers.install_runtime(Runtime.CODEX)
    receipts = isolated_homes["state"] / "receipts"
    (receipts / "unrelated.json").write_text("{bad", encoding="utf-8")
    result = installers.uninstall_runtime(Runtime.CODEX)
    assert not any("unrelated" in item for item in result["warnings"])
