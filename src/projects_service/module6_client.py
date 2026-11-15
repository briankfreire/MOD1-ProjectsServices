"""Module 6 infrastructure adapter; bounded I/O and conservative POST outcomes."""

import asyncio
from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from projects_service.notifications_domain import Outcome

ENDPOINT = "https://software6-bff-2-cnbqhhgdcndzgwdx.chilecentral-01.azurewebsites.net/api/integrations/notifications"


def trusted_endpoint(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or "?" in value
        or "#" in value
        or "\\" in value
        or "%" in value
        or any(ord(char) <= 32 or ord(char) == 127 for char in value)
        or any(part in {".", ".."} for part in parsed.path.split("/"))
    ):
        raise ValueError("Use the trusted Module 6 endpoint or explicit HTTP loopback")
    if value != ENDPOINT and not (
        parsed.scheme == "http"
        and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        and parsed.port
    ):
        raise ValueError("Use the trusted Module 6 endpoint or explicit HTTP loopback")
    return value


class Acknowledgement(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(min_length=1, max_length=200)
    source: str
    type: str
    title: str
    body: str
    priority: Literal["critical", "high", "medium", "low"]
    relevance_score: float = Field(ge=0, le=1)
    reason: str
    classified_by: Literal["llm", "rules"]
    created_at: datetime
    event_id: str | None = None
    project_id: str | None = None
    scope: str | None = None


class Module6Client:
    def __init__(
        self,
        endpoint: str,
        key: str,
        *,
        deadline_seconds: float = 15,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not 0 < deadline_seconds <= 30:
            raise ValueError("Delivery deadline must be positive and at most 30 seconds")
        self.endpoint, self._key = trusted_endpoint(endpoint), key
        self.deadline_seconds, self.transport = deadline_seconds, transport

    def send(self, payload: dict[str, Any]) -> Outcome:
        # The synchronous application port is used only by the dedicated worker.
        # A request owns its cancellable client so no connection survives its event loop.
        try:
            return asyncio.run(self._deliver(payload))
        except TimeoutError:
            return Outcome("uncertain", "delivery_deadline_exceeded")
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
            return Outcome("pending", "connection_unavailable")
        except httpx.HTTPError:
            return Outcome("uncertain", "transport_outcome_unknown")

    async def _deliver(self, payload: dict[str, Any]) -> Outcome:
        return await asyncio.wait_for(self._post(payload), timeout=self.deadline_seconds)

    async def _post(self, payload: dict[str, Any]) -> Outcome:
        async with httpx.AsyncClient(
            transport=self.transport,
            trust_env=False,
            follow_redirects=False,
            timeout=httpx.Timeout(10, connect=5),
        ) as client:
            async with client.stream(
                "POST",
                self.endpoint,
                json=payload,
                headers={"X-Integration-Key": self._key, "Content-Type": "application/json"},
            ) as response:
                code = response.status_code
                if code in {401, 403, 429}:
                    return Outcome("blocked", "receiver_rejected", code)
                if 300 <= code < 500:
                    return Outcome("failed", "receiver_rejected", code)
                if code != 200:
                    return Outcome("uncertain", "unexpected_response", code)
                content = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=8192):
                    content.extend(chunk)
                    if len(content) > 65536:
                        return Outcome("uncertain", "invalid_acknowledgement", code)
                try:
                    acknowledgement = Acknowledgement.model_validate_json(content)
                except ValidationError:
                    return Outcome("uncertain", "invalid_acknowledgement", code)
                if (
                    any(
                        value is not None and value != payload.get(name)
                        for name, value in (
                            ("event_id", acknowledgement.event_id),
                            ("project_id", acknowledgement.project_id),
                            ("scope", acknowledgement.scope),
                        )
                    )
                    or acknowledgement.source != payload["source"]
                    or acknowledgement.type != payload["type"]
                ):
                    return Outcome("uncertain", "mismatched_acknowledgement", code)
                return Outcome("delivered", http_status=code)
