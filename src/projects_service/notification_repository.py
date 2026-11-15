"""Transactional capture and fenced delivery leases in this service's schema."""

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Engine, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from projects_service.models import NotificationDeliveryRecord as Row
from projects_service.notifications_domain import Claim, Outcome, build_notification


def capture(
    session: Session,
    event_id: UUID,
    project_id: UUID,
    action: str,
    changes: dict[str, Any],
    now: datetime,
) -> None:
    options = session.get_bind().get_execution_options()
    if not options.get("module6_enabled") or not options.get("module6_source"):
        return
    payload = build_notification(event_id, project_id, action, changes, options["module6_source"])
    if payload is not None:
        enqueue(session, payload, now)


def enqueue(session: Session, payload: dict[str, Any], now: datetime) -> None:
    if not session.get_bind().get_execution_options().get("module6_enabled"):
        return
    insert = sqlite_insert if session.get_bind().dialect.name == "sqlite" else pg_insert
    session.execute(
        insert(Row)
        .values(
            event_id=payload["event_id"],
            payload=payload,
            status="pending",
            attempts=0,
            available_at=now,
            created_at=now,
        )
        .on_conflict_do_nothing(index_elements=["event_id"])
    )


class NotificationOutbox:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def claim(self, now: datetime) -> Claim | None:
        with Session(self.engine) as session, session.begin():
            session.execute(
                update(Row)
                .where(Row.status == "sending", Row.lease_until <= now)
                .values(
                    status="uncertain", last_error="lease_expired", lease_id=None, lease_until=None
                )
            )
            row = session.scalar(
                select(Row)
                .where(Row.status == "pending", Row.available_at <= now)
                .order_by(Row.created_at, Row.event_id)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if row is None:
                return None
            token = uuid4()
            attempt = row.attempts + 1
            payload, event_id = dict(row.payload), row.event_id
            result = session.execute(
                update(Row)
                .where(Row.event_id == event_id, Row.status == "pending")
                .values(
                    status="sending",
                    lease_id=token,
                    lease_until=now + timedelta(seconds=60),
                    attempts=attempt,
                )
                .returning(Row.event_id)
            )
            if result.scalar_one_or_none() is None:
                return None
            return Claim(event_id, token, payload, attempt)

    def finish(self, claim: Claim, outcome: Outcome, now: datetime) -> bool:
        status = outcome.status
        if status == "pending" and claim.attempt >= 5:
            status = "failed"
        with Session(self.engine) as session, session.begin():
            result = session.execute(
                update(Row)
                .where(
                    Row.event_id == claim.event_id,
                    Row.status == "sending",
                    Row.lease_id == claim.token,
                    Row.lease_until > now,
                )
                .values(
                    status=status,
                    last_error=outcome.error,
                    last_http_status=outcome.http_status,
                    available_at=now + timedelta(seconds=min(30 * 2 ** (claim.attempt - 1), 3600)),
                    lease_id=None,
                    lease_until=None,
                    delivered_at=now if status == "delivered" else None,
                )
                .returning(Row.event_id)
            )
            return result.scalar_one_or_none() is not None

    def counts(self) -> dict[str, int]:
        with Session(self.engine) as session:
            return {
                status: count
                for status, count in session.execute(
                    select(Row.status, func.count()).group_by(Row.status)
                )
            }

    def list_events(self, status: str, limit: int = 50) -> list[dict[str, Any]]:
        if not 1 <= limit <= 100:
            raise ValueError("Limit must be between 1 and 100")
        with Session(self.engine) as session:
            rows = session.execute(
                select(Row.event_id, Row.status, Row.attempts, Row.last_error, Row.last_http_status)
                .where(Row.status == status)
                .order_by(Row.created_at, Row.event_id)
                .limit(limit)
            ).mappings()
            return [dict(row) for row in rows]

    def retry(
        self, event_id: str, now: datetime, *, acknowledge_duplicate_risk: bool = False
    ) -> bool:
        allowed = ["blocked", "failed"] + (["uncertain"] if acknowledge_duplicate_risk else [])
        with Session(self.engine) as session, session.begin():
            result = session.execute(
                update(Row)
                .where(Row.event_id == event_id, Row.status.in_(allowed))
                .values(
                    status="pending",
                    attempts=0,
                    available_at=now,
                    last_error="manual_retry",
                    lease_id=None,
                    lease_until=None,
                )
                .returning(Row.event_id)
            )
            return result.scalar_one_or_none() is not None
