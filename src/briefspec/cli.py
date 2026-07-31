from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from briefspec import __version__
from briefspec.adapters import normalize_event
from briefspec.config import briefspec_home, config_template, load_config
from briefspec.diagnostics import doctor_runtime
from briefspec.errors import BriefSpecError, InstallConflict
from briefspec.hooks import emit_diagnostics, process_event, read_hook_payload, render_decision
from briefspec.installers import install_runtime, uninstall_runtime
from briefspec.markdown import detect_kind, validate_checkpoint, validate_outcome
from briefspec.models import CheckpointMode, Runtime
from briefspec.state import atomic_write, list_sessions, prune_sessions, reset_session


def _runtimes(value: str) -> list[Runtime]:
    return list(Runtime) if value == "all" else [Runtime(value)]


def _detect_runtime(payload: dict[str, Any]) -> Runtime:
    explicit = str(payload.get("runtime") or payload.get("provider") or "").lower()
    if explicit in {item.value for item in Runtime}:
        return Runtime(explicit)
    if (
        any(name.startswith("CLAUDE_CODE") for name in os.environ)
        or os.environ.get("CLAUDE_PLUGIN_ROOT")
        and not os.environ.get("CODEX_THREAD_ID")
    ):
        return Runtime.CLAUDE
    if any(name.startswith("COPILOT") for name in os.environ):
        return Runtime.COPILOT
    return Runtime.CODEX


def _read_text(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    return Path(path).read_text(encoding="utf-8")


def _print_result(value: Any, as_json: bool) -> None:
    if as_json:
        print(json.dumps(value, indent=2, sort_keys=True, default=str))
        return
    if isinstance(value, list):
        for item in value:
            _print_result(item, False)
        return
    if isinstance(value, dict) and "operations" in value:
        print(f"{value.get('runtime', 'briefspec')}: {value.get('scope', '')}")
        for operation in value["operations"]:
            print(f"  {operation['action']:12} {operation['path']} — {operation['detail']}")
        for warning in value.get("warnings", []):
            print(f"  WARN         {warning}")
        return
    if isinstance(value, dict) and "checks" in value:
        print(f"{value['runtime']}: {value['status']}")
        for check in value["checks"]:
            print(f"  {check['status']:4} {check['name']}: {check['detail']}")
            if check.get("remediation"):
                print(f"       → {check['remediation']}")
        return
    print(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="briefspec",
        description="Predictable, evidence-backed handoffs for AI coding agents.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    for name in ("install", "uninstall"):
        command = commands.add_parser(name)
        command.add_argument("runtime", choices=[item.value for item in Runtime] + ["all"])
        command.add_argument("--scope", choices=["user", "project"], default="user")
        command.add_argument("--project", type=Path)
        command.add_argument("--dry-run", action="store_true")
        command.add_argument("--json", action="store_true")

    doctor = commands.add_parser("doctor")
    doctor.add_argument(
        "runtime",
        nargs="?",
        choices=[item.value for item in Runtime] + ["all"],
        default="all",
    )
    doctor.add_argument("--scope", choices=["user", "project"], default="user")
    doctor.add_argument("--project", type=Path)
    doctor.add_argument("--probe", action="store_true")
    doctor.add_argument("--json", action="store_true")

    validate = commands.add_parser("validate")
    validate.add_argument("kind", choices=["auto", "outcome", "checkpoint"])
    validate.add_argument("path", nargs="?", default="-")
    validate.add_argument("--mode", choices=[item.value for item in CheckpointMode])
    validate.add_argument("--json", action="store_true")

    hook = commands.add_parser("hook", help=argparse.SUPPRESS)
    hook.add_argument(
        "--provider",
        required=True,
        choices=[item.value for item in Runtime] + ["auto"],
    )
    hook.add_argument("--event")
    hook.add_argument(
        "--output-profile",
        choices=["native", "vscode"],
        default="native",
    )

    config = commands.add_parser("config")
    config_commands = config.add_subparsers(dest="config_command", required=True)
    show = config_commands.add_parser("show")
    show.add_argument("--json", action="store_true")
    init = config_commands.add_parser("init")
    init.add_argument("--scope", choices=["user", "project"], default="user")
    init.add_argument("--project", type=Path)
    init.add_argument("--force", action="store_true")

    state = commands.add_parser("state")
    state_commands = state.add_subparsers(dest="state_command", required=True)
    state_list = state_commands.add_parser("list")
    state_list.add_argument("--json", action="store_true")
    prune = state_commands.add_parser("prune")
    prune.add_argument("--older-than", type=int, metavar="DAYS")
    prune.add_argument("--dry-run", action="store_true")
    reset = state_commands.add_parser("reset")
    reset.add_argument("--runtime", required=True, choices=[item.value for item in Runtime])
    reset.add_argument("--session", required=True)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command in {"install", "uninstall"}:
            handler = install_runtime if args.command == "install" else uninstall_runtime
            results = [
                handler(
                    runtime,
                    scope=args.scope,
                    project=args.project,
                    dry_run=args.dry_run,
                )
                for runtime in _runtimes(args.runtime)
            ]
            _print_result(results if len(results) > 1 else results[0], args.json)
            return 0

        if args.command == "doctor":
            results = [
                doctor_runtime(
                    runtime,
                    scope=args.scope,
                    project=args.project,
                    probe=args.probe,
                )
                for runtime in _runtimes(args.runtime)
            ]
            _print_result(results if len(results) > 1 else results[0], args.json)
            return 1 if any(result["status"] == "FAIL" for result in results) else 0

        if args.command == "validate":
            text = _read_text(args.path)
            kind = detect_kind(text) if args.kind == "auto" else args.kind
            if kind == "outcome":
                result = validate_outcome(text)
            elif kind == "checkpoint":
                mode = CheckpointMode(args.mode) if args.mode else None
                result = validate_checkpoint(text, mode)
            else:
                print("No BriefSpec marker found", file=sys.stderr)
                return 1
            _print_result(result.to_dict(), args.json)
            if not args.json:
                print("VALID" if result.valid else "INVALID")
                for error in result.errors:
                    print(f"  ERROR: {error}")
                for warning in result.warnings:
                    print(f"  WARN: {warning}")
            return 0 if result.valid else 1

        if args.command == "hook":
            try:
                payload = read_hook_payload(sys.stdin)
                runtime = (
                    _detect_runtime(payload) if args.provider == "auto" else Runtime(args.provider)
                )
                event = normalize_event(runtime, payload, args.event)
                decision = process_event(event, payload)
                emit_diagnostics(decision)
                print(
                    json.dumps(
                        render_decision(
                            runtime,
                            event.type,
                            decision,
                            output_profile=args.output_profile,
                        )
                    )
                )
            except Exception as exc:  # host hooks must fail open
                print(f"briefspec: fail-open: {type(exc).__name__}: {exc}", file=sys.stderr)
                print("{}")
            return 0

        if args.command == "config":
            if args.config_command == "show":
                _print_result(load_config(), args.json)
                return 0
            destination = (
                ((args.project or Path.cwd()) / ".briefspec.toml")
                if args.scope == "project"
                else briefspec_home() / "config.toml"
            )
            if destination.exists() and not args.force:
                print(f"Refusing to overwrite existing config: {destination}", file=sys.stderr)
                return 3
            atomic_write(destination, config_template().encode())
            print(destination)
            return 0

        if args.command == "state":
            if args.state_command == "list":
                _print_result(list_sessions(), args.json)
                return 0
            if args.state_command == "prune":
                days = args.older_than
                if days is None:
                    days = int(load_config()["state"]["retention_days"])
                removed = prune_sessions(days, args.dry_run)
                for path in removed:
                    print(path)
                return 0
            found = reset_session(Runtime(args.runtime), args.session)
            return 0 if found else 1
    except InstallConflict as exc:
        print(f"Installation conflict: {exc}", file=sys.stderr)
        return 3
    except (BriefSpecError, OSError, ValueError) as exc:
        print(f"briefspec: {exc}", file=sys.stderr)
        return 1
    return 2
