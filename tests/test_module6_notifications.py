"""Real SQL outbox and HTTP boundary, using synthetic data only."""

import importlib
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from projects_service.config import Settings
from projects_service.database import create_database_engine, init_schema

NOW = datetime(2026, 11, 15, tzinfo=UTC)
PROJECT = UUID("11111111-1111-4111-8111-111111111111")
EVENT = UUID("22222222-2222-4222-8222-222222222222")
KEY = "synthetic-test-key"


@pytest.mark.parametrize("enqueue_on_sleep", [None, 29], ids=["idle", "activity-resets-heartbeat"])
def test_continuous_worker_bounds_count_queries_without_delaying_delivery(
    m6_engine, monkeypatch, capsys, enqueue_on_sleep
):
    import json
    from types import SimpleNamespace

    from sqlalchemy import event

    cli = worker_cli()
    clock = {"seconds": 0, "sleeps": 0}
    counted_at = []
    claims = []
    received = []

    def trace(connection, cursor, statement, parameters, context, executemany):
        if "GROUP BY" in statement:
            counted_at.append(clock["seconds"])
        elif statement.lstrip().startswith("SELECT") and "module6_notification_outbox" in statement:
            claims.append(clock["seconds"])

    event.listen(m6_engine, "before_cursor_execute", trace)

    def sleep(seconds):
        assert seconds == 10
        assert m6_engine.pool.checkedout() == 0
        clock["sleeps"] += 1
        if clock["sleeps"] == 61:
            raise KeyboardInterrupt
        clock["seconds"] += seconds
        if clock["sleeps"] == enqueue_on_sleep:
            enqueue(m6_engine)

    def receive(request):
        received.append(clock["seconds"])
        return receiver_reply(request)

    adapter = sender(receive)
    monkeypatch.setattr(
        cli,
        "Settings",
        lambda: Settings(
            _env_file=None,
            database_url=str(m6_engine.url),
            module6_enabled=True,
            module6_key=KEY,
            module6_source="backlog",
        ),
    )
    monkeypatch.setattr(cli, "create_database_engine", lambda settings: m6_engine)
    monkeypatch.setattr(cli, "Module6Client", lambda *args: adapter)
    monkeypatch.setattr(
        cli, "time", SimpleNamespace(monotonic=lambda: clock["seconds"], sleep=sleep)
    )
    try:
        assert cli.main(["run"]) == 0
    finally:
        event.remove(m6_engine, "before_cursor_execute", trace)
    reports = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert counted_at == ([0, 300, 600] if enqueue_on_sleep is None else [0, 290, 590])
    assert len(reports) == 3
    assert [report["attempted"] for report in reports] == (
        [0, 0, 0] if enqueue_on_sleep is None else [0, 1, 0]
    )
    assert len(claims) == (61 if enqueue_on_sleep is None else 62)
    assert received == ([] if enqueue_on_sleep is None else [290])
    if enqueue_on_sleep is not None:
        assert record(m6_engine).status == "delivered"
        assert record(m6_engine).attempts == 1


def test_one_shot_dispatch_reports_empty_queue(m6_engine, monkeypatch, capsys):
    import json

    cli = worker_cli()
    monkeypatch.setattr(
        cli,
        "Settings",
        lambda: Settings(
            _env_file=None,
            database_url=str(m6_engine.url),
            module6_enabled=True,
            module6_key=KEY,
            module6_source="backlog",
        ),
    )
    monkeypatch.setattr(cli, "create_database_engine", lambda settings: m6_engine)
    assert cli.main(["dispatch"]) == 0
    assert json.loads(capsys.readouterr().out) == {"attempted": 0, "states": {}}


def modules():
    try:
        return tuple(
            importlib.import_module("projects_service." + name)
            for name in (
                "notifications_domain",
                "notification_repository",
                "notification_delivery",
                "module6_client",
            )
        )
    except ImportError as error:
        pytest.fail(f"Module 6 delivery has not been implemented: {error}")


@pytest.fixture
def m6_engine(tmp_path):
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'm6.db'}",
        module6_enabled=True,
        module6_key=KEY,
        module6_source="backlog",
    )
    engine = create_database_engine(settings)
    init_schema(engine, settings.database_schema)
    yield engine
    engine.dispose()


def payload():
    return {
        "event_id": "mod1:projects:" + str(EVENT),
        "scope": "project",
        "project_id": str(PROJECT),
        "source": "backlog",
        "type": "project.created",
        "title": "Aviso sintético",
        "body": "Evento de teste local.",
        "priority": "medium",
        "link": None,
    }


def enqueue(engine):
    _, repository, _, _ = modules()
    with Session(engine) as session:
        repository.enqueue(session, payload(), NOW)
        session.commit()


def record(engine):
    model = importlib.import_module("projects_service.models").NotificationDeliveryRecord
    with Session(engine) as session:
        return session.scalar(select(model))


def receiver_reply(request):
    return httpx.Response(
        200,
        json={
            "id": "receiver-id",
            "event_id": payload()["event_id"],
            "project_id": str(PROJECT),
            "scope": "project",
            "source": "backlog",
            "type": "project.created",
            "title": "Aviso sintético",
            "body": "Evento de teste local.",
            "priority": "medium",
            "relevance_score": 0.5,
            "reason": "test",
            "classified_by": "rules",
            "created_at": NOW.isoformat(),
        },
    )


def sender(handler):
    _, _, _, adapter = modules()
    return adapter.Module6Client(
        "http://127.0.0.1:9999/api/integrations/notifications",
        KEY,
        transport=httpx.MockTransport(handler),
    )


def test_event_mapping_emits_only_minimal_project_payload():
    domain, _, _, _ = modules()
    data = {"item_id": str(uuid4()), "title": "Entrega", "diff": {}, "password": "private"}
    result = domain.build_notification(EVENT, PROJECT, "project.created", data, "backlog")
    assert result["event_id"] == "mod1:projects:" + str(EVENT)
    assert result["type"] == "project.created"
    assert result["scope"] == "project" and result["project_id"] == str(PROJECT)
    assert result["link"] is None
    assert "private" not in str(result) and "password" not in str(result)
    assert (
        domain.build_notification(EVENT, PROJECT, "access.invitation.created", data, "backlog")
        is None
    )
    assert domain.build_notification(EVENT, PROJECT, "reorder", data, "backlog") is None


def test_enqueue_rolls_back_with_business_transaction(m6_engine):
    _, repository, _, _ = modules()
    with Session(m6_engine) as session:
        repository.enqueue(session, payload(), NOW)
        session.flush()
        session.rollback()
    assert record(m6_engine) is None


def test_disabled_capture_needs_no_delivery_table(tmp_path):
    _, repository, _, _ = modules()
    settings = Settings(_env_file=None, database_url=f"sqlite:///{tmp_path / 'disabled.db'}")
    engine = create_database_engine(settings)
    with Session(engine) as session:
        repository.enqueue(session, payload(), NOW)
        session.commit()
    engine.dispose()


def test_claim_is_exclusive_and_does_not_hold_transaction_during_http(m6_engine):
    _, repository, delivery, _ = modules()
    enqueue(m6_engine)
    first = repository.NotificationOutbox(m6_engine)
    other = repository.NotificationOutbox(m6_engine)
    claim = first.claim(NOW)
    assert claim is not None and other.claim(NOW) is None
    assert first.finish(claim, delivery.Outcome("delivered"), NOW)
    assert record(m6_engine).status == "delivered"
    assert other.claim(NOW) is None


def test_lease_expiry_is_uncertain_and_stale_ack_cannot_overwrite(m6_engine):
    _, repository, delivery, _ = modules()
    enqueue(m6_engine)
    outbox = repository.NotificationOutbox(m6_engine)
    claim = outbox.claim(NOW)
    assert outbox.claim(NOW + timedelta(seconds=61)) is None
    assert record(m6_engine).status == "uncertain"
    assert not outbox.finish(claim, delivery.Outcome("delivered"), NOW + timedelta(seconds=62))
    assert record(m6_engine).status == "uncertain"


def test_dispatch_uses_private_header_and_preserves_payload(m6_engine):
    _, repository, delivery, _ = modules()
    enqueue(m6_engine)

    def receive(request):
        import json

        assert request.headers["X-Integration-Key"] == KEY
        assert "authorization" not in request.headers
        assert json.loads(request.content) == payload()
        # An independent writer can commit while HTTP is in flight.
        with m6_engine.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE if not exists receiver_probe (id integer)")
            connection.exec_driver_sql("INSERT INTO receiver_probe VALUES (1)")
        return receiver_reply(request)

    assert (
        delivery.dispatch(
            repository.NotificationOutbox(m6_engine), sender(receive), limit=10, clock=lambda: NOW
        )
        == 1
    )
    assert record(m6_engine).status == "delivered"
    assert record(m6_engine).attempts == 1
    assert (
        delivery.dispatch(
            repository.NotificationOutbox(m6_engine), sender(receive), limit=10, clock=lambda: NOW
        )
        == 0
    )


@pytest.mark.parametrize(
    "code,want",
    [
        (401, "blocked"),
        (403, "blocked"),
        (422, "failed"),
        (302, "failed"),
        (429, "blocked"),
        (500, "uncertain"),
        (503, "uncertain"),
        (201, "uncertain"),
    ],
)
def test_rejected_or_ambiguous_posts_are_not_automatically_repeated(m6_engine, code, want):
    _, repository, delivery, _ = modules()
    enqueue(m6_engine)
    adapter = sender(
        lambda request: httpx.Response(
            code, headers={"Location": "https://evil.invalid"}, text="private-body"
        )
    )
    outbox = repository.NotificationOutbox(m6_engine)
    delivery.dispatch(outbox, adapter, limit=10, clock=lambda: NOW)
    row = record(m6_engine)
    assert row.status == want and row.last_http_status == code
    assert "private-body" not in str(row.last_error)
    assert outbox.claim(NOW + timedelta(days=1)) is None


@pytest.mark.parametrize(
    "kind,want",
    [
        (httpx.ConnectError, "pending"),
        (httpx.ConnectTimeout, "pending"),
        (httpx.ReadTimeout, "uncertain"),
        (httpx.WriteTimeout, "uncertain"),
        (httpx.RemoteProtocolError, "uncertain"),
    ],
)
def test_transport_failures_distinguish_not_sent_from_unknown(m6_engine, kind, want):
    _, repository, delivery, _ = modules()
    enqueue(m6_engine)

    def fail(request):
        raise kind("sensitive upstream text", request=request)

    outbox = repository.NotificationOutbox(m6_engine)
    delivery.dispatch(outbox, sender(fail), limit=10, clock=lambda: NOW)
    assert record(m6_engine).status == want
    assert "sensitive" not in str(record(m6_engine).last_error)
    assert outbox.claim(NOW) is None


def test_connection_retries_have_backoff_and_finite_budget(m6_engine):
    _, repository, delivery, _ = modules()
    enqueue(m6_engine)

    def fail(request):
        raise httpx.ConnectError("offline", request=request)

    outbox = repository.NotificationOutbox(m6_engine)
    for attempt in range(5):
        now = NOW + timedelta(days=attempt)
        assert delivery.dispatch(outbox, sender(fail), limit=100, clock=lambda: now) == 1
    assert record(m6_engine).status == "failed"
    assert record(m6_engine).attempts == 5
    assert outbox.claim(NOW + timedelta(days=10)) is None


@pytest.mark.parametrize("body", [{}, {"id": "x", "event_id": "another-event"}])
def test_malformed_200_ack_is_uncertain(m6_engine, body):
    _, repository, delivery, _ = modules()
    enqueue(m6_engine)
    delivery.dispatch(
        repository.NotificationOutbox(m6_engine),
        sender(lambda r: httpx.Response(200, json=body)),
        limit=1,
        clock=lambda: NOW,
    )
    assert record(m6_engine).status == "uncertain"


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://evil.invalid/api/integrations/notifications",
        "http://example.com",
        "https://software6-bff-2-cnbqhhgdcndzgwdx.chilecentral-01.azurewebsites.net@evil.invalid",
        "http://127.0.0.1:9000/a?key=secret",
    ],
)
def test_key_cannot_be_configured_for_an_untrusted_target(endpoint):
    with pytest.raises(ValueError):
        Settings(_env_file=None, database_url="sqlite:///:memory:", module6_endpoint=endpoint)


def test_key_required_when_enabled_and_secret_repr():
    with pytest.raises(ValueError):
        Settings(
            _env_file=None,
            database_url="sqlite:///:memory:",
            module6_enabled=True,
            module6_source="backlog",
        )
    settings = Settings(_env_file=None, database_url="sqlite:///:memory:", module6_key=KEY)
    assert KEY not in repr(settings)


def test_manual_retry_requires_duplicate_ack_for_uncertain_and_never_requeues_delivered(m6_engine):
    _, repository, delivery, _ = modules()
    enqueue(m6_engine)
    outbox = repository.NotificationOutbox(m6_engine)
    claim = outbox.claim(NOW)
    outbox.finish(claim, delivery.Outcome("uncertain", error="unknown"), NOW)
    assert not outbox.retry(payload()["event_id"], NOW, acknowledge_duplicate_risk=False)
    assert outbox.retry(payload()["event_id"], NOW, acknowledge_duplicate_risk=True)
    claim = outbox.claim(NOW)
    outbox.finish(claim, delivery.Outcome("delivered"), NOW)
    assert not outbox.retry(payload()["event_id"], NOW, acknowledge_duplicate_risk=True)


def test_capture_deduplicates_stable_event_id(m6_engine):
    _, repository, _, _ = modules()
    enqueue(m6_engine)
    enqueue(m6_engine)
    assert repository.NotificationOutbox(m6_engine).counts() == {"pending": 1}


def test_additive_migration_creates_delivery_table_without_replaying_history(m6_engine):
    from projects_service.database import migrate_schema
    from projects_service.models import NotificationDeliveryRecord

    NotificationDeliveryRecord.__table__.drop(m6_engine)
    migrate_schema(m6_engine, "projects")
    migrate_schema(m6_engine, "projects")
    assert record(m6_engine) is None


def test_two_workers_claim_each_event_at_most_once(m6_engine):
    from concurrent.futures import ThreadPoolExecutor

    _, repository, _, _ = modules()
    enqueue(m6_engine)
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(
            pool.map(lambda _: repository.NotificationOutbox(m6_engine).claim(NOW), range(2))
        )
    assert sum(claim is not None for claim in claims) == 1


def test_dispatch_rejects_unbounded_batches():
    _, _, delivery, _ = modules()
    for limit in (0, 101):
        with pytest.raises(ValueError):
            delivery.dispatch(None, None, limit=limit)


def test_project_creation_lifecycle_and_team_approval_reuse_event_ids(m6_engine):
    from projects_service.access_repository import AccessRepository
    from projects_service.dependencies import build_projects_service
    from projects_service.domain import ProjectDraft
    from projects_service.models import EventRecord, NotificationDeliveryRecord

    actor = uuid4()
    with Session(m6_engine, expire_on_commit=False) as session:
        service = build_projects_service(session, clock=lambda: NOW, id_factory=lambda: PROJECT)
        service.create(actor, ProjectDraft(name="Private project"))
        service.access.lifecycle(actor, PROJECT, expected_version=1, status="active")
        repository = AccessRepository(session)
        repository.event(
            PROJECT,
            actor,
            "recommendation.approved",
            2,
            {"kind": "teams", "recommendation_id": str(uuid4()), "private": "secret"},
        )
        repository.event(
            PROJECT, actor, "recommendation.approved", 2, {"kind": "access_revocation"}
        )
        repository.event(PROJECT, actor, "recommendation.rejected", 2, {"kind": "teams"})
        session.commit()
        events = list(session.scalars(select(EventRecord)))
        rows = list(session.scalars(select(NotificationDeliveryRecord)))
        assert len(rows) == 3
        assert {row.payload["type"] for row in rows} == {
            "project.created",
            "project.lifecycle",
            "project.teams.approved",
        }
        assert {row.event_id for row in rows} <= {
            "mod1:projects:" + str(event.id) for event in events
        }
        assert "private" not in str([row.payload for row in rows]).lower()


def test_projects_require_explicit_agreed_source_before_enabling():
    with pytest.raises(ValueError):
        Settings(
            _env_file=None, database_url="sqlite:///:memory:", module6_enabled=True, module6_key=KEY
        )


def worker_cli():
    try:
        return importlib.import_module("projects_service.module6_cli")
    except ImportError:
        pytest.fail("The notification worker CLI is missing")


def test_worker_status_and_disabled_dispatch_never_make_http_calls(m6_engine, monkeypatch, capsys):
    import json

    enqueue(m6_engine)
    monkeypatch.setenv("DATABASE_URL", str(m6_engine.url))
    monkeypatch.setenv("MODULE6_ENABLED", "false")
    monkeypatch.delenv("MODULE6_KEY", raising=False)
    monkeypatch.delenv("MODULE6_SOURCE", raising=False)
    cli = worker_cli()
    assert cli.main(["status"]) == 0
    assert json.loads(capsys.readouterr().out) == {"pending": 1}
    assert cli.main(["dispatch"]) == 2
    assert record(m6_engine).attempts == 0


def test_worker_missing_schema_exits_with_redacted_error(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'absent.db'}")
    monkeypatch.setenv("MODULE6_ENABLED", "false")
    assert worker_cli().main(["status"]) == 1
    error = capsys.readouterr().err
    assert "sqlite" not in error and str(tmp_path) not in error


def test_actual_tcp_receiver_observes_committed_event_and_cli_delivery(
    m6_engine, monkeypatch, capsys
):
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    observed = []

    class Receiver(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            observed.append(
                (
                    self.path,
                    body,
                    self.headers.get("X-Integration-Key"),
                    self.headers.get("Authorization"),
                )
            )
            reply = receiver_reply(None).content
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(reply)))
            self.end_headers()
            self.wfile.write(reply)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Receiver)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        enqueue(m6_engine)
        monkeypatch.setenv("DATABASE_URL", str(m6_engine.url))
        monkeypatch.setenv("MODULE6_ENABLED", "true")
        monkeypatch.setenv("MODULE6_KEY", KEY)
        monkeypatch.setenv("MODULE6_SOURCE", "backlog")
        monkeypatch.setenv(
            "MODULE6_ENDPOINT",
            f"http://127.0.0.1:{server.server_port}/api/integrations/notifications",
        )
        cli = worker_cli()
        assert cli.main(["dispatch", "--batch-size", "10"]) == 0
        assert record(m6_engine).status == "delivered"
        assert cli.main(["dispatch"]) == 0
        assert len(observed) == 1
        path, body, key, bearer = observed[0]
        assert path == "/api/integrations/notifications" and body == payload()
        assert key == KEY and bearer is None
        assert KEY not in capsys.readouterr().out
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


@pytest.mark.parametrize(
    "field,value",
    [
        ("priority", "urgent"),
        ("classified_by", "unknown"),
        ("created_at", "not-a-date"),
        ("scope", "global"),
        ("event_id", "wrong"),
        ("project_id", "another-project"),
        ("relevance_score", 2),
    ],
)
def test_invalid_or_unrelated_acknowledgement_is_never_delivered(m6_engine, field, value):
    import json

    _, repository, delivery, _ = modules()
    enqueue(m6_engine)
    body = json.loads(receiver_reply(None).content)
    body[field] = value
    delivery.dispatch(
        repository.NotificationOutbox(m6_engine),
        sender(lambda request: httpx.Response(200, json=body)),
        limit=1,
        clock=lambda: NOW,
    )
    assert record(m6_engine).status == "uncertain"


def test_unbounded_receiver_body_is_not_treated_as_success(m6_engine):
    _, repository, delivery, _ = modules()
    enqueue(m6_engine)
    delivery.dispatch(
        repository.NotificationOutbox(m6_engine),
        sender(lambda request: httpx.Response(200, content=b"x" * 65537)),
        limit=1,
        clock=lambda: NOW,
    )
    assert record(m6_engine).status == "uncertain"


def test_payload_matches_the_owners_input_contract():
    import json
    from pathlib import Path

    document = json.loads(
        (Path(__file__).parent / "fixtures/module6-contract.json").read_text(encoding="utf-8")
    )
    schemas = document["components"]["schemas"]
    contract = schemas["NotificationInput"]
    domain, _, _, _ = modules()
    message = domain.build_notification(EVENT, PROJECT, "project.created", {}, "backlog")
    assert set(contract["required"]) <= message.keys()
    assert message.keys() <= contract["properties"].keys()
    for key in ["source", "scope", "priority"]:
        schema = schemas[contract["properties"][key]["$ref"].split("/")[-1]]
        assert message[key] in schema["enum"]
    for key in ["event_id", "source", "type", "title", "body", "project_id"]:
        assert isinstance(message[key], str)
    assert message["project_id"] and message["scope"] == "project"


def test_operator_can_list_failed_events_without_private_payloads(m6_engine, monkeypatch, capsys):
    import json

    _, repository, delivery, _ = modules()
    enqueue(m6_engine)
    outbox = repository.NotificationOutbox(m6_engine)
    claim = outbox.claim(NOW)
    outbox.finish(claim, delivery.Outcome("uncertain", error="transport_outcome_unknown"), NOW)
    monkeypatch.setenv("DATABASE_URL", str(m6_engine.url))
    monkeypatch.setenv("MODULE6_ENABLED", "false")
    assert worker_cli().main(["list", "--status", "uncertain", "--limit", "1"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert len(output) == 1 and output[0]["event_id"] == payload()["event_id"]
    assert output[0]["last_error"] == "transport_outcome_unknown"
    assert "payload" not in output[0] and KEY not in str(output)


@pytest.mark.parametrize("name", ["notifications_domain", "notification_delivery"])
def test_notification_domain_and_dispatcher_preserve_layer_boundaries(name):
    import ast
    from pathlib import Path

    package = "projects_service"
    source = Path(__file__).resolve().parents[1] / "src" / package / (name + ".py")
    tree = ast.parse(source.read_text(encoding="utf-8"))
    forbidden = (
        "httpx",
        "fastapi",
        "starlette",
        "sqlalchemy",
        package + ".models",
        package + ".config",
        package + ".database",
        package + ".notification_repository",
        package + ".module6_client",
    )
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
    assert not any(
        name == item or name.startswith(item + ".") for name in imports for item in forbidden
    )


@pytest.mark.parametrize("phase", ["headers", "body"])
def test_total_deadline_cancels_slow_headers_or_body(phase):
    import threading
    import time
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    _, _, _, adapter = modules()
    received = threading.Event()

    class SlowReceiver(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            received.set()
            reply = receiver_reply(None).content
            try:
                if phase == "headers":
                    time.sleep(0.9)
                self.send_response(200)
                self.send_header("Content-Length", str(len(reply)))
                self.end_headers()
                if phase == "body":
                    self.wfile.write(reply[:1])
                    self.wfile.flush()
                    time.sleep(0.9)
                    self.wfile.write(reply[1:])
                else:
                    self.wfile.write(reply)
            except OSError:
                pass

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), SlowReceiver)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        target = adapter.Module6Client(
            f"http://127.0.0.1:{server.server_port}/api/integrations/notifications",
            KEY,
            deadline_seconds=0.35,
        )
        started = time.monotonic()
        result = target.send(payload())
        elapsed = time.monotonic() - started
        assert received.is_set()
        assert result.status == "uncertain" and result.error == "delivery_deadline_exceeded"
        assert elapsed < 0.8
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
