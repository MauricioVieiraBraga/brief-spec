from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema.protocols import Validator
from jsonschema.validators import validator_for
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "schemas"


def _schema_documents() -> dict[str, dict[str, Any]]:
    documents = [
        json.loads(path.read_text(encoding="utf-8")) for path in sorted(SCHEMAS.glob("*.json"))
    ]
    return {document["$id"]: document for document in documents}


def _validator(name: str) -> Validator:
    documents = _schema_documents()
    schema = documents[f"https://briefspec.dev/schemas/{name}.schema.json"]
    registry = Registry().with_resources(
        [
            (identifier, Resource.from_contents(document))
            for identifier, document in documents.items()
        ]
    )
    validator_class = validator_for(schema)
    validator_class.check_schema(schema)
    return validator_class(schema, registry=registry)


def _proof() -> list[dict[str, str]]:
    return [
        {
            "kind": "test",
            "label": "Contract suite",
            "locator": "tests/test_schema_contracts.py",
            "basis": "direct",
            "result": "pass",
        }
    ]


CHECKPOINTS = {
    "orient": {
        "current_state": "The implementation is ready for release verification.",
        "completed": ["Aligned the portable and human contracts."],
        "decisions": ["Keep one bounded presentation model."],
        "open": [],
    },
    "teach": {
        "mental_model": "One contract is rendered differently for each reading need.",
        "why_it_matters": "The schema cannot drift from the visible handoff.",
        "what_changed": ["Mode-specific fields are represented explicitly."],
        "example": "Teach carries a mental model while Orient carries current state.",
        "watch_outs": ["Structural validity is not truth verification."],
    },
    "spoken": {
        "script": "Here is the short spoken rendering of the current session state.",
    },
}


@pytest.mark.parametrize(("mode", "mode_fields"), CHECKPOINTS.items())
def test_checkpoint_schema_represents_every_human_mode(
    mode: str,
    mode_fields: dict[str, Any],
) -> None:
    payload = {
        "schema_version": "1.0",
        "kind": "session-checkpoint",
        "mode": mode,
        "headline": f"{mode.title()} checkpoint",
        "proof": _proof(),
        "next": ["Continue with the release gate."],
        **mode_fields,
    }
    _validator("session-checkpoint").validate(payload)


@pytest.mark.parametrize(
    ("mode", "missing_field"),
    [
        ("orient", "current_state"),
        ("teach", "mental_model"),
        ("spoken", "script"),
    ],
)
def test_checkpoint_schema_requires_mode_specific_fields(
    mode: str,
    missing_field: str,
) -> None:
    payload = {
        "schema_version": "1.0",
        "kind": "session-checkpoint",
        "mode": mode,
        "headline": f"{mode.title()} checkpoint",
        "proof": _proof(),
        "next": ["Continue with the release gate."],
        **CHECKPOINTS[mode],
    }
    del payload[missing_field]
    errors = list(_validator("session-checkpoint").iter_errors(payload))
    assert any(missing_field in error.message for error in errors)
