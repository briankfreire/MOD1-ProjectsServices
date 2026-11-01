from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from projects_service.access_domain import Invitation, Member
from projects_service.access_repository import AccessRepository
from projects_service.domain import Project
from projects_service.models import Base, InvitationRecord, MemberRecord, ProjectRecord


def test_repository_returns_detached_domain_snapshots():
    engine = create_engine("sqlite:///:memory:").execution_options(
        schema_translate_map={"projects": None}
    )
    Base.metadata.create_all(engine)
    owner, user, project_id, invitation_id = (uuid4() for _ in range(4))
    now = datetime(2026, 10, 30, tzinfo=UTC)
    code_hash = sha256(b"synthetic-invitation").hexdigest()
    with Session(engine) as session:
        session.add(
            ProjectRecord(
                id=project_id,
                owner_id=owner,
                name="Snapshot",
                description="",
                objective="",
                created_at=now,
            )
        )
        session.add(
            MemberRecord(
                project_id=project_id,
                user_id=user,
                roles=["developer"],
                expires_at=None,
            )
        )
        session.add(
            InvitationRecord(
                id=invitation_id,
                project_id=project_id,
                user_id=user,
                roles=["developer"],
                expires_at=None,
                code_hash=code_hash,
                code_expires_at=now,
                status="pending",
            )
        )
        session.commit()
        repository = AccessRepository(session)
        project = repository.project(project_id)
        member = repository.member(project_id, user)
        invitation = repository.invitation(code_hash)
        assert isinstance(project, Project)
        assert isinstance(member, Member)
        assert isinstance(invitation, Invitation)
        member.roles.clear()
        invitation.roles.clear()
        session.commit()
        assert repository.member(project_id, user).roles == ["developer"]
        assert repository.invitation(code_hash).roles == ["developer"]
        with repository.locked_project(project_id) as locked:
            assert isinstance(locked, Project)
            assert locked == project
    assert project.name == "Snapshot" and project.created_at == now
    engine.dispose()
