from __future__ import annotations

from typing import Any

from briefspec.adapters import claude, codex, copilot
from briefspec.models import Runtime, RuntimeEvent


def normalize_event(
    runtime: Runtime,
    payload: dict[str, Any],
    event_name: str | None = None,
) -> RuntimeEvent:
    adapters = {
        Runtime.CODEX: codex.normalize,
        Runtime.CLAUDE: claude.normalize,
        Runtime.COPILOT: copilot.normalize,
    }
    return adapters[runtime](payload, event_name)
