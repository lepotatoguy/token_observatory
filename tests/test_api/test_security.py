import pytest

from backend.middleware.security import SECURITY_HEADERS


@pytest.mark.parametrize("host", ["example.com:8766", "127.0.0.1.evil:8766", "127.0.0.1:8765",
                                 "localhost", "[::1]:8766", "localhost:8766@evil", ""])
def test_rejects_foreign_hosts(client, host):
    assert client.get("/api/health", headers={"Host": host}).status_code == 403


@pytest.mark.parametrize("host", ["127.0.0.1:8766", "localhost:8766"])
def test_accepts_loopback_hosts(client, host):
    assert client.get("/api/health", headers={"Host": host}).status_code == 200


@pytest.mark.parametrize("method", ["GET", "POST", "OPTIONS"])
@pytest.mark.parametrize("headers", [
    {"Sec-Fetch-Site": "cross-site"},
    {"Origin": "https://example.com"},
    {"Origin": "null"},
    {"Origin": "http://localhost:8765"},
    {"Origin": "http://user@localhost:8766"},
    {"Origin": "http://localhost:8766/path"},
    {"Origin": "http://localhost:8766?query"},
    {"Origin": "http://[invalid"},
    {"Origin": "https://localhost:8766"},
    {"Origin": ""},
])
def test_blocks_browser_cross_site_requests(client, method, headers):
    assert client.open("/api/health", method=method, headers=headers).status_code == 403


@pytest.mark.parametrize("origin", ["http://127.0.0.1:8766", "http://localhost:8766"])
def test_accepts_local_origins(client, origin):
    assert client.get("/api/health", headers={"Origin": origin}).status_code == 200


@pytest.mark.parametrize("path,headers,status", [
    ("/api/missing", {}, 404),
    ("/api/health", {"Host": "evil:8766"}, 403),
])
def test_security_headers_on_errors(client, path, headers, status):
    response = client.get(path, headers=headers)
    assert response.status_code == status
    for name, value in SECURITY_HEADERS.items():
        assert response.headers[name] == value


@pytest.fixture
def mutation_client(app):
    @app.post("/api/test-body")
    def body():
        from flask import jsonify, request
        return jsonify(request.get_json())

    return app.test_client()


def test_body_limit(mutation_client):
    at_limit = '{"text":"' + "x" * 1013 + '"}'
    assert len(at_limit) == 1024
    assert mutation_client.post("/api/test-body", data=at_limit, content_type="application/json").status_code == 200
    response = mutation_client.post("/api/test-body", data=at_limit + " ", content_type="application/json")
    assert response.status_code == 413
    assert response.headers["Cache-Control"] == "no-store"


def test_json_required(mutation_client):
    assert mutation_client.post("/api/test-body", data="{}").status_code == 415
    assert mutation_client.post("/api/test-body", data="{", content_type="application/json").status_code == 400


def test_streamed_body_limit(mutation_client):
    from io import BytesIO
    response = mutation_client.post("/api/test-body", content_type="application/json", environ_overrides={
        "wsgi.input": BytesIO(b'{"text":"' + b"x" * 1024 + b'"}'),
        "wsgi.input_terminated": True,
        "CONTENT_LENGTH": "",
    })
    assert response.status_code == 413
