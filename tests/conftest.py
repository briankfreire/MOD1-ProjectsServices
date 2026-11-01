import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from projects_service.config import Settings


@pytest.fixture
def issuer():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    public.update(kid="test-key", alg="RS256", use="sig")
    state = {"payload": {"keys": [public]}, "status": 200, "requests": 0}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            state["requests"] += 1
            self.send_response(state["status"])
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(state["payload"]).encode())

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    owner = uuid4()

    def token(*, sub=None, updates=None, omit=(), headers=None, signing_key=None):
        now = int(time.time())
        claims = dict(
            sub=str(sub or owner),
            iss="mod1-auth-local",
            aud="engenharia-software-api",
            iat=now,
            exp=now + 1800,
            jti=str(uuid4()),
        )
        claims.update(updates or {})
        for name in omit:
            claims.pop(name)
        return jwt.encode(
            claims,
            signing_key or key,
            algorithm="RS256",
            headers={"kid": "test-key", "typ": "JWT", **(headers or {})},
        )

    yield {
        "key": key,
        "state": state,
        "token": token,
        "owner": owner,
        "settings": Settings(
            database_url="sqlite:///:memory:",
            auth_session_check_enabled=False,
            jwks_url=f"http://127.0.0.1:{server.server_port}/jwks",
            _env_file=None,
        ),
    }
    server.shutdown()
    server.server_close()
    thread.join()


@pytest.fixture
def advanced_http_client(issuer):
    """Isolated HTTP fixture with explicit controlled external dependency seams."""
    from fastapi.testclient import TestClient

    from projects_service.app import create_app
    from projects_service.database import init_schema

    app = create_app(issuer["settings"])
    init_schema(app.state.engine, "projects")
    app.state.identity.active = lambda token, target: True
    app.state.identity.profile = lambda token, target: None
    app.state.backlog.items_snapshot = lambda token, project_id: []
    with TestClient(app) as client:
        yield client
