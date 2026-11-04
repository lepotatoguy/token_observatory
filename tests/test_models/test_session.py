import pytest
from pydantic import ValidationError

from backend.models.session import TokenEvent


def event(**updates):
    return dict(at=1.0, model="synthetic", input=5, cached=3, write=1, output=2, reasoning=1, **updates)


def test_event_round_trip_and_forward_fields():
    raw = event(future_field={"value": 42})
    model = TokenEvent.model_validate(raw)
    assert model.input == 5
    assert model.model_dump()["future_field"] == raw["future_field"]
    assert TokenEvent.model_validate_json(model.model_dump_json()) == model


@pytest.mark.parametrize("field,value", [("input", -1), ("cached", "1"), ("write", True),
                                       ("output", 1.5), ("reasoning", -3), ("at", float("nan"))])
def test_rejects_invalid_values(field, value):
    raw = event()
    raw[field] = value
    with pytest.raises(ValidationError):
        TokenEvent.model_validate(raw)
