"""Application dispatcher. Ports keep SQL and HTTP outside this layer."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol

from projects_service.notifications_domain import Claim, Outcome


class Outbox(Protocol):
    def claim(self, now: datetime) -> Claim | None: ...
    def finish(self, claim: Claim, outcome: Outcome, now: datetime) -> bool: ...


class Sender(Protocol):
    def send(self, payload: dict[str, Any]) -> Outcome: ...


def dispatch(
    outbox: Outbox,
    sender: Sender,
    *,
    limit: int = 50,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> int:
    if not 1 <= limit <= 100:
        raise ValueError("Batch must contain between 1 and 100 events")
    count = 0
    for _ in range(limit):
        claim = outbox.claim(clock())
        if claim is None:
            break
        result = sender.send(claim.payload)
        outbox.finish(claim, result, clock())
        count += 1
    return count
