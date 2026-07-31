from __future__ import annotations

import os
import tomllib
from copy import deepcopy
from pathlib import Path
from typing import Any

DEFAULT_CONFIG: dict[str, dict[str, Any]] = {
    "checkpoint": {
        "policy": "suggest",
        "default_mode": "orient",
        "elapsed_minutes": 12,
        "turns": 8,
        "assistant_chars": 16_000,
        "tool_calls": 12,
        "cooldown_minutes": 6,
        "minimum_turns_after_checkpoint": 2,
    },
    "outcome": {
        "policy": "suggest",
        "one_repair": True,
    },
    "state": {
        "retention_days": 14,
    },
}

_ALLOWED = {
    ("checkpoint", "policy"),
    ("checkpoint", "default_mode"),
    ("checkpoint", "elapsed_minutes"),
    ("checkpoint", "turns"),
    ("checkpoint", "assistant_chars"),
    ("checkpoint", "tool_calls"),
    ("checkpoint", "cooldown_minutes"),
    ("checkpoint", "minimum_turns_after_checkpoint"),
    ("outcome", "policy"),
    ("outcome", "one_repair"),
    ("state", "retention_days"),
}


def briefspec_home() -> Path:
    explicit = os.environ.get("BRIEFSPEC_HOME")
    if explicit:
        return Path(explicit).expanduser()
    xdg = os.environ.get("XDG_STATE_HOME")
    if xdg:
        return Path(xdg).expanduser() / "briefspec"
    return Path.home() / ".local" / "state" / "briefspec"


def _merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for section, values in overlay.items():
        if not isinstance(values, dict):
            continue
        for key, value in values.items():
            if (section, key) in _ALLOWED:
                merged.setdefault(section, {})[key] = value
    return merged


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def load_config(cwd: Path | None = None) -> dict[str, Any]:
    config = _merge(DEFAULT_CONFIG, _read_toml(briefspec_home() / "config.toml"))
    project_path = (cwd or Path.cwd()) / ".briefspec.toml"
    return _merge(config, _read_toml(project_path))


def config_template() -> str:
    return """\
[checkpoint]
policy = "suggest" # off | manual | suggest | auto
default_mode = "orient" # orient | teach | spoken
elapsed_minutes = 12
turns = 8
assistant_chars = 16000
tool_calls = 12
cooldown_minutes = 6
minimum_turns_after_checkpoint = 2

[outcome]
policy = "suggest" # off | suggest | enforce
one_repair = true

[state]
retention_days = 14
"""
