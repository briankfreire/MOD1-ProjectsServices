"""Project-scoped notification contracts; no HTTP, persistence or credentials."""

from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

DeliveryState = Literal["pending", "sending", "delivered", "blocked", "failed", "uncertain"]


@dataclass(frozen=True)
class Claim:
    event_id: str
    token: UUID
    payload: dict[str, Any]
    attempt: int


@dataclass(frozen=True)
class Outcome:
    status: DeliveryState
    error: str | None = None
    http_status: int | None = None


def build_notification(
    event_id: UUID, project_id: UUID, action: str, changes: dict[str, Any], source: str
) -> dict[str, Any] | None:
    catalog = {
        "project.created": ("Projeto criado", "Um projeto foi criado.", "medium"),
        "project.lifecycle": (
            "Status do projeto atualizado",
            "O ciclo de vida do projeto foi atualizado.",
            "medium",
        ),
        "project.archived": ("Projeto arquivado", "O projeto foi arquivado.", "medium"),
        "project.restored": ("Projeto restaurado", "O projeto foi restaurado.", "medium"),
    }
    kind = action
    if action == "recommendation.approved" and changes.get("kind") == "teams":
        kind = "project.teams.approved"
        title, body, priority = (
            "Equipes aprovadas",
            "A composição de equipes foi aprovada para o projeto.",
            "medium",
        )
    elif action in catalog:
        title, body, priority = catalog[action]
        if action == "project.lifecycle":
            labels = {
                "planned": "Planejado",
                "active": "Ativo",
                "suspended": "Suspenso",
                "completed": "Concluído",
            }
            body += " Status: " + labels.get(str(changes.get("status", "")), "atualizado") + "."
    else:
        return None

    return {
        "event_id": "mod1:projects:" + str(event_id),
        "scope": "project",
        "project_id": str(project_id),
        "source": source,
        "type": kind,
        "title": title,
        "body": body,
        "priority": priority,
        "link": None,
    }
