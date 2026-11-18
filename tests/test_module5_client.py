import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

ARTIGO = {
    "titulo": "Engenharia de software",
    "link": "https://example.org/estudo?lingua=pt",
    "fonte": "Exemplo",
    "idioma": "pt",
    "data_publicacao": None,
}


@pytest.fixture
def module5_http():
    state = {
        "code": 200,
        "body": json.dumps({"artigos": [ARTIGO], "categoria": "geral", "total": 1}).encode(),
        "headers": {"Content-Type": "application/json"},
        "requests": [],
        "session_requests": [],
        "session_ok": True,
        "owner_ids": {},
        "on_curation": lambda: None,
    }

    class Handler(BaseHTTPRequestHandler):
        def reply(self, code, body, headers):
            self.send_response(code)
            for name, value in headers.items():
                self.send_header(name, value)
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def handle_curation(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            state["requests"].append((self.command, self.path, dict(self.headers), body))
            state["on_curation"]()
            self.reply(state["code"], state["body"], state["headers"])

        def do_GET(self):  # noqa: N802
            if self.path == "/auth/me":
                token = self.headers.get("Authorization")
                state["session_requests"].append(token)
                user = state["owner_ids"].get(token)
                self.reply(
                    200 if user and state["session_ok"] else 401,
                    json.dumps({"id": user, "is_active": True}).encode(),
                    {"Content-Type": "application/json"},
                )
            else:
                self.handle_curation()

        def do_POST(self):  # noqa: N802
            self.handle_curation()

        def log_message(self, *args):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}", state
        finally:
            server.shutdown()
            thread.join()


def test_provider_feed_caps_public_articles_and_removes_provider_metadata(module5_http):
    from projects_service.module5_client import Module5Client

    url, state = module5_http
    state["body"] = json.dumps(
        {
            "artigos": [{**ARTIGO, "publisher_internal": "private"}] * 51,
            "total": 999,
            "categoria": "geral",
            "fontes_consultadas": ["Exemplo"],
            "fontes_indisponiveis": ["Fonte temporariamente fora"],
            "repositorio": "private",
        }
    ).encode()
    result = Module5Client(url).feed().model_dump()
    assert result == {
        "enabled": True,
        "artigos": [ARTIGO] * 50,
        "total": 51,
        "categoria": "geral",
        "fontes_consultadas": ["Exemplo"],
        "fontes_indisponiveis": ["Fonte temporariamente fora"],
        "truncated": True,
    }


@pytest.mark.parametrize(
    "payload",
    [
        {"artigos": [{**ARTIGO, "link": "//example.org/unsafe"}]},
        {"artigos": [{**ARTIGO, "link": "https://name:pw@example.org/unsafe"}]},
        {"artigos": [{**ARTIGO, "link": "https://example.org/unsafe\npath"}]},
        {"artigos": [{**ARTIGO, "link": "https://example.org:bogus/unsafe"}]},
        {"artigos": [{**ARTIGO, "link": "https://example.org/ " + "x" * 2050}]},
        {"artigos": [{**ARTIGO, "link": "javascript:alert(1)"}]},
        {"artigos": [{**ARTIGO, "titulo": "x" * 501}]},
        {"artigos": [{**ARTIGO, "fonte": True}]},
        {"artigos": [ARTIGO] * 1001},
        {"artigos": [ARTIGO], "fontes_consultadas": "wrong"},
        {"artigos": [ARTIGO], "fontes_indisponiveis": ["Exemplo"] * 51},
        {"artigos": [ARTIGO], "extra": [{"number": float("nan")}]},
    ],
)
def test_provider_rejects_unbounded_or_malformed_data(module5_http, payload):
    from projects_service.access_domain import AccessError
    from projects_service.module5_client import Module5Client

    url, state = module5_http
    state["body"] = json.dumps(payload).encode()
    with pytest.raises(AccessError) as error:
        Module5Client(url).query("synthetic-token", "Pergunta")
    assert error.value.status == 503
    assert len(state["requests"]) == 1


@pytest.mark.parametrize(
    ("code", "body", "expected_status"),
    [
        (401, b"upstream-private", 401),
        (403, b"upstream-private", 403),
        (302, b"upstream-private", 503),
        (429, b"upstream-private", 503),
        (500, b"upstream-private", 503),
        (200, b"<html>private</html>", 503),
        (200, b'{"artigos": [], "metadata": 1e999}', 503),
        (200, b'{"artigos": [], "extra": "' + b"x" * (1024 * 1024) + b'"}', 503),
    ],
    ids=[
        "unauthorized",
        "forbidden",
        "redirect",
        "rate-limit",
        "error",
        "html",
        "overflow",
        "size",
    ],
)
def test_query_sanitizes_provider_failure_and_never_follows_or_retries(
    module5_http, code, body, expected_status
):
    from projects_service.access_domain import AccessError
    from projects_service.module5_client import Module5Client

    url, state = module5_http
    state.update(code=code, body=body)
    state["headers"]["Location"] = url + "/untrusted"
    with pytest.raises(AccessError) as error:
        Module5Client(url).query("synthetic-token", "Pergunta")
    assert error.value.status == expected_status
    assert "upstream-private" not in error.value.detail
    assert [path for _, path, _, _ in state["requests"]] == ["/consultas"]


def test_query_deadline_covers_waiting_for_response_headers(module5_http):
    from projects_service.access_domain import AccessError
    from projects_service.module5_client import Module5Client

    url, state = module5_http
    state["on_curation"] = lambda: time.sleep(1.2)
    start = time.monotonic()
    with pytest.raises(AccessError) as error:
        Module5Client(url, deadline_seconds=0.25).query("synthetic-token", "Pergunta")
    assert error.value.status == 503
    assert time.monotonic() - start < 1
    assert len(state["requests"]) == 1
