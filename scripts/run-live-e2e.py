#!/usr/bin/env python3
"""Run bounded, read-only Brief-Spec acceptance scenarios in live host CLIs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from briefspec.bundle import build_delivery_bundle, deliver_bundle
from briefspec.config import briefspec_home
from briefspec.delivery import export_core, load_delivery
from briefspec.models import Runtime, VerificationLevel
from briefspec.state import list_sessions, session_path
from briefspec.verification import verify_target
from briefspec.work_types import type_profile

MODES = ("outcome", "orient", "teach", "spoken")
WORK_TYPES = (
    "general",
    "exploration",
    "review",
    "implementation",
    "debugging",
    "planning",
    "research",
    "operations",
)
HOSTS = ("codex", "claude", "omp", "grok", "kimi")
CORE_HOSTS = ("codex", "claude")
SECONDARY_HOSTS = ("omp", "grok", "kimi")

_TASKS = {
    "general": (
        "general",
        "Brief-Spec is requested. Read evidence.txt and answer what one fact the file establishes, "
        "why the answer is trustworthy, and the next useful action. Do not change any file.",
    ),
    "exploration": (
        "codebase",
        "Explore and map how this codebase repository is structured. Trace its entry points and "
        "flow using evidence.txt, identify unknowns, and name the next probe. Do not change files.",
    ),
    "review": (
        "pull-request",
        "Review pull request #42 using evidence.txt. Inspect its scope and correctness, give a "
        "verdict, identify findings and risk, and recommend the next move. Do not change files.",
    ),
    "implementation": (
        "feature",
        "Implement and add the requested feature handoff by inspecting evidence.txt, but this is a "
        "read-only acceptance fixture so do not change files. Explain intent, resulting behavior, "
        "verification, and tradeoffs.",
    ),
    "debugging": (
        "bug",
        "Debug the failing bug described by evidence.txt. Diagnose the root cause, explain the fix "
        "and regression protection, and retain residual risk. Do not change files.",
    ),
    "planning": (
        "architecture",
        "Plan the architecture implementation using evidence.txt. Define phases, decisions, "
        "acceptance criteria, and release gates. Do not change files.",
    ),
    "research": (
        "dependency",
        "Research the latest dependency tools represented by evidence.txt. Compare and evaluate "
        "the evidence quality, limitations, and recommendation without network access or changes.",
    ),
    "operations": (
        "incident",
        "Assess the incident outage described by evidence.txt. Explain impact, current state, "
        "recovery actions, rollback posture, and follow-up. Do not change files.",
    ),
}

_PRESENTATION = {
    "general": "outcome",
    "exploration": "orient",
    "review": "teach",
    "implementation": "spoken",
    "debugging": "outcome",
    "planning": "orient",
    "research": "teach",
    "operations": "spoken",
}

_SECONDARY_TYPES = ("review", "exploration", "implementation", "debugging")

_BOUNDARY = {
    "outcome": """Inside the typed region, end with one unchanged Outcome Brief block. Its status
is DONE; Human action, Gaps, Next, and Open are None; Proof is exactly one direct passing file
reference to `evidence.txt`. This is a terminal Outcome boundary; do not use a checkpoint.""",
    "orient": """Inside the typed region, end with one unchanged Orient checkpoint block with all
required fields in order and exactly one direct passing Proof reference to `evidence.txt`. This is
an explicitly requested checkpoint boundary; do not use an Outcome Brief.""",
    "teach": """Inside the typed region, end with one unchanged Teach checkpoint block with all
required fields in order and exactly one direct passing Proof reference to `evidence.txt`. This is
an explicitly requested checkpoint boundary; do not use an Outcome Brief.""",
    "spoken": """Inside the typed region, end with one unchanged Spoken checkpoint block with all
required fields in order. Its Script is 100 to 140 natural spoken words and never speaks a path.
Screen-only proof is exactly one direct passing file reference to `evidence.txt`. This is an
explicitly requested checkpoint boundary; do not use an Outcome Brief.""",
}


def _prompt(host: str, work_type: str, mode: str) -> str:
    subject, task = _TASKS[work_type]
    labels = ", ".join(section.label for section in type_profile(work_type).sections)
    confidence = "low" if work_type == "general" else "high"
    origin = "fallback" if work_type == "general" else "inferred"
    routing = (
        "Use the installed native Brief-Spec skill's deterministic local classification. The "
        "lifecycle hook records the event, but this harness does not treat passive hook stdout as "
        "model context."
        if host == "grok"
        else "Follow the classification supplied by the installed Brief-Spec lifecycle hook."
    )
    metadata_source = "classifier's" if host == "grok" else "hook's"
    return f"""{task}

{routing} Do not call a network service or another model to classify. Return only one complete
`brief-spec:typed:v1`
region. Copy the {metadata_source} work type, subject, confidence, origin, and classified_at into
the outer marker; it should classify as {work_type} + {subject}. Use every profile heading once
in this exact order: {labels}. The deterministic local classification has
confidence={confidence} and origin={origin}. Put concise, non-empty content under every heading.
{_BOUNDARY[mode]}
The literal final line is `<!-- /brief-spec -->`. Do not include raw transcript or authentication
data. Do not use network access, URLs, web search, or external connectors; `evidence.txt` is the
complete fixture. Its complete contents are: "Brief-Spec live acceptance fixture: canonical
delivery is ready for verification." If this harness has no file-read tool, use that supplied
content as the fixture while still citing `evidence.txt` as the screen-only proof. Do not call a
tool to reread content that has already been supplied here."""


def _run(
    command: list[str],
    *,
    cwd: Path,
    timeout: int = 300,
    env_overrides: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    environment.update(env_overrides or {})
    return subprocess.run(
        command,
        cwd=cwd,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
        env=environment,
    )


def _redact(value: str) -> str:
    value = re.sub(r"\bsk-[A-Za-z0-9_-]{12,}\b", "[REDACTED_API_KEY]", value)
    return re.sub(r"(?i)(authorization[\"']?\s*[:=]\s*[\"']?bearer\s+)\S+", r"\1[REDACTED]", value)


def _stderr_evidence(value: str) -> str:
    redacted = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", _redact(value))
    selected = [
        line
        for line in redacted.splitlines()
        if any(token in line.lower() for token in ("brief-spec", "error", "max turns"))
    ][-20:]
    record = {
        "sha256": hashlib.sha256(redacted.encode()).hexdigest(),
        "line_count": len(redacted.splitlines()),
        "selected": selected,
    }
    return json.dumps(record, indent=2, sort_keys=True) + "\n"


def _sanitized_events(stream: str) -> str:
    """Retain acceptance evidence without signatures, connector inventories, or credentials."""
    retained: list[str] = []
    for line in stream.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        event_type = value.get("type")
        subtype = value.get("subtype")
        record: dict[str, Any] = {"type": event_type}
        if subtype:
            record["subtype"] = subtype
        for name in (
            "thread_id",
            "session_id",
            "hook_name",
            "hook_event",
            "outcome",
            "exit_code",
            "terminal_reason",
            "total_cost_usd",
            "is_error",
        ):
            if value.get(name) is not None:
                record[name] = value[name]
        message = value.get("message")
        if isinstance(message, dict):
            if isinstance(message.get("model"), str):
                record["model"] = message["model"]
            content = message.get("content", [])
            texts = [
                item.get("text", "")
                for item in content
                if isinstance(item, dict) and item.get("type") == "text"
            ]
            if texts:
                assistant = "\n".join(texts)
                record["assistant_chars"] = len(assistant)
                record["assistant_sha256"] = hashlib.sha256(assistant.encode()).hexdigest()
            tools = [
                item.get("name", "")
                for item in content
                if isinstance(item, dict) and item.get("type") == "tool_use"
            ]
            if tools:
                record["tool_uses"] = tools
        item = value.get("item")
        if isinstance(item, dict):
            record["item_type"] = item.get("type")
            if item.get("type") == "agent_message":
                assistant = str(item.get("text", ""))
                record["assistant_chars"] = len(assistant)
                record["assistant_sha256"] = hashlib.sha256(assistant.encode()).hexdigest()
            if item.get("type") == "command_execution":
                command = str(item.get("command", ""))
                record["command_sha256"] = hashlib.sha256(command.encode()).hexdigest()
                record["command_status"] = item.get("status", "")
        retained.append(json.dumps(record, sort_keys=True))
    return "\n".join(retained) + ("\n" if retained else "")


def _extract_claude(stream: str) -> str:
    result_text = ""
    assistant_text = ""
    for line in stream.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if value.get("type") == "result" and isinstance(value.get("result"), str):
            result_text = value["result"]
        message = value.get("message")
        if isinstance(message, dict) and message.get("role") == "assistant":
            content = message.get("content", [])
            pieces = [
                item.get("text", "")
                for item in content
                if isinstance(item, dict) and item.get("type") == "text"
            ]
            if pieces:
                assistant_text = "\n".join(pieces)
    return result_text or assistant_text


def _all_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for child in value.values() for text in _all_strings(child)]
    if isinstance(value, list):
        return [text for child in value for text in _all_strings(child)]
    return []


def _extract_typed(stream: str) -> str:
    candidates: list[str] = []
    for line in stream.splitlines():
        try:
            candidates.extend(_all_strings(json.loads(line)))
        except json.JSONDecodeError:
            continue
    candidates.extend(_all_strings(_json_document(stream)))
    bounded = [
        value.strip()
        for value in candidates
        if value.strip().startswith("<!-- brief-spec:typed:v1")
        and value.strip().endswith("<!-- /brief-spec -->")
        and ("<!-- briefspec:outcome:v1 -->" in value or "<!-- briefspec:checkpoint:v1" in value)
    ]
    if bounded:
        return max(bounded, key=len)
    marker = stream.find("<!-- brief-spec:typed:v1")
    end = stream.find("<!-- /brief-spec -->", marker)
    if marker >= 0 and end >= 0:
        return stream[marker : end + len("<!-- /brief-spec -->")]
    return ""


def _extract_grok(stream: str) -> str:
    """Reassemble Grok's streamed text deltas without selecting skill examples."""
    groups: list[str] = []
    current: list[str] = []
    for line in stream.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if value.get("type") == "text" and isinstance(value.get("data"), str):
            current.append(value["data"])
            continue
        if value.get("type") in {"usage", "tool_call", "end"} and current:
            groups.append("".join(current))
            current = []
    if current:
        groups.append("".join(current))
    bounded = [
        group.strip()
        for group in groups
        if group.strip().startswith("<!-- brief-spec:typed:v1")
        and group.strip().endswith("<!-- /brief-spec -->")
        and ("<!-- briefspec:outcome:v1 -->" in group or "<!-- briefspec:checkpoint:v1" in group)
    ]
    return bounded[-1] if bounded else _extract_typed(stream)


def _json_document(stream: str) -> Any:
    try:
        return json.loads(stream)
    except json.JSONDecodeError:
        return None


def _session_refs(stream: str) -> list[str]:
    found: set[str] = set()
    for line in stream.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        stack: list[Any] = [value]
        while stack:
            current = stack.pop()
            if isinstance(current, dict):
                for key, child in current.items():
                    if key in {"session_id", "thread_id", "sessionId", "threadId"} and child:
                        found.add(str(child))
                    else:
                        stack.append(child)
            elif isinstance(current, list):
                stack.extend(current)
    return sorted(found)


def _stream_values(stream: str) -> tuple[list[str], float | None]:
    models: set[str] = set()
    cost: float | None = None
    for line in stream.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        model = value.get("model")
        if isinstance(model, str) and model:
            models.add(model)
        message = value.get("message")
        if isinstance(message, dict) and isinstance(message.get("model"), str):
            models.add(message["model"])
        if isinstance(value.get("total_cost_usd"), (int, float)):
            cost = float(value["total_cost_usd"])
        model_usage = value.get("modelUsage")
        if isinstance(model_usage, dict):
            models.update(str(name) for name in model_usage if name)
    return sorted(models), cost


def _state_snapshot(host: str) -> dict[str, str]:
    return {
        str(value.get("session_id")): str(value.get("updated_at"))
        for value in list_sessions()
        if value.get("runtime") == host and value.get("session_id")
    }


def _host_command(host: str, prompt: str, final_path: Path) -> list[str]:
    if host == "codex":
        return [
            "codex",
            "exec",
            "--ephemeral",
            "--json",
            "--color",
            "never",
            "--sandbox",
            "read-only",
            "--dangerously-bypass-hook-trust",
            "--output-last-message",
            str(final_path),
            prompt,
        ]
    if host == "claude":
        return [
            "claude",
            "-p",
            "--output-format",
            "stream-json",
            "--verbose",
            "--include-hook-events",
            "--no-session-persistence",
            "--permission-mode",
            "plan",
            "--tools",
            "Read",
            "--max-budget-usd",
            "1",
            "--model",
            "haiku",
            "--strict-mcp-config",
            '--mcp-config={"mcpServers":{}}',
            prompt,
        ]
    if host == "omp":
        return [
            "omp",
            "-p",
            "--mode",
            "json",
            "--no-session",
            "--tools",
            "read",
            "--max-time",
            "5m",
            prompt,
        ]
    if host == "grok":
        return [
            "grok",
            "-p",
            prompt,
            "--output-format",
            "streaming-json",
            "--permission-mode",
            "plan",
            "--model",
            "grok-4.5",
            "--system-prompt-override",
            (
                "Follow the user prompt exactly. The complete Brief-Spec type profile and boundary "
                "contract are supplied in the prompt. If native policy requires skill loading, "
                "read required files one at a time. Do not browse or modify files; return only the "
                "requested bounded Markdown."
            ),
            "--tools",
            "read_file",
            "--disable-web-search",
            "--no-subagents",
            "--no-memory",
            "--max-turns",
            "8",
        ]
    return ["kimi", "-p", prompt, "--output-format", "stream-json"]


def _host_version(host: str, workspace: Path) -> str:
    command = [host, "--version"]
    result = _run(command, cwd=workspace, timeout=30)
    return (result.stdout or result.stderr).strip().splitlines()[0]


def _host_environment(host: str, workspace: Path) -> dict[str, str]:
    if host != "grok":
        return {}
    isolated_home = workspace / ".host-home"
    exclude = workspace / ".git" / "info" / "exclude"
    exclusions = exclude.read_text(encoding="utf-8") if exclude.is_file() else ""
    if ".host-home/" not in exclusions.splitlines():
        exclude.write_text(exclusions.rstrip() + "\n.host-home/\n", encoding="utf-8")
    grok_home = isolated_home / ".grok"
    source_home = Path.home() / ".grok"
    grok_home.mkdir(parents=True, mode=0o700)
    for skill in ("brief-spec", "outcome-brief", "session-checkpoint"):
        shutil.copytree(source_home / "skills" / skill, grok_home / "skills" / skill)
    shutil.copytree(source_home / "brief-spec", grok_home / "brief-spec")
    (grok_home / "hooks").mkdir(parents=True)
    shutil.copy2(source_home / "hooks" / "brief-spec.json", grok_home / "hooks")
    (grok_home / "config.toml").write_text(
        """[compat.claude]
skills = false
rules = false
agents = false
mcps = false
hooks = false
sessions = false

[compat.cursor]
skills = false
rules = false
agents = false
mcps = false
hooks = false
sessions = false

[marketplace]
official_marketplace_auto_installed = false

[workflows]
enabled = false

[memory]
enabled = false
""",
        encoding="utf-8",
    )
    return {
        "HOME": str(isolated_home),
        "GROK_HOME": str(grok_home),
        "GROK_AUTH_PATH": str(source_home / "auth.json"),
        "BRIEF_SPEC_HOME": str(briefspec_home()),
    }


def _prepare_repository(root: Path) -> None:
    (root / "evidence.txt").write_text(
        "Brief-Spec live acceptance fixture: canonical delivery is ready for verification.\n",
        encoding="utf-8",
    )
    commands = (
        ["git", "init", "-q"],
        ["git", "config", "user.email", "briefspec@example.invalid"],
        ["git", "config", "user.name", "Brief-Spec E2E"],
        ["git", "add", "evidence.txt"],
        ["git", "commit", "-qm", "test: add acceptance fixture"],
    )
    for command in commands:
        result = _run(command, cwd=root, timeout=30)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or f"failed: {' '.join(command)}")


def run_scenario(
    host: str,
    work_type: str,
    mode: str,
    output_root: Path,
) -> dict[str, Any]:
    expected_subject, _ = _TASKS[work_type]
    scenario = output_root / host / f"{work_type}-{mode}"
    scenario.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f"brief-spec-{host}-{work_type}-{mode}-") as temporary:
        workspace = Path(temporary)
        _prepare_repository(workspace)
        final_path = scenario / "final.md"
        state_before = _state_snapshot(host)
        result = _run(
            _host_command(host, _prompt(host, work_type, mode), final_path),
            cwd=workspace,
            env_overrides=_host_environment(host, workspace),
        )
        stream = _redact(result.stdout)
        error = _redact(result.stderr)
        (scenario / "events.jsonl").write_text(_sanitized_events(stream), encoding="utf-8")
        (scenario / "stderr.json").write_text(_stderr_evidence(error), encoding="utf-8")
        if result.returncode != 0:
            error_tail = "\n".join(error.splitlines()[-20:])
            raise RuntimeError(
                f"{host}/{work_type}/{mode} failed: {error_tail or result.returncode}"
            )
        if host == "claude":
            final_path.write_text(_extract_claude(stream), encoding="utf-8")
        elif host == "grok":
            final_path.write_text(_extract_grok(stream), encoding="utf-8")
        elif host != "codex":
            final_path.write_text(_extract_typed(stream), encoding="utf-8")
        if not final_path.is_file():
            raise RuntimeError(f"{host}/{work_type}/{mode} produced no final output")
        final = final_path.read_text(encoding="utf-8")
        if not final.strip():
            raise RuntimeError(f"{host}/{work_type}/{mode} produced an empty final output")
        session_refs = _session_refs(stream)
        models, cost_usd = _stream_values(stream)
        delivery, warnings = load_delivery(
            final,
            source_path=final_path,
            runtime=host,
            session_ref=(session_refs or [None])[0],
            host_version=_host_version(host, workspace),
            source_revision=_run(
                ["git", "rev-parse", "HEAD"], cwd=workspace, timeout=30
            ).stdout.strip(),
            model=(models or [None])[0],
            created_at="2026-08-11T12:00:00Z",
        )
        formats = ["markdown", "json", "html"]
        if mode == "spoken":
            formats.extend(("spoken-text", "ssml"))
        exports = scenario / "exports"
        export_core(delivery, formats, exports, force=True)
        bundle_path = scenario / "delivery.zip"
        build_delivery_bundle(delivery, bundle_path, formats=formats, force=True)
        rendered = verify_target(
            bundle_path,
            level=VerificationLevel.RENDERED,
            workspace=workspace,
        )
        resolved = verify_target(
            exports / "brief.json",
            level=VerificationLevel.RESOLVED,
            workspace=workspace,
        )
        delivered = deliver_bundle(bundle_path, scenario / "delivered", force=True)
        delivered_result = verify_target(
            Path(delivered["receipt"]),
            level=VerificationLevel.DELIVERED,
            workspace=workspace,
        )
        worktree = _run(["git", "status", "--porcelain"], cwd=workspace, timeout=30).stdout
        strict = _run(
            ["brief-spec", "validate", str(final_path), "--strict", "--json"],
            cwd=workspace,
            timeout=30,
        )
        expected_kind = "outcome-brief" if mode == "outcome" else "session-checkpoint"
        actual_brief = delivery.get("brief", {})
        mode_matches = actual_brief.get("kind") == expected_kind and (
            mode == "outcome" or actual_brief.get("mode") == mode
        )
        classification = delivery.get("classification", {})
        explanation = delivery.get("explanation", {})
        expected_sections = [section.section_id for section in type_profile(work_type).sections]
        classification_matches = (
            classification.get("work_type") == work_type
            and classification.get("subject") == expected_subject
            and classification.get("origin")
            == ("fallback" if work_type == "general" else "inferred")
            and classification.get("confidence") == ("low" if work_type == "general" else "high")
            and [item.get("id") for item in explanation.get("sections", [])] == expected_sections
        )
        state_after = _state_snapshot(host)
        changed_sessions = sorted(
            session_id
            for session_id, updated_at in state_after.items()
            if state_before.get(session_id) != updated_at
        )
        session_refs = sorted(set(session_refs) | set(changed_sessions))
        hook_state_paths = [session_path(Runtime(host), ref) for ref in session_refs]
        hook_observed = "briefspec" in stream.lower() or any(
            path.is_file() for path in hook_state_paths
        )
        passed = (
            strict.returncode == 0
            and rendered["status"] == "PASS"
            and resolved["status"] in {"PASS", "WARN"}
            and delivered_result["status"] == "PASS"
            and not worktree.strip()
            and not warnings
            and mode_matches
            and classification_matches
            and hook_observed
            and (cost_usd is None or cost_usd <= 1)
        )
        record = {
            "host": host,
            "work_type": work_type,
            "subject": expected_subject,
            "mode": mode,
            "status": "PASS" if passed else "FAIL",
            "host_returncode": result.returncode,
            "session_refs": session_refs,
            "models": models,
            "cost_usd": cost_usd,
            "hook_observed": hook_observed,
            "hook_state_paths": [str(path) for path in hook_state_paths if path.is_file()],
            "mode_matches": mode_matches,
            "classification_matches": classification_matches,
            "classification": classification,
            "strict_validation": {
                "status": "PASS" if strict.returncode == 0 else "FAIL",
                "returncode": strict.returncode,
                "output": _redact(strict.stdout or strict.stderr),
            },
            "warnings": warnings,
            "rendered": rendered,
            "resolved": resolved,
            "delivered": delivered_result,
            "worktree_clean": not worktree.strip(),
        }
        (scenario / "result.json").write_text(
            json.dumps(record, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return record


def collect_results(output: Path) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for path in sorted(output.glob("*/*/result.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            results.append(value)
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", choices=[*HOSTS, "all"], default="all")
    parser.add_argument("--type", choices=[*WORK_TYPES, "all"], default="all")
    parser.add_argument("--mode", choices=[*MODES, "matrix", "all"], default="matrix")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--collect-only", action="store_true")
    args = parser.parse_args()
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output = (args.output or Path(".briefspec") / "live-e2e" / stamp).resolve()
    output.mkdir(parents=True, exist_ok=True)
    hosts = HOSTS if args.host == "all" else (args.host,)
    expected: list[tuple[str, str, str]] = []
    for host in hosts:
        if args.type == "all":
            types = WORK_TYPES if host in CORE_HOSTS else _SECONDARY_TYPES
        else:
            types = (args.type,)
        for work_type in types:
            modes = MODES if args.mode == "all" else (_PRESENTATION[work_type],)
            if args.mode not in {"all", "matrix"}:
                modes = (args.mode,)
            expected.extend((host, work_type, mode) for mode in modes)
    failures: list[dict[str, str]] = []
    if not args.collect_only:
        for host, work_type, mode in expected:
            try:
                run_scenario(host, work_type, mode, output)
            except Exception as exc:  # retain every scenario result in one release evidence set
                failure = {
                    "host": host,
                    "work_type": work_type,
                    "mode": mode,
                    "error": _redact(str(exc)),
                }
                failures.append(failure)
                print(json.dumps(failure, sort_keys=True), file=os.sys.stderr)
    results = collect_results(output)
    summary = {
        "schema_version": 2,
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "output": str(output),
        "expected_scenarios": len(expected),
        "completed_scenarios": len(results),
        "execution_failures": failures,
        "results": results,
    }
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    incomplete = not args.collect_only and len(results) != len(expected)
    return (
        1 if failures or incomplete or any(result["status"] != "PASS" for result in results) else 0
    )


if __name__ == "__main__":
    raise SystemExit(main())
