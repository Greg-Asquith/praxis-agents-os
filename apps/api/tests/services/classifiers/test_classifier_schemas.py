"""Validation tests for workspace classifier contracts."""

import pytest
from pydantic import ValidationError

from services.classifiers.schemas import ClassifierCreateRequest, ClassifierUpdateRequest


def _payload(**overrides):
    payload = {
        "name": "complaint_triage",
        "display_name": "Complaint triage",
        "description": "Route customer messages.",
        "labels": [
            {"label": " Complaint ", "description": "Needs service recovery."},
            {"label": "Other", "description": ""},
        ],
    }
    payload.update(overrides)
    return payload


def test_classifier_create_normalizes_operator_authored_fields() -> None:
    request = ClassifierCreateRequest.model_validate(_payload())

    assert request.labels[0].label == "Complaint"
    assert request.labels[1].description is None
    assert request.model_provider is None
    assert request.model is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("name", "Complaint-Triage"),
        ("name", "_complaint"),
        ("labels", [{"label": "same"}, {"label": " same "}]),
        ("labels", [{"label": "only"}]),
    ],
)
def test_classifier_create_rejects_invalid_names_and_label_sets(field, value) -> None:
    with pytest.raises(ValidationError):
        ClassifierCreateRequest.model_validate(_payload(**{field: value}))


def test_classifier_model_override_requires_catalog_valid_pair() -> None:
    with pytest.raises(ValidationError):
        ClassifierCreateRequest.model_validate(_payload(model_provider="openai"))

    with pytest.raises(ValidationError):
        ClassifierCreateRequest.model_validate(
            _payload(model_provider="openai", model="not-a-model")
        )

    request = ClassifierCreateRequest.model_validate(
        _payload(model_provider="openai", model="gpt-5.6-luna")
    )
    assert request.model_provider == "openai"
    assert request.model == "gpt-5.6-luna"


def test_classifier_update_requires_both_model_fields_even_when_clearing() -> None:
    cleared = ClassifierUpdateRequest.model_validate({"model_provider": None, "model": None})
    assert cleared.model_provider is None
    assert cleared.model is None

    with pytest.raises(ValidationError, match="must be supplied together"):
        ClassifierUpdateRequest.model_validate({"model_provider": None})
