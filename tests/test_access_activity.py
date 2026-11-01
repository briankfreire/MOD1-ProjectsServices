"""US039 only suggests revocation from a complete conservative observation window."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from test_advanced import auth, configure_provider, create
from test_notifications import concurrent_client as concurrent_client


@pytest.fixture
def client(advanced_http_client):
    return advanced_http_client


def granted(client, issuer):
    client.app.state.clock = lambda: datetime(2026, 9, 1, tzinfo=UTC)
    project = create(client, issuer)
    target = uuid4()
    path = "/projects/" + project["id"]
    assert (
        client.post(
            path + "/members",
            json={"user_id": str(target), "roles": ["developer"]},
            headers=auth(issuer),
        ).status_code
        == 201
    )
    return path, target


def propose(client, issuer, path, target, **constraints):
    configure_provider(
        client,
        issuer,
        target,
        "access_revocation",
        [{"user_id": str(target), "reason": "Observed inactivity; review manually"}],
    )
    return client.post(
        path + "/recommendations",
        json={"kind": "access_revocation", "constraints": constraints},
        headers=auth(issuer),
    )


def test_full_observation_window_allows_human_revocation_but_recent_use_excludes(client, issuer):
    path, target = granted(client, issuer)
    client.app.state.clock = lambda: datetime(2026, 10, 2, tzinfo=UTC)
    draft = propose(client, issuer, path, target)
    assert draft.status_code == 201, draft.text
    assert client.get(path + "/access/v2", headers=auth(issuer, target)).status_code == 200
    response = client.post(
        path + "/recommendations/" + draft.json()["id"] + "/approve",
        json={"expected_version": 1},
        headers=auth(issuer),
    )
    assert response.status_code == 409
    assert client.get(path, headers=auth(issuer, target)).status_code == 200
    assert propose(client, issuer, path, target).status_code == 409


def test_evidence_proven_inactivity_can_be_approved_once(client, issuer):
    path, target = granted(client, issuer)
    client.app.state.clock = lambda: datetime(2026, 10, 2, tzinfo=UTC)
    draft = propose(client, issuer, path, target)
    assert draft.status_code == 201, draft.text
    endpoint = path + "/recommendations/" + draft.json()["id"] + "/approve"
    assert (
        client.post(endpoint, json={"expected_version": 1}, headers=auth(issuer)).status_code == 200
    )
    assert (
        client.post(endpoint, json={"expected_version": 1}, headers=auth(issuer)).status_code == 200
    )
    assert client.get(path, headers=auth(issuer, target)).status_code == 404


def test_legacy_without_observation_stays_unknown_not_inactive(client, issuer):
    from projects_service.models import MemberRecord

    client.app.state.clock = lambda: datetime(2026, 10, 2, tzinfo=UTC)
    project = create(client, issuer)
    target = uuid4()
    path = "/projects/" + project["id"]
    with Session(client.app.state.engine) as session:
        session.add(
            MemberRecord(
                project_id=UUID(project["id"]),
                user_id=target,
                roles=["developer"],
                expires_at=None,
                role_grants=[],
            )
        )
        session.commit()
    assert propose(client, issuer, path, target).status_code == 409


def test_new_grant_resets_observation_window(client, issuer):
    path, target = granted(client, issuer)
    client.app.state.clock = lambda: datetime(2026, 10, 2, tzinfo=UTC)
    assert (
        client.patch(
            path + "/members/" + str(target),
            json={"roles": ["product_owner"]},
            headers=auth(issuer),
        ).status_code
        == 200
    )
    assert propose(client, issuer, path, target).status_code == 409


@pytest.mark.parametrize("unused_days", [0, 3651, True, "30"])
def test_inactivity_window_is_strict_and_bounded(client, issuer, unused_days):
    path, target = granted(client, issuer)
    assert propose(client, issuer, path, target, unused_days=unused_days).status_code == 422


def test_observation_write_failure_prevents_authorized_action(client, issuer):
    from projects_service.models import AccessObservationRecord

    path, target = granted(client, issuer)
    client.app.state.clock = lambda: datetime(2026, 10, 2, tzinfo=UTC)

    def unavailable(connection, cursor, statement, parameters, context, executemany):
        if "ACCESS_OBSERVATIONS" in statement.upper() and statement.lstrip().upper().startswith(
            ("INSERT", "UPDATE")
        ):
            raise OperationalError(statement, parameters, Exception("synthetic telemetry outage"))

    event.listen(client.app.state.engine, "before_cursor_execute", unavailable)
    try:
        assert (
            client.patch(path, json={"name": "Must not commit"}, headers=auth(issuer)).status_code
            == 503
        )
        assert client.get(path + "/access/v2", headers=auth(issuer, target)).status_code == 503
    finally:
        event.remove(client.app.state.engine, "before_cursor_execute", unavailable)
    assert client.get(path, headers=auth(issuer)).json()["name"] == "Advanced"
    outsider = uuid4()
    assert client.get(path + "/access/v2", headers=auth(issuer, outsider)).status_code == 404
    with Session(client.app.state.engine) as session:
        assert (
            session.scalar(
                select(AccessObservationRecord).where(AccessObservationRecord.user_id == outsider)
            )
            is None
        )


def test_activity_and_revocation_decision_are_serialized(concurrent_client, issuer, monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from projects_service.collaboration_repository import CollaborationRepository
    from projects_service.recommendation_service import RecommendationService

    client = concurrent_client
    path, target = granted(client, issuer)
    client.app.state.clock = lambda: datetime(2026, 10, 2, tzinfo=UTC)
    draft = propose(client, issuer, path, target)
    assert draft.status_code == 201, draft.text
    validated, release, activity_entered = threading.Event(), threading.Event(), threading.Event()
    apply = RecommendationService.apply
    observe = CollaborationRepository.observe_activity

    def pause_after_validation(service, *args):
        validated.set()
        assert release.wait(timeout=8)
        return apply(service, *args)

    def observe_request(repository, project, user, now):
        if user == target:
            activity_entered.set()
        return observe(repository, project, user, now)

    monkeypatch.setattr(RecommendationService, "apply", pause_after_validation)
    monkeypatch.setattr(CollaborationRepository, "observe_activity", observe_request)
    with ThreadPoolExecutor(max_workers=2) as pool:
        decision = pool.submit(
            client.post,
            path + "/recommendations/" + draft.json()["id"] + "/approve",
            json={"expected_version": 1},
            headers=auth(issuer),
        )
        try:
            assert validated.wait(timeout=8)
            access = pool.submit(client.get, path + "/access/v2", headers=auth(issuer, target))
            assert activity_entered.wait(timeout=8)
        finally:
            release.set()
        assert decision.result(timeout=12).status_code == 200
        assert access.result(timeout=12).status_code == 404


def test_ordinary_read_activity_does_not_invalidate_unrelated_role_proposal(client, issuer):
    path, target = granted(client, issuer)
    configure_provider(
        client,
        issuer,
        target,
        "roles",
        [
            {"user_id": str(target), "roles": ["developer"]},
        ],
    )
    draft = client.post(path + "/recommendations", json={"kind": "roles"}, headers=auth(issuer))
    assert draft.status_code == 201, draft.text
    assert client.get(path, headers=auth(issuer, target)).status_code == 200
    approval = client.post(
        path + "/recommendations/" + draft.json()["id"] + "/approve",
        json={"expected_version": 1},
        headers=auth(issuer),
    )
    assert approval.status_code == 200, approval.text
