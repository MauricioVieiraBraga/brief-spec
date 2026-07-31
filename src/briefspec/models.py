from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any


class Runtime(StrEnum):
    CODEX = "codex"
    CLAUDE = "claude"
    COPILOT = "copilot"


class EventType(StrEnum):
    SESSION_START = "session_start"
    USER_PROMPT = "user_prompt"
    POST_TOOL = "post_tool"
    PRE_COMPACT = "pre_compact"
    AGENT_STOP = "agent_stop"
    ERROR = "error"
    UNKNOWN = "unknown"


class OutcomeStatus(StrEnum):
    DONE = "DONE"
    REVIEW = "REVIEW"
    DECIDE = "DECIDE"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


class CheckpointMode(StrEnum):
    ORIENT = "orient"
    TEACH = "teach"
    SPOKEN = "spoken"


class Policy(StrEnum):
    OFF = "off"
    MANUAL = "manual"
    SUGGEST = "suggest"
    AUTO = "auto"
    ENFORCE = "enforce"


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    kind: str
    label: str
    locator: str
    basis: str = "direct"
    result: str = "info"
    revision: str | None = None
    observed_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value is not None}


@dataclass(frozen=True, slots=True)
class RuntimeEvent:
    runtime: Runtime
    type: EventType
    session_id: str
    occurred_at: datetime
    payload_hash: str
    cwd: Path | None = None
    turn_id: str | None = None
    assistant_text: str | None = None
    transcript_path: Path | None = None
    stop_hook_active: bool = False
    prompt_chars: int = 0
    assistant_chars: int = 0
    tool_calls: int = 0


@dataclass(slots=True)
class SessionState:
    runtime: str
    session_id: str
    started_at: str
    updated_at: str
    turn_count: int = 0
    tool_count: int = 0
    prompt_chars: int = 0
    assistant_chars: int = 0
    pending_checkpoint: bool = False
    pending_mode: str = CheckpointMode.ORIENT.value
    pending_reasons: list[str] = field(default_factory=list)
    outcome_expected: bool = False
    repair_attempted: bool = False
    last_suggested_at: str | None = None
    last_checkpoint_at: str | None = None
    last_checkpoint_turn: int = 0
    recent_event_hashes: list[str] = field(default_factory=list)

    @classmethod
    def new(cls, runtime: Runtime, session_id: str, now: datetime) -> SessionState:
        stamp = now.astimezone(UTC).isoformat()
        return cls(
            runtime=runtime.value,
            session_id=session_id,
            started_at=stamp,
            updated_at=stamp,
        )

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> SessionState:
        allowed = {field.name for field in cls.__dataclass_fields__.values()}
        return cls(**{key: item for key, item in value.items() if key in allowed})

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ValidationResult:
    valid: bool
    kind: str
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "kind": self.kind,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "data": self.data,
        }


@dataclass(frozen=True, slots=True)
class HookDecision:
    action: str = "allow"
    reason: str | None = None
    context: str | None = None
    diagnostics: tuple[str, ...] = ()
