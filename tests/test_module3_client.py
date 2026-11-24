import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import pytest

ARTIFACT = {
    "id": 41,
    "project_id": 7,
    "name": "Requisitos.md",
    "artifact_type": "MARKDOWN",
    "version": 1,
    "created_at": "2026-11-24T00:00:00Z",
    "file_path": "/private/file.md",
}
VERSION = {
    "id": 81,
    "artifact_id": 41,
    "version_number": 1,
    "created_at": "2026-11-24T00:00:00Z",
    "file_path": "/private/file.md",
}


@pytest.fixture
def module3_http():
    state = {
        "requests": [],
        "tokens": {},
        "session_ok": True,
        "on_request": lambda: None,
        "override": None,
        "route_overrides": {},
        "delay": 0,
    }
    routes = {
        "/projects/": [{"id": 7, "name": "Projeto de artefatos", "description": None}],
        "/projects/7/artifacts/": [ARTIFACT],
        "/projects/7/artifacts/41/versions": [VERSION],
        "/projects/7/artifacts/41/download": b"# Requisitos\n",
    }

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            if self.path == "/auth/me":
                user = state["tokens"].get(self.headers.get("Authorization"))
                code = 200 if user and state["session_ok"] else 401
                body, headers = json.dumps({"id": user, "is_active": True}).encode(), {}
            else:
                state["requests"].append((self.command, self.path, dict(self.headers)))
                state["on_request"]()
                if state["delay"]:
                    time.sleep(state["delay"])
                value = routes.get(urlsplit(self.path).path)
                code = 200 if value is not None else 404
                body = value if isinstance(value, bytes) else json.dumps(value).encode()
                headers = {
                    "Content-Type": "application/octet-stream"
                    if isinstance(value, bytes)
                    else "application/json"
                }
                if state["override"]:
                    code, body, headers = state["override"]
                if urlsplit(self.path).path in state["route_overrides"]:
                    code, body, headers = state["route_overrides"][urlsplit(self.path).path]
            self.send_response(code)
            for key, value in {"Content-Type": "application/json", **headers}.items():
                self.send_header(key, value)
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *args):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(
            target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
        )
        thread.start()
        yield f"http://127.0.0.1:{server.server_port}", state
        server.shutdown()
        thread.join()


def test_catalog_artifacts_and_versions_are_sanitized_gets_without_identity(module3_http):
    from projects_service.module3_client import Module3Client

    base, state = module3_http
    client = Module3Client(base)
    assert client.catalog().items[0].id == 7
    page = client.artifacts(7, search="Requisitos & plano", artifact_type="MARKDOWN")
    assert page.module3_project_id == 7
    assert "file_path" not in page.items[0].model_dump()
    versions = client.versions(7, 41)
    assert versions.items[0].id == 81
    assert "file_path" not in versions.items[0].model_dump()
    assert all(
        method == "GET" and not headers.get("Authorization") and not headers.get("Cookie")
        for method, _, headers in state["requests"]
    )
    assert "search=Requisitos+%26+plano" in state["requests"][1][1]


def test_download_verifies_artifact_membership_and_returns_attachment_bytes(module3_http):
    from projects_service.access_domain import AccessError
    from projects_service.module3_client import Module3Client

    base, state = module3_http
    client = Module3Client(base)
    result = client.download(7, 41)
    assert result.content == b"# Requisitos\n"
    assert result.filename == "artifact-41.md"
    before = len(state["requests"])
    with pytest.raises(AccessError) as error:
        client.download(7, 999)
    assert error.value.status == 404
    assert len(state["requests"]) == before + 1
    assert not any("/999/download" in path for _, path, _ in state["requests"])


@pytest.mark.parametrize(
    "code,body,headers",
    [
        (302, b"", {"Location": "http://127.0.0.1:1/private"}),
        (403, b"private internal diagnostics", {}),
        (429, b"quota", {}),
        (200, b"not json", {}),
        (200, b"{}", {"Content-Type": "application/json"}),
        (200, b"[true]", {"Content-Type": "application/json"}),
        (200, b" " * (1024 * 1024 + 1), {"Content-Type": "application/json"}),
        (200, b'[{"id":7,"name":"\\ud800"}]', {"Content-Type": "application/json"}),
    ],
    ids=[
        "redirect",
        "forbidden",
        "rate-limit",
        "invalid-json",
        "wrong-shape",
        "wrong-item",
        "oversize",
        "invalid-unicode",
    ],
)
def test_invalid_refused_redirect_or_oversize_catalog_is_unavailable(
    module3_http, code, body, headers
):
    from projects_service.access_domain import AccessError
    from projects_service.module3_client import Module3Client

    base, state = module3_http
    state["override"] = code, body, headers
    with pytest.raises(AccessError) as error:
        Module3Client(base).catalog()
    assert error.value.status == 503
    assert len(state["requests"]) == 1


def test_total_deadline_cancels_slow_provider(module3_http):
    from projects_service.access_domain import AccessError
    from projects_service.module3_client import Module3Client

    base, state = module3_http
    state["delay"] = 0.3
    start = time.monotonic()
    with pytest.raises(AccessError) as error:
        Module3Client(base, deadline_seconds=0.05).catalog()
    assert error.value.status == 503
    assert time.monotonic() - start < 1


@pytest.mark.parametrize(
    "base", ["https://example.com", "http://localhost", "http://127.0.0.1:1/x"]
)
def test_untrusted_base_is_rejected(base):
    from projects_service.module3_client import Module3Client

    with pytest.raises(ValueError):
        Module3Client(base)


def test_foreign_project_or_version_metadata_is_never_returned(module3_http):
    from projects_service.access_domain import AccessError
    from projects_service.module3_client import Module3Client

    base, state = module3_http
    client = Module3Client(base)
    state["route_overrides"]["/projects/7/artifacts/"] = (
        200,
        json.dumps([{**ARTIFACT, "project_id": 8}]).encode(),
        {"Content-Type": "application/json"},
    )
    with pytest.raises(AccessError) as error:
        client.artifacts(7)
    assert error.value.status == 503
    state["route_overrides"].clear()
    state["route_overrides"]["/projects/7/artifacts/41/versions"] = (
        200,
        json.dumps([{**VERSION, "artifact_id": 99}]).encode(),
        {"Content-Type": "application/json"},
    )
    with pytest.raises(AccessError) as error:
        client.versions(7, 41)
    assert error.value.status == 503


def test_catalog_limits_display_without_hiding_truncation(module3_http):
    from projects_service.module3_client import Module3Client

    base, state = module3_http
    rows = [{"id": i + 1, "name": "Projeto"} for i in range(101)]
    state["override"] = 200, json.dumps(rows).encode(), {"Content-Type": "application/json"}
    result = Module3Client(base).catalog()
    assert result.total == 101 and result.truncated and len(result.items) == 100


def test_download_rejects_oversize_before_accepting_file(module3_http):
    from projects_service.access_domain import AccessError
    from projects_service.module3_client import Module3Client

    base, state = module3_http
    state["route_overrides"]["/projects/7/artifacts/41/download"] = (
        200,
        b"file",
        {"Content-Type": "application/octet-stream", "Content-Length": "10485761"},
    )
    with pytest.raises(AccessError) as error:
        Module3Client(base).download(7, 41)
    assert error.value.status == 503
