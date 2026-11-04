"""Apply the loopback and browser-origin boundary before Flask routing."""

from urllib.parse import urlsplit

from werkzeug.wrappers import Response


SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": (
        "default-src 'self'; style-src 'self' 'unsafe-inline'; "
        "script-src 'self'; connect-src 'self'; frame-ancestors 'none'"
    ),
}


class SecurityMiddleware:
    def __init__(self, app, port: int):
        self.app = app
        self.hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    def allowed_origin(self, origin: str) -> bool:
        try:
            parsed = urlsplit(origin)
            return (
                parsed.scheme == "http"
                and parsed.netloc in self.hosts
                and not parsed.path
                and not parsed.query
                and not parsed.fragment
                and origin == f"http://{parsed.netloc}"
            )
        except ValueError:
            return False

    def __call__(self, environ, start_response):
        def secure_response(status, headers, exc_info=None):
            headers = [(key, value) for key, value in headers if key.lower() not in header_names]
            headers.extend(SECURITY_HEADERS.items())
            return start_response(status, headers, exc_info)

        header_names = {name.lower() for name in SECURITY_HEADERS}
        origin = environ.get("HTTP_ORIGIN")
        if (
            environ.get("HTTP_HOST") not in self.hosts
            or environ.get("HTTP_SEC_FETCH_SITE") == "cross-site"
            or (origin is not None and not self.allowed_origin(origin))
        ):
            return Response("Forbidden\n", status=403, mimetype="text/plain")(environ, secure_response)
        return self.app(environ, secure_response)
