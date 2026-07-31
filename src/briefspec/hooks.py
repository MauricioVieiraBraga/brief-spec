from __future__ import annotations

import json
import sys
from datetime import UTC
from typing import Any

from briefspec.config import load_config
from briefspec.markdown import validate_checkpoint, validate_outcome
from briefspec.models import (
    CheckpointMode,
    EventType,
    HookDecision,
    Policy,
    Runtime,
    RuntimeEvent,
)
from briefspec.state import load_session, save_session, session_lock
from briefspec.triggers import eligibility_reasons, update_counters

SESSION_CONTEXT = """\
BriefSpec is active. When substantive work ends, use the outcome-brief skill and keep the
fields in its prescribed order. For long or overloaded work, use session-checkpoint in
orient, teach, or spoken mode. Preserve proof and explicit gaps; never infer success."""


def _checkpoint_request(mode: str, reasons: list[str]) -> str:
    because = ", ".join(reasons) if reasons else "an explicit request"
    return (
        f"Before ending this turn, add one valid BriefSpec session checkpoint in {mode} mode. "
        f"It is due because of: {because}. Use the session-checkpoint skill, retain inspectable "
        "proof, and do not replace the requested task result."
    )


def _outcome_request(errors: tuple[str, ...] = ()) -> str:
    detail = f" Fix: {'; '.join(errors)}." if errors else ""
    return (
        "Before ending this turn, close the completed task with one valid BriefSpec Outcome "
        "Brief. Use the outcome-brief skill. Keep Status, Outcome, Human action, Proof, Gaps, "
        f"Next, and Open in that order.{detail}"
    )


def process_event(
    event: RuntimeEvent,
    payload: dict[str, Any],
    config: dict[str, Any] | None = None,
) -> HookDecision:
    effective = config or load_config(event.cwd)
    diagnostics: list[str] = []
    prompt = str(payload.get("prompt") or "")
    try:
        with session_lock(event.runtime, event.session_id):
            state = load_session(event.runtime, event.session_id, event.occurred_at)
            if event.payload_hash in state.recent_event_hashes:
                return HookDecision(diagnostics=("duplicate event ignored",))
            state.recent_event_hashes.append(event.payload_hash)
            state.recent_event_hashes = state.recent_event_hashes[-32:]
            update_counters(state, event, prompt)

            checkpoint_policy = Policy(str(effective["checkpoint"]["policy"]))
            outcome_policy = Policy(str(effective["outcome"]["policy"]))
            if not state.pending_checkpoint:
                state.pending_mode = CheckpointMode(
                    str(effective["checkpoint"]["default_mode"])
                ).value
            if event.type not in {EventType.PRE_COMPACT, EventType.AGENT_STOP}:
                reasons = eligibility_reasons(state, effective, event.occurred_at)
                if reasons and checkpoint_policy not in {Policy.OFF, Policy.MANUAL}:
                    state.pending_checkpoint = True
                    state.pending_reasons = list(dict.fromkeys(state.pending_reasons + reasons))

            decision = HookDecision()
            if event.type is EventType.SESSION_START and (
                checkpoint_policy is not Policy.OFF or outcome_policy is not Policy.OFF
            ):
                decision = HookDecision(context=SESSION_CONTEXT)

            if (
                event.type is EventType.POST_TOOL
                and state.pending_checkpoint
                and checkpoint_policy is Policy.SUGGEST
            ):
                decision = HookDecision(
                    context=(
                        "A BriefSpec checkpoint is eligible. At the next natural boundary, "
                        "offer or include an orient checkpoint without interrupting active "
                        "work."
                    )
                )

            if event.type is EventType.AGENT_STOP:
                assistant = event.assistant_text or ""
                outcome_result = validate_outcome(assistant)
                checkpoint_result = validate_checkpoint(assistant)
                has_outcome = outcome_result.valid
                has_checkpoint = checkpoint_result.valid

                if has_outcome:
                    state.outcome_expected = False
                    if (
                        state.pending_checkpoint
                        and state.pending_mode == CheckpointMode.ORIENT.value
                        and "pre-compact" not in state.pending_reasons
                    ):
                        state.pending_checkpoint = False
                        state.pending_reasons = []
                if has_checkpoint:
                    state.pending_checkpoint = False
                    state.pending_reasons = []
                    state.last_checkpoint_at = event.occurred_at.astimezone(UTC).isoformat()
                    state.last_checkpoint_turn = state.turn_count

                requests: list[str] = []
                if state.outcome_expected and outcome_policy is Policy.ENFORCE and not has_outcome:
                    errors = (
                        outcome_result.errors
                        if "<!-- briefspec:outcome:v1 -->" in assistant
                        else ()
                    )
                    requests.append(_outcome_request(errors))
                if (
                    state.pending_checkpoint
                    and checkpoint_policy is Policy.AUTO
                    and not has_checkpoint
                    and not (
                        has_outcome
                        and state.pending_mode == CheckpointMode.ORIENT.value
                        and "pre-compact" not in state.pending_reasons
                    )
                ):
                    requests.append(_checkpoint_request(state.pending_mode, state.pending_reasons))

                already_active = event.stop_hook_active or state.repair_attempted
                if requests and bool(effective["outcome"]["one_repair"]) and not already_active:
                    state.repair_attempted = True
                    save_session(state)
                    return HookDecision(
                        action="block",
                        reason="\n\n".join(requests),
                        diagnostics=tuple(diagnostics),
                    )
                if requests and already_active:
                    diagnostics.append("repair guard allowed a still-invalid second stop")

            save_session(state)
            return HookDecision(
                action=decision.action,
                reason=decision.reason,
                context=decision.context,
                diagnostics=tuple(diagnostics) or decision.diagnostics,
            )
    except Exception as exc:  # Hooks must fail open.
        return HookDecision(diagnostics=(f"fail-open: {type(exc).__name__}: {exc}",))


def render_decision(
    runtime: Runtime,
    event: EventType,
    decision: HookDecision,
    output_profile: str = "native",
) -> dict[str, Any]:
    if decision.action == "block" and decision.reason:
        result: dict[str, Any] = {"decision": "block", "reason": decision.reason}
        if output_profile == "vscode":
            result["hookSpecificOutput"] = {
                "hookEventName": "Stop",
                "decision": "block",
                "reason": decision.reason,
            }
        return result
    if decision.context:
        if runtime is Runtime.COPILOT:
            result = {"additionalContext": decision.context}
            if output_profile == "vscode":
                result["hookSpecificOutput"] = {
                    "hookEventName": {
                        EventType.SESSION_START: "SessionStart",
                        EventType.POST_TOOL: "PostToolUse",
                        EventType.USER_PROMPT: "UserPromptSubmit",
                    }.get(event, "SessionStart"),
                    "additionalContext": decision.context,
                }
            return result
        event_name = {
            EventType.SESSION_START: "SessionStart",
            EventType.POST_TOOL: "PostToolUse",
            EventType.USER_PROMPT: "UserPromptSubmit",
        }.get(event, "SessionStart")
        return {
            "hookSpecificOutput": {
                "hookEventName": event_name,
                "additionalContext": decision.context,
            }
        }
    return {}


def emit_diagnostics(decision: HookDecision) -> None:
    for diagnostic in decision.diagnostics:
        print(f"briefspec: {diagnostic}", file=sys.stderr)


def read_hook_payload(stream: Any, limit: int = 1024 * 1024) -> dict[str, Any]:
    raw = stream.buffer.read(limit + 1) if hasattr(stream, "buffer") else stream.read(limit + 1)
    if isinstance(raw, str):
        raw = raw.encode()
    if len(raw) > limit:
        raise ValueError("hook payload exceeds 1 MiB")
    value = json.loads(raw or b"{}")
    if not isinstance(value, dict):
        raise ValueError("hook payload must be a JSON object")
    return value
