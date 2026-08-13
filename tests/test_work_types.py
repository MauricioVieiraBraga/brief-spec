from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from briefspec import cli
from briefspec.delivery import load_delivery, new_delivery, render_markdown, validate_delivery
from briefspec.hooks import process_event
from briefspec.models import EventType, Runtime, RuntimeEvent, WorkType
from briefspec.work_types import (
    MAX_CLASSIFICATION_CHARS,
    classify_task,
    normalize_subject,
    type_profile,
    types_document,
)


def _corpus() -> list[tuple[str, str]]:
    templates = {
        "general": "What is the meaning of ordinary term {index} in one sentence?",
        "exploration": "Explore codebase module {index} and map its entry points and flow.",
        "review": "Review pull request #{index} and audit its merge risk.",
        "implementation": "Implement feature {index} and add tests for the resulting behavior.",
        "debugging": "Debug failing bug {index} and identify its root cause and traceback.",
        "planning": "Create a plan with milestones and release gates for feature {index}.",
        "research": "Research the latest market changes using web sources for tool {index}.",
        "operations": "Handle production incident SEV1-{index}, recovery, and rollback.",
    }
    return [
        (work_type, template.format(index=index))
        for work_type, template in templates.items()
        for index in range(1, 21)
    ]


def _f1(expected: list[str], actual: list[str], label: str) -> float:
    true_positive = sum(
        expected_value == label and actual_value == label
        for expected_value, actual_value in zip(expected, actual, strict=True)
    )
    false_positive = sum(
        expected_value != label and actual_value == label
        for expected_value, actual_value in zip(expected, actual, strict=True)
    )
    false_negative = sum(
        expected_value == label and actual_value != label
        for expected_value, actual_value in zip(expected, actual, strict=True)
    )
    denominator = 2 * true_positive + false_positive + false_negative
    return 1.0 if denominator == 0 else (2 * true_positive) / denominator


def test_labelled_160_prompt_corpus_meets_release_thresholds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1786492800")
    corpus = _corpus()
    assert len(corpus) == 160
    expected = [work_type for work_type, _ in corpus]
    actual = [classify_task(prompt).work_type for _, prompt in corpus]
    scores = {work_type.value: _f1(expected, actual, work_type.value) for work_type in WorkType}
    assert sum(scores.values()) / len(scores) >= 0.95, scores
    assert min(scores.values()) >= 0.90, scores
    assert Counter(expected) == Counter({work_type.value: 20 for work_type in WorkType})


@pytest.mark.parametrize("work_type", list(WorkType))
def test_explicit_overrides_are_always_authoritative(work_type: WorkType) -> None:
    result = classify_task(
        "Review this pull request, debug its failure, then create a release plan.",
        explicit_type=work_type.value,
    )
    assert result.work_type == work_type.value
    assert result.origin == "explicit"
    assert result.confidence == "high"


def test_host_context_precedes_intent_and_ambiguous_intent_falls_back() -> None:
    host = classify_task(
        "Implement this change.",
        host_context={"work_type": "review", "subject": "pull-request"},
    )
    assert (host.work_type, host.subject, host.origin) == (
        "review",
        "pull-request",
        "host",
    )
    native_review = classify_task(
        "Please inspect this change.",
        host_context={"pull_request_url": "https://example.invalid/pull/42"},
    )
    assert (native_review.work_type, native_review.subject, native_review.origin) == (
        "review",
        "pull-request",
        "host",
    )
    ambiguous = classify_task("Review and research this item for me.")
    assert (ambiguous.work_type, ambiguous.confidence, ambiguous.origin) == (
        "general",
        "low",
        "fallback",
    )


def test_classification_is_bounded_private_and_deterministic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1786492800")
    prompt = "Explore the codebase and map its entry points. SECRET_TOKEN=do-not-store"
    first = classify_task(prompt)
    second = classify_task(prompt)
    assert first.to_dict() == second.to_dict()
    assert "SECRET_TOKEN" not in json.dumps(first.to_dict())
    ignored_tail = "What is one plus one? " + ("x" * MAX_CLASSIFICATION_CHARS) + " review PR #9"
    assert classify_task(ignored_tail).work_type == "general"


def test_subjects_are_open_normalized_slugs_and_builtin_vocabulary_is_stable() -> None:
    assert normalize_subject("Customer Success / Handoff") == "customer-success-handoff"
    document = types_document()
    assert len(document["types"]) == 8
    assert document["custom_primary_types"] is False
    assert "pull-request" in document["subjects"]
    assert "security" in document["subjects"]


def _event(
    event_type: EventType,
    *,
    session: str,
    prompt: str = "",
    minute: int = 0,
) -> tuple[RuntimeEvent, dict[str, Any]]:
    payload = {"prompt": prompt, "event": event_type.value, "nonce": minute}
    return (
        RuntimeEvent(
            runtime=Runtime.CODEX,
            type=event_type,
            session_id=session,
            occurred_at=datetime(2026, 8, 12, 12, minute, tzinfo=UTC),
            payload_hash=f"{session}-{minute}-{event_type.value}",
            prompt_chars=len(prompt),
        ),
        payload,
    )


def test_task_classification_is_sticky_until_a_clear_pivot(
    isolated_homes: dict[str, Path],
) -> None:
    first_event, first_payload = _event(
        EventType.USER_PROMPT,
        session="sticky",
        prompt="Explore this codebase and map its entry points.",
    )
    first = process_event(first_event, first_payload)
    assert "exploration + codebase" in (first.context or "")

    second_event, second_payload = _event(
        EventType.USER_PROMPT,
        session="sticky",
        prompt="Review pull request #42 for merge risk.",
        minute=1,
    )
    second = process_event(second_event, second_payload)
    assert "exploration + codebase" in (second.context or "")

    override_event, override_payload = _event(
        EventType.USER_PROMPT,
        session="sticky",
        prompt="Brief-Spec work type: planning for this task.",
        minute=2,
    )
    override = process_event(override_event, override_payload)
    assert "planning + general" in (override.context or "")

    pivot_event, pivot_payload = _event(
        EventType.USER_PROMPT,
        session="sticky",
        prompt="New task: now review pull request #42 for merge risk.",
        minute=3,
    )
    pivot = process_event(pivot_event, pivot_payload)
    assert "review + pull-request" in (pivot.context or "")


@pytest.mark.parametrize("work_type", list(WorkType))
@pytest.mark.parametrize("presentation", ["outcome", "orient", "teach", "spoken"])
def test_typed_semantic_matrix_round_trips_one_canonical_object(
    work_type: WorkType,
    presentation: str,
    request: pytest.FixtureRequest,
) -> None:
    if presentation == "outcome":
        text = request.getfixturevalue("outcome_text")(
            proof=("[direct/pass] `tests/test_contract.py` — direct evidence",)
        )
    else:
        text = request.getfixturevalue("checkpoint_text")(presentation)
    legacy, _warnings = load_delivery(text, created_at="2026-08-12T12:00:00Z")
    profile = type_profile(work_type.value)
    classification = classify_task(
        "Explicit canonical fixture",
        explicit_type=work_type.value,
        subject="general",
        now=datetime(2026, 8, 12, 12, tzinfo=UTC),
    ).to_dict()
    explanation = {
        "profile_version": "1.0",
        "sections": [
            {
                "id": section.section_id,
                "label": section.label,
                "content": f"Canonical content for {section.label}.",
            }
            for section in profile.sections
        ],
    }
    delivery = new_delivery(
        legacy["brief"],
        harness="test",
        created_at="2026-08-12T12:00:00Z",
        classification=classification,
        explanation=explanation,
    )
    assert validate_delivery(delivery).valid
    markdown = render_markdown(delivery)
    loaded, warnings = load_delivery(
        markdown,
        harness="test",
        created_at="2026-08-12T12:00:00Z",
    )
    assert not warnings
    assert loaded["brief"] == delivery["brief"]
    assert loaded["explanation"] == delivery["explanation"]
    for field in (
        "work_type",
        "subject",
        "confidence",
        "origin",
        "classified_at",
        "profile_version",
    ):
        assert loaded["classification"][field] == delivery["classification"][field]


def test_classify_stdin_does_not_persist_input(
    isolated_homes: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from io import StringIO

    monkeypatch.setattr("sys.stdin", StringIO("Review pull request #42 for merge risk."))
    assert cli.main(["classify", "-", "--json"]) == 0
    value = json.loads(capsys.readouterr().out)
    assert value["work_type"] == "review"
    assert not isolated_homes["state"].exists()
