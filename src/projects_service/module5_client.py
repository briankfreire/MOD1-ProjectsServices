"""Project curation HTTP adapter with a cancellable total request deadline."""

import asyncio
import json
import math
import re
from typing import Never

import httpx

from projects_service.access_domain import AccessError
from projects_service.module5_domain import CurationResult, ProviderArticles, ProviderFeed

BASE_URL = (
    "https://agente-tendencias-tecnologicas-fyd3bzerc9a2cqcu.chilecentral-01.azurewebsites.net"
)
MAX_RESPONSE_BYTES = 1024 * 1024


def trusted_base_url(value: str) -> str:
    if value == BASE_URL:
        return value
    loopback = re.fullmatch(r"http://(?:localhost|127\.0\.0\.1|\[::1\]):([0-9]{1,5})", value)
    if loopback and 0 < int(loopback[1]) <= 65535:
        return value
    raise ValueError("Module 5 requires the official HTTPS base or explicit HTTP loopback")


def reject_nonfinite(_: str) -> Never:
    raise ValueError("Non-finite JSON number")


def finite_number(value: str) -> float:
    number = float(value)
    return number if math.isfinite(number) else reject_nonfinite(value)


class Module5Client:
    def __init__(self, base_url: str, *, deadline_seconds: float = 60) -> None:
        if not 0 < deadline_seconds <= 60:
            raise ValueError("Module 5 request deadline must be positive and at most 60 seconds")
        self.base_url = trusted_base_url(base_url)
        self.deadline_seconds = deadline_seconds

    def feed(self) -> CurationResult:
        return self._receive("GET", "/feed", ProviderFeed)

    def query(self, token: str, pergunta: str) -> CurationResult:
        return self._receive("POST", "/consultas", ProviderArticles, token=token, pergunta=pergunta)

    def _receive(
        self,
        method: str,
        path: str,
        schema: type[ProviderArticles],
        *,
        token: str | None = None,
        pergunta: str | None = None,
    ) -> CurationResult:
        try:
            content = asyncio.run(self._bounded_request(method, path, token, pergunta))
            data = json.loads(
                content.decode("utf-8"), parse_constant=reject_nonfinite, parse_float=finite_number
            )
            return schema.model_validate(data).public_result()
        except (httpx.HTTPError, ValueError, RecursionError, TimeoutError):
            raise AccessError(503, "Curation service temporarily unavailable") from None

    async def _bounded_request(
        self, method: str, path: str, token: str | None, pergunta: str | None
    ) -> bytearray:
        return await asyncio.wait_for(
            self._request(method, path, token, pergunta),
            timeout=self.deadline_seconds,
        )

    async def _request(
        self, method: str, path: str, token: str | None, pergunta: str | None
    ) -> bytearray:
        headers = {"Accept": "application/json", "Accept-Encoding": "identity"}
        if token is not None:
            headers["Authorization"] = "Bearer " + token
        async with httpx.AsyncClient(
            trust_env=False,
            follow_redirects=False,
            timeout=httpx.Timeout(5, read=55),
        ) as client:
            async with client.stream(
                method,
                self.base_url + path,
                headers=headers,
                json={"pergunta": pergunta} if pergunta is not None else None,
            ) as response:
                if response.status_code == 401:
                    raise AccessError(401, "Authentication required")
                if response.status_code == 403:
                    raise AccessError(403, "Curation access denied")
                if (
                    response.status_code != 200
                    or response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
                    != "application/json"
                    or response.headers.get("Content-Encoding", "identity").lower() != "identity"
                ):
                    raise ValueError("Unexpected curation response")
                content = bytearray()
                async for chunk in response.aiter_raw(chunk_size=8192):
                    if len(content) + len(chunk) > MAX_RESPONSE_BYTES:
                        raise ValueError("Curation response exceeded size limit")
                    content.extend(chunk)
                return content
