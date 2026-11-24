"""Bounded GET-only transport for the public Module 3 artifact service."""

import asyncio
import json
import math
import re
from collections.abc import Awaitable, Callable
from typing import TypeVar
from urllib.parse import urlencode

import httpx
from pydantic import BaseModel

from projects_service.access_domain import AccessError
from projects_service.module3_domain import (
    PUBLIC_LIMIT,
    ArtifactCatalog,
    ArtifactDownload,
    ArtifactItem,
    ArtifactList,
    ArtifactPage,
    ProjectList,
    VersionList,
    VersionPage,
)

BASE_URL = "https://modulo3-fhgjdpa6d5bbfvff.canadacentral-01.azurewebsites.net"
MAX_JSON_BYTES = 1024 * 1024
MAX_DOWNLOAD_BYTES = 10 * 1024 * 1024
T = TypeVar("T")
Model = TypeVar("Model", bound=BaseModel)


def trusted_base_url(value: str) -> str:
    if value == BASE_URL:
        return value
    match = re.fullmatch(r"http://(?:localhost|127\.0\.0\.1|\[::1\]):([0-9]{1,5})", value)
    if match and 0 < int(match[1]) <= 65535:
        return value
    raise ValueError("Module 3 requires official HTTPS or explicit HTTP loopback")


def finite_number(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Non-finite JSON")
    return number


class Module3Client:
    def __init__(self, base_url: str, *, deadline_seconds: float = 30) -> None:
        self.base_url = trusted_base_url(base_url)
        if not 0 < deadline_seconds <= 30:
            raise ValueError("Module 3 deadline must be positive and at most30seconds")
        self.deadline_seconds = deadline_seconds

    def _run(
        self,
        operation: Callable[[httpx.AsyncClient], Awaitable[T]],
        loop: asyncio.AbstractEventLoop | None,
    ) -> T:
        async def perform() -> T:
            async with httpx.AsyncClient(
                trust_env=False,
                follow_redirects=False,
                timeout=httpx.Timeout(5, read=25),
                headers={"Accept-Encoding": "identity"},
            ) as client:
                return await operation(client)

        async def bounded() -> T:
            return await asyncio.wait_for(perform(), timeout=self.deadline_seconds)

        try:
            if loop is not None:
                future = asyncio.run_coroutine_threadsafe(bounded(), loop)
                try:
                    return future.result(timeout=self.deadline_seconds + 1)
                except TimeoutError:
                    future.cancel()
                    raise
            local = asyncio.new_event_loop()
            try:
                return local.run_until_complete(bounded())
            finally:
                local.close()
        except (httpx.HTTPError, ValueError, RecursionError, TimeoutError):
            raise AccessError(503, "Artifact service temporarily unavailable") from None

    async def _read(self, client: httpx.AsyncClient, path: str, *, binary: bool = False) -> bytes:
        limit = MAX_DOWNLOAD_BYTES if binary else MAX_JSON_BYTES
        async with client.stream("GET", self.base_url + path) as response:
            if response.status_code == 404:
                raise AccessError(404, "Artifact unavailable")
            media = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            allowed = (
                {
                    "application/octet-stream",
                    "application/pdf",
                    "text/markdown",
                    "text/plain",
                    "image/png",
                    "image/jpeg",
                }
                if binary
                else {"application/json"}
            )
            if (
                response.status_code != 200
                or media not in allowed
                or response.headers.get("Content-Encoding", "identity").lower() != "identity"
            ):
                raise ValueError("Unexpected artifact response")
            size = response.headers.get("Content-Length")
            if size is not None and not 0 <= int(size) <= limit:
                raise ValueError("Artifact response too large")
            content = bytearray()
            async for chunk in response.aiter_raw(chunk_size=8192):
                if len(content) + len(chunk) > limit:
                    raise ValueError("Artifact response too large")
                content.extend(chunk)
            return bytes(content)

    async def _json(self, client: httpx.AsyncClient, path: str, model: type[Model]) -> Model:
        data = await self._read(client, path)
        value = json.loads(data, parse_constant=finite_number, parse_float=finite_number)
        result = model.model_validate(value)
        rows = getattr(result, "root", [])
        if len({row.id for row in rows}) != len(rows):
            raise ValueError("Duplicate artifact identifiers")
        return result

    def catalog(self, *, loop: asyncio.AbstractEventLoop | None = None) -> ArtifactCatalog:
        async def perform(client: httpx.AsyncClient) -> ArtifactCatalog:
            rows = (await self._json(client, "/projects/", ProjectList)).root
            return ArtifactCatalog(
                items=rows[:PUBLIC_LIMIT], total=len(rows), truncated=len(rows) > PUBLIC_LIMIT
            )

        return self._run(perform, loop)

    async def _artifacts(
        self,
        client: httpx.AsyncClient,
        project_id: int,
        search: str = "",
        artifact_type: str = "",
    ) -> list[ArtifactItem]:
        params = {k: v for k, v in {"search": search, "artifact_type": artifact_type}.items() if v}
        suffix = "?" + urlencode(params) if params else ""
        rows = (
            await self._json(client, f"/projects/{project_id}/artifacts/{suffix}", ArtifactList)
        ).root
        if any(row.project_id != project_id for row in rows):
            raise ValueError("Artifact project mismatch")
        return rows

    def artifacts(
        self,
        project_id: int,
        *,
        search: str = "",
        artifact_type: str = "",
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> ArtifactPage:
        async def perform(client: httpx.AsyncClient) -> ArtifactPage:
            rows = await self._artifacts(client, project_id, search, artifact_type)
            return ArtifactPage(
                module3_project_id=project_id,
                items=rows[:PUBLIC_LIMIT],
                total=len(rows),
                truncated=len(rows) > PUBLIC_LIMIT,
            )

        return self._run(perform, loop)

    async def _artifact(
        self, client: httpx.AsyncClient, project_id: int, artifact_id: int
    ) -> ArtifactItem:
        rows = await self._artifacts(client, project_id)
        for row in rows:
            if row.id == artifact_id:
                return row
        raise AccessError(404, "Artifact unavailable")

    def versions(
        self,
        project_id: int,
        artifact_id: int,
        *,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> VersionPage:
        async def perform(client: httpx.AsyncClient) -> VersionPage:
            await self._artifact(client, project_id, artifact_id)
            rows = (
                await self._json(
                    client, f"/projects/{project_id}/artifacts/{artifact_id}/versions", VersionList
                )
            ).root
            if any(row.artifact_id != artifact_id for row in rows):
                raise ValueError("Version artifact mismatch")
            rows.sort(key=lambda row: row.version_number, reverse=True)
            return VersionPage(
                module3_project_id=project_id,
                artifact_id=artifact_id,
                items=rows[:PUBLIC_LIMIT],
                total=len(rows),
                truncated=len(rows) > PUBLIC_LIMIT,
            )

        return self._run(perform, loop)

    def download(
        self,
        project_id: int,
        artifact_id: int,
        *,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> ArtifactDownload:
        async def perform(client: httpx.AsyncClient) -> ArtifactDownload:
            artifact = await self._artifact(client, project_id, artifact_id)
            content = await self._read(
                client, f"/projects/{project_id}/artifacts/{artifact_id}/download", binary=True
            )
            extension = {"PDF": "pdf", "MARKDOWN": "md", "PNG": "png", "JPEG": "jpg"}[
                artifact.artifact_type
            ]
            return ArtifactDownload(content, f"artifact-{artifact_id}.{extension}")

        return self._run(perform, loop)
