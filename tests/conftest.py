import json

import pytest

from backend.app import create_app
from backend.config import Config


@pytest.fixture
def app(tmp_path):
    app = create_app(Config(PORT=8766, DATA_DIR=tmp_path / "history", CODEX_HOME=tmp_path / "codex",
                            CLAUDE_HOME=tmp_path / "claude", LIVE_CHECKS=False, UPDATE_CHECKS=False))
    app.config.update(TESTING=True, SERVER_NAME=f"127.0.0.1:{app.config['PORT']}")
    return app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def make_jsonl(tmp_path):
    def write(rows, name="session.jsonl"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        return path

    return write
