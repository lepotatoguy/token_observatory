from pathlib import Path

import pytest

from backend.app import create_app
from backend.config import Config


def test_environment_read_at_construction(monkeypatch, tmp_path):
    monkeypatch.setenv("TOKEN_OBSERVATORY_PORT", "9876")
    monkeypatch.setenv("TOKEN_OBSERVATORY_DATA_DIR", str(tmp_path / "history"))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    monkeypatch.setenv("TOKEN_OBSERVATORY_LIVE_CHECKS", "0")
    monkeypatch.setenv("TOKEN_OBSERVATORY_UPDATE_CHECKS", "0")
    config = Config()
    assert config.PORT == 9876
    assert config.DATA_DIR == tmp_path / "history"
    assert config.CODEX_HOME == tmp_path / "codex"
    assert config.CLAUDE_HOME == tmp_path / "claude"
    assert config.LIVE_CHECKS is config.UPDATE_CHECKS is False
    client = create_app(config).test_client()
    assert client.get("/api/health", base_url="http://127.0.0.1:9876").status_code == 200
    assert client.get("/api/health", base_url="http://127.0.0.1:8766").status_code == 403


def test_defaults(monkeypatch):
    for name in ("TOKEN_OBSERVATORY_PORT", "TOKEN_OBSERVATORY_DATA_DIR", "CODEX_HOME", "CLAUDE_CONFIG_DIR",
                 "TOKEN_OBSERVATORY_LIVE_CHECKS", "TOKEN_OBSERVATORY_UPDATE_CHECKS"):
        monkeypatch.delenv(name, raising=False)
    config = Config()
    assert config.PORT == 8765
    assert config.DATA_DIR.name == "history"
    assert config.CODEX_HOME == Path.home() / ".codex"
    assert config.CLAUDE_HOME == Path.home() / ".claude"
    assert config.LIVE_CHECKS is config.UPDATE_CHECKS is True


@pytest.mark.parametrize("port", [0, -1, 65536])
def test_invalid_port(port):
    with pytest.raises(ValueError):
        Config(PORT=port)
