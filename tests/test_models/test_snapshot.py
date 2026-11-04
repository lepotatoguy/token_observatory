import pytest
from pydantic import ValidationError

from backend.models.providers import ProviderUpdate
from backend.models.snapshot import PriceEntry, UsageSnapshot


def test_snapshot_validates_current_export():
    from backend.parsers.claude import ClaudeLog
    from pathlib import Path
    log = ClaudeLog(Path("synthetic.jsonl"))
    log.consume({"type": "assistant", "timestamp": "2026-11-03T12:00:00Z", "message": {
        "id": "synthetic-response", "model": "test-model", "usage": {"input_tokens": 3, "output_tokens": 2}}})
    session = log.export({})
    raw = dict(at=1.0, sessions=[session], sources=[], warnings=[], limits={}, accounting_version=2,
               providers=dict(enabled=["claude"], setup_done=True), live_limits=dict(checked_at=None, errors={}),
               archive=dict(directory="history", saved_at=None, interval_seconds=60, dates=[], error=None),
               limit_control={}, future_snapshot_field="retained")
    validated = UsageSnapshot.model_validate(raw)
    assert validated.sessions[0].totals.total == 5
    assert validated.model_dump()["future_snapshot_field"] == "retained"
    assert UsageSnapshot.model_validate_json(validated.model_dump_json()) == validated


def test_price_values_and_shape():
    assert PriceEntry(match="test", rates=[1., 2., 3., 4., 5.]).rates[0] == 1.
    for rates in ([1., -2., 3., 4., 5.], [1., 2.], [True, 2., 3., 4., 5.]):
        with pytest.raises(ValidationError):
            PriceEntry(match="test", rates=rates)


def test_bundled_price_rows_keep_unreported_components():
    import json
    from pathlib import Path
    rows = json.loads((Path(__file__).resolve().parents[2] / "backend/data/prices.json").read_text())["models"]
    validated = [PriceEntry.model_validate(row) for row in rows]
    assert len(validated) == len(rows)
    assert any(None in row.rates for row in validated)


@pytest.mark.parametrize("payload", [{"enabled": {"codex": "true"}}, {"enabled": {"unknown": True}},
                                     {"ports": {"ollama": {"listen": 65536}}}, {"setup_done": None}])
def test_provider_update_rejects_invalid_settings(payload):
    with pytest.raises(ValidationError):
        ProviderUpdate.model_validate(payload)


def test_provider_update_preserves_partial_changes():
    payload = {"enabled": {"claude": False}, "ports": {"ollama": {"listen": 11436}}}
    assert ProviderUpdate.model_validate(payload).model_dump(exclude_unset=True) == payload
