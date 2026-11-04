from backend.app import create_app
from backend.config import Config
from backend.middleware.security import SECURITY_HEADERS


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json == {"app": "token-observatory", "version": 2}
    for name, value in SECURITY_HEADERS.items():
        assert response.headers[name] == value


def test_factory_has_isolated_store(app):
    other = create_app(Config(DATA_DIR=app.config["DATA_DIR"], CODEX_HOME=app.config["CODEX_HOME"], CLAUDE_HOME=app.config["CLAUDE_HOME"], LIVE_CHECKS=False, UPDATE_CHECKS=False))
    assert app.extensions is not other.extensions
    assert app.extensions["store"] is not other.extensions["store"]
    assert other.extensions["runtime"].threads == []
