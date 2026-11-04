from pathlib import Path

import pytest

from backend.services import providers


@pytest.fixture(autouse=True)
def isolate_provider_environment(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.setenv('MINIMAX_DATA_DIR', str(tmp_path / 'minimax'))
    monkeypatch.delenv('MINIMAX_API_KEY', raising=False)
    monkeypatch.delenv('ANTHROPIC_BASE_URL', raising=False)
    monkeypatch.setattr(providers.detect, '__defaults__', (lambda port: False, None))
