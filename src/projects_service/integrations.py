"""HTTP infrastructure. No credential, profile or provider payload is logged."""

from typing import Any
from uuid import UUID

import httpx

from projects_service.access_domain import AccessError
from projects_service.config import Settings
from projects_service.security import AuthenticationRejected, SigningKeysUnavailable


class IdentityStatusClient:
    def __init__(self, settings: Settings, *, client: httpx.Client | None = None) -> None:
        self.base = settings.auth_api_base_url.rstrip("/")
        self.client = client or httpx.Client(timeout=5, follow_redirects=False)

    def check(self, token: str, user_id: UUID) -> None:
        try:
            response = self.client.get(
                self.base + "/auth/me", headers={"Authorization": "Bearer " + token}
            )
            if response.status_code == 401:
                raise AuthenticationRejected()
            response.raise_for_status()
            data = response.json()
            if (
                not isinstance(data, dict)
                or data.get("id") != str(user_id)
                or type(data.get("is_active")) is not bool
            ):
                raise ValueError()
            if not data["is_active"]:
                raise AuthenticationRejected()
        except (httpx.HTTPError, ValueError, TypeError):
            raise SigningKeysUnavailable() from None

    def active(self, token: str, user_id: UUID) -> bool:
        try:
            response = self.client.get(
                self.base + f"/auth/users/{user_id}/status",
                headers={"Authorization": "Bearer " + token},
            )
            if response.status_code == 404:
                return False
            response.raise_for_status()
            data = response.json()
            if data.get("id") != str(user_id) or type(data.get("is_active")) is not bool:
                raise ValueError()
            return bool(data["is_active"])
        except (httpx.HTTPError, ValueError, TypeError):
            raise AccessError(503, "Identity temporarily unavailable") from None

    def directory(self, token: str) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        try:
            for offset in range(0, 1000, 100):
                response = self.client.get(
                    self.base + "/auth/directory",
                    params={"limit": 100, "offset": offset},
                    headers={"Authorization": "Bearer " + token},
                )
                response.raise_for_status()
                page = response.json()
                result.extend(page["items"])
                if offset + 100 >= page["total"]:
                    return result
            raise ValueError()
        except (httpx.HTTPError, ValueError, TypeError, KeyError):
            raise AccessError(503, "Directory temporarily unavailable") from None

    def profile(self, token: str, user_id: UUID) -> dict[str, Any] | None:
        try:
            response = self.client.get(
                self.base + f"/auth/directory/{user_id}",
                headers={"Authorization": "Bearer " + token},
            )
            if response.status_code == 404:
                return None
            response.raise_for_status()
            data = response.json()
            if (
                data.get("user_id") != str(user_id)
                or type(data.get("weekly_availability_hours")) is not int
                or not 0 <= data["weekly_availability_hours"] <= 168
            ):
                raise ValueError()
            return dict(data)
        except (httpx.HTTPError, ValueError, TypeError):
            raise AccessError(503, "Directory temporarily unavailable") from None


class BacklogClient:
    def __init__(self, settings: Settings, *, client: httpx.Client | None = None) -> None:
        self.base = settings.backlog_api_base_url.rstrip("/")
        self.client = client or httpx.Client(timeout=5, follow_redirects=False)

    def summary(self, token: str, project_id: UUID) -> dict[str, Any]:
        try:
            response = self.client.get(
                self.base + f"/projects/{project_id}/content-summary",
                headers={"Authorization": "Bearer " + token},
            )
            response.raise_for_status()
            data = response.json()
            base_counts = ("stories", "epics", "tasks", "history")
            additive_counts = ("recommendations", "recommendation_events", "review_events")
            known = {"project_id", "total", *base_counts, *additive_counts}
            if not isinstance(data, dict) or set(data) - known:
                raise ValueError()
            if (
                data.get("project_id") != str(project_id)
                or any(
                    type(data.get(key)) is not int or data[key] < 0
                    for key in (*base_counts, "total")
                )
                or any(
                    type(data.get(key, 0)) is not int or data.get(key, 0) < 0
                    for key in additive_counts
                )
            ):
                raise ValueError()
            if data["total"] != sum(data.get(key, 0) for key in (*base_counts, *additive_counts)):
                raise ValueError()
            return dict(data)
        except (httpx.HTTPError, ValueError, TypeError):
            raise AccessError(503, "Backlog temporarily unavailable") from None

    def items_snapshot(self, token: str, project_id: UUID) -> list[dict[str, Any]]:
        from projects_service.recommendation_domain import WorkItemSnapshot

        items: list[dict[str, Any]] = []
        expected_total: int | None = None
        try:
            for offset in (0, 100):
                response = self.client.get(
                    self.base + f"/projects/{project_id}/items",
                    params={"limit": 100, "offset": offset},
                    headers={"Authorization": "Bearer " + token},
                )
                response.raise_for_status()
                page = response.json()
                if (
                    not isinstance(page, dict)
                    or type(page.get("total")) is not int
                    or page["total"] < 0
                    or page.get("limit") != 100
                    or page.get("offset") != offset
                    or not isinstance(page.get("items"), list)
                ):
                    raise ValueError()
                if page["total"] > 200:
                    raise AccessError(422, "Recommendation supports at most 200 backlog items")
                if expected_total is None:
                    expected_total = page["total"]
                if expected_total != page["total"] or len(page["items"]) != min(
                    100, max(0, expected_total - offset)
                ):
                    raise ValueError()
                for raw in page["items"]:
                    item = WorkItemSnapshot.model_validate(raw)
                    if item.project_id != project_id:
                        raise ValueError()
                    items.append(item.model_dump(mode="json"))
                if len(items) >= expected_total:
                    if len({item["id"] for item in items}) != len(items):
                        raise ValueError()
                    return sorted(items, key=lambda item: item["id"])
            raise ValueError()
        except (httpx.HTTPError, ValueError, TypeError, KeyError):
            raise AccessError(503, "Backlog snapshot temporarily unavailable") from None


class AIClient:
    """Opt-in generic structured provider; never retries a potentially paid request."""

    def __init__(self, settings: Settings, *, client: httpx.Client | None = None) -> None:
        self.settings = settings
        self.client = client or httpx.Client(timeout=30, follow_redirects=False)

    def generate(self, kind: str, context: dict[str, Any]) -> dict[str, Any]:
        import json
        from urllib.parse import urlsplit

        from pydantic import ValidationError

        from projects_service.recommendation_domain import AIResponse

        base = self.settings.ai_base_url
        if base is None:
            raise AccessError(503, "Recommendation provider is not configured")
        if self.settings.ai_simulated and urlsplit(base).hostname not in {
            "localhost",
            "127.0.0.1",
            "::1",
        }:
            raise AccessError(503, "Simulated provider must be local")
        body = {
            "schema_version": 1,
            "kind": kind,
            "model": self.settings.ai_model,
            "context": context,
        }
        if len(json.dumps(body, default=str).encode()) > 131072:
            raise AccessError(422, "Recommendation context too large")
        headers = {"Content-Type": "application/json"}
        if self.settings.ai_api_key:
            headers["Authorization"] = "Bearer " + self.settings.ai_api_key.get_secret_value()
        try:
            with self.client.stream(
                "POST", base.rstrip("/") + "/generate", json=body, headers=headers
            ) as response:
                response.raise_for_status()
                chunks = bytearray()
                for chunk in response.iter_bytes():
                    chunks.extend(chunk)
                    if len(chunks) > 65536:
                        raise ValueError()
                result = AIResponse.model_validate_json(bytes(chunks)).model_dump()
            return {
                **result,
                "model": self.settings.ai_model,
                "provider": urlsplit(base).hostname,
                "simulated": self.settings.ai_simulated,
            }
        except (httpx.HTTPError, ValueError, TypeError, ValidationError):
            raise AccessError(
                503, "Recommendation provider returned unavailable or invalid output"
            ) from None
