from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from briefspec.models import CheckpointMode, OutcomeStatus, ValidationResult

OUTCOME_START = "<!-- briefspec:outcome:v1 -->"
CHECKPOINT_PATTERN = re.compile(
    r"<!--\s*briefspec:checkpoint:v1\s+mode=(orient|teach|spoken)\s*-->"
)
END_MARKER = "<!-- /briefspec -->"

_OUTCOME_SECTION_ORDER = (
    "Status",
    "Outcome",
    "Human action",
    "Proof",
    "Gaps",
    "Next",
    "Open",
)

_CHECKPOINT_SECTIONS = {
    CheckpointMode.ORIENT: (
        "Headline",
        "Current state",
        "Completed",
        "Decisions",
        "Proof",
        "Next",
        "Open",
    ),
    CheckpointMode.TEACH: (
        "Headline",
        "Mental model",
        "Why it matters",
        "What changed",
        "Example",
        "Watch-outs",
        "Next",
        "Proof",
    ),
    CheckpointMode.SPOKEN: (
        "Headline",
        "Script",
        "Screen-only proof",
        "Next",
    ),
}


def _bounded_region(text: str, start: str | re.Pattern[str]) -> tuple[str | None, str | None]:
    if isinstance(start, str):
        index = text.find(start)
        marker = start
        mode = None
    else:
        match = start.search(text)
        if not match:
            return None, None
        index = match.start()
        marker = match.group(0)
        mode = match.group(1)
    if index < 0:
        return None, mode
    end = text.find(END_MARKER, index + len(marker))
    if end < 0:
        return None, mode
    return text[index + len(marker) : end].strip(), mode


def _read_sections(region: str, names: Iterable[str]) -> tuple[dict[str, Any], list[str]]:
    lines = region.splitlines()
    names = tuple(names)
    positions: list[tuple[int, str, str]] = []
    for index, line in enumerate(lines):
        stripped = line.strip().removeprefix("**").removesuffix("**").strip()
        for name in names:
            match = re.match(rf"^{re.escape(name)}\s*:\s*(.*)$", stripped, re.IGNORECASE)
            if match:
                positions.append((index, name, match.group(1).strip()))
                break

    errors: list[str] = []
    found_names = [name for _, name, _ in positions]
    missing = [name for name in names if name not in found_names]
    if missing:
        errors.append(f"Missing required field(s): {', '.join(missing)}")

    found_order = [name for name in found_names if name in names]
    expected_order = [name for name in names if name in found_order]
    if found_order != expected_order:
        errors.append("Fields are not in the required order")

    data: dict[str, Any] = {}
    for item_index, (line_index, name, inline) in enumerate(positions):
        next_index = positions[item_index + 1][0] if item_index + 1 < len(positions) else len(lines)
        body_lines = lines[line_index + 1 : next_index]
        if inline:
            data[name] = inline
            continue
        items = [
            line.strip()[2:].strip() for line in body_lines if line.strip().startswith(("- ", "* "))
        ]
        if items:
            data[name] = items
        else:
            data[name] = "\n".join(line.strip() for line in body_lines).strip()
    return data, errors


def _empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, list):
        return not value or all(_empty(item) for item in value)
    return str(value).strip().lower() in {"", "none", "n/a", "not applicable"}


def validate_outcome(text: str) -> ValidationResult:
    region, _ = _bounded_region(text, OUTCOME_START)
    if region is None:
        return ValidationResult(False, "outcome-brief", ("Missing bounded outcome marker",))
    data, errors = _read_sections(region, _OUTCOME_SECTION_ORDER)

    try:
        status = OutcomeStatus(str(data.get("Status", "")).strip().upper())
        data["Status"] = status.value
    except ValueError:
        status = None
        errors.append("Status must be DONE, REVIEW, DECIDE, BLOCKED, or FAILED")

    if _empty(data.get("Outcome")):
        errors.append("Outcome must state what is now true")
    if _empty(data.get("Proof")):
        errors.append("Proof must contain at least one inspectable reference")

    human_action = data.get("Human action")
    gaps = data.get("Gaps")
    next_items = data.get("Next")
    open_items = data.get("Open")

    if status is OutcomeStatus.DONE:
        if not _empty(human_action):
            errors.append("DONE cannot require human action")
        if not _empty(gaps):
            errors.append("DONE cannot contain unresolved gaps")
    if status in {OutcomeStatus.REVIEW, OutcomeStatus.DECIDE, OutcomeStatus.BLOCKED} and _empty(
        human_action
    ):
        errors.append(f"{status.value} requires explicit human action")
    if status in {OutcomeStatus.BLOCKED, OutcomeStatus.FAILED}:
        if _empty(gaps):
            errors.append(f"{status.value} requires an explicit gap")
        if _empty(next_items):
            errors.append(f"{status.value} requires a next action")
    if status is OutcomeStatus.DECIDE and _empty(open_items):
        errors.append("DECIDE requires an open decision")

    for name, limit in (("Proof", 5), ("Next", 3), ("Open", 3)):
        value = data.get(name)
        if isinstance(value, list) and len(value) > limit:
            errors.append(f"{name} supports at most {limit} items")

    warnings: list[str] = []
    outcome = str(data.get("Outcome", ""))
    if len(outcome) > 500:
        warnings.append("Outcome is longer than 500 characters")
    return ValidationResult(not errors, "outcome-brief", tuple(errors), tuple(warnings), data)


def validate_checkpoint(text: str, expected_mode: CheckpointMode | None = None) -> ValidationResult:
    region, raw_mode = _bounded_region(text, CHECKPOINT_PATTERN)
    if region is None or raw_mode is None:
        return ValidationResult(False, "session-checkpoint", ("Missing bounded checkpoint marker",))
    mode = CheckpointMode(raw_mode)
    errors: list[str] = []
    if expected_mode is not None and mode is not expected_mode:
        errors.append(f"Expected {expected_mode.value} mode, found {mode.value}")

    data, section_errors = _read_sections(region, _CHECKPOINT_SECTIONS[mode])
    errors.extend(section_errors)
    data["Mode"] = mode.value

    if _empty(data.get("Headline")):
        errors.append("Headline must orient the reader")
    if _empty(data.get("Next")):
        errors.append("Next must identify the next useful move")
    if _empty(data.get("Proof" if mode is not CheckpointMode.SPOKEN else "Screen-only proof")):
        errors.append("Checkpoint must retain at least one evidence reference")

    warnings: list[str] = []
    if mode is CheckpointMode.SPOKEN:
        script = str(data.get("Script", ""))
        words = len(script.split())
        if words < 80:
            warnings.append("Spoken script is shorter than 80 words")
        if words > 240:
            errors.append("Spoken script must not exceed 240 words")
        if "|" in script or "```" in script:
            errors.append("Spoken script cannot contain tables or code fences")
    return ValidationResult(not errors, "session-checkpoint", tuple(errors), tuple(warnings), data)


def detect_kind(text: str) -> str | None:
    if OUTCOME_START in text:
        return "outcome"
    if CHECKPOINT_PATTERN.search(text):
        return "checkpoint"
    return None
