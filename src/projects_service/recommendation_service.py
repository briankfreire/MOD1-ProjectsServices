"""Persisted, human-approved recommendations from bounded authorized snapshots."""

import json
from collections.abc import Callable
from datetime import timedelta
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4

from projects_service.access_domain import AccessError, Member, MembershipPatch, utc
from projects_service.collaboration_domain import RecommendationDraft
from projects_service.collaboration_service import CollaborationService, unavailable
from projects_service.recommendation_domain import valid_suggestions


def fingerprint(context: dict[str, Any]) -> str:
    # Elapsed clock time alone is not a context mutation. Eligibility states and
    # persisted observation timestamps remain hashed and are re-evaluated.
    if "access_usage" in context:
        context = {
            **context,
            "access_usage": {
                key: value
                for key, value in context["access_usage"].items()
                if key not in {"cutoff", "evaluated_at"}
            },
        }
    return sha256(
        json.dumps(context, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def public(record: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in record.items() if not key.startswith("_")}


class RecommendationService:
    def __init__(self, collaboration: CollaborationService) -> None:
        self.collaboration = collaboration
        self.repository = collaboration.repository
        self.access = collaboration.access
        self.generate: Callable[[str, dict[str, Any]], dict[str, Any]] = unavailable
        self.inactivity_days = 30

    def context(
        self,
        actor: UUID,
        project_id: UUID,
        kind: str,
        constraints: dict[str, Any],
        *,
        external: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        project = self.repository.project(project_id)
        self.access.require(project, actor, "project:members:manage")
        assert project is not None
        self.access.writable(project, administrative=True)
        if kind == "roles":
            self.access.require(project, actor, "project:roles:manage")
        if kind == "teams":
            self.access.require(project, actor, "project:teams:manage")
        if external is None:
            external = self.capture_external(actor, project_id, kind)
            # capture_external releases its read transaction before HTTP.
            project = self.repository.project(project_id)
            self.access.require(project, actor, "project:members:manage")
            assert project is not None
        if external["lease_generation"] is not None and (
            self.repository.active_leases(project_id)
            or self.repository.lease_generation(project_id) != external["lease_generation"]
        ):
            raise AccessError(409, "Backlog changed while collecting recommendation context")
        work_items: list[dict[str, Any]] | None = external["work_items"]
        directory = external["directory"]
        allowed = ("display_name", "summary", "seniority", "weekly_availability_hours", "skills")
        candidates = [
            {"id": str(p["user_id"]), **{k: p[k] for k in allowed if k in p}}
            for p in directory
            if p.get("share_for_recommendations") is True
        ]
        candidates.sort(key=lambda p: p["id"])
        members = self.access.members(actor, project_id, limit=100, offset=0)
        if members.total > 100 or len(candidates) > 1000:
            raise AccessError(422, "Recommendation context exceeds supported size")
        member_ids = {str(m.user_id) for m in members.items}
        for link in self.repository.project_teams(project_id):
            member_ids.update(
                str(m["user_id"])
                for m in self.repository.team_members(link["team_id"])
                if self.access.access_for(project, m["user_id"]).permissions
            )
        roles = [r.model_dump() for r in self.access.roles(actor, project_id).items]
        teams = [
            self.collaboration.get_team(actor, t["id"])
            for t in self.repository.teams(actor)
            if self.collaboration.team_access(actor, t)
        ]
        # Cost data is manager-only and explicit. Missing rates remain null, never estimates.
        allocations = self.repository.allocations(project_id=project_id)
        costs = [
            {
                "user_id": str(a["user_id"]),
                "weekly_hours": a["weekly_hours"],
                "hourly_rate": a["hourly_rate"],
                "currency": a["currency"],
            }
            for a in allocations
        ]
        context: dict[str, Any] = {
            "project": project.model_dump(mode="json"),
            "candidates": candidates,
            "members": sorted(member_ids),
            "roles": roles,
            "teams": json.loads(json.dumps(teams, default=str)),
            "allocations": costs,
            "constraints": constraints,
            "backlog_write_generation": external["lease_generation"],
            "work_items": work_items,
            "task_assignments": [
                {"item_id": item["id"], "user_id": item["assignee_id"], "status": item["status"]}
                for item in work_items
                if item["kind"] == "task" and item["assignee_id"] is not None
            ]
            if work_items is not None
            else None,
            "backlog_snapshot_status": "available" if work_items is not None else "not_requested",
            "access_usage": self.access_usage(actor, project_id, member_ids, constraints)
            if kind == "access_revocation"
            else {"status": "not_requested", "inactive_user_ids": []},
        }
        context["evidence"] = (
            ["project:" + str(project_id)]
            + ["profile:" + c["id"] for c in candidates]
            + ["team:" + str(t["id"]) for t in teams]
            + ["item:" + item["id"] for item in work_items or []]
            + ["activity:" + user_id for user_id in context["access_usage"]["inactive_user_ids"]]
        )
        return context

    def capture_external(self, actor: UUID, project_id: UUID, kind: str) -> dict[str, Any]:
        project = self.repository.project(project_id)
        self.access.require(project, actor, "project:members:manage")
        task_context = kind in {"roles", "teams", "skills_map", "training"}
        generation = None
        if task_context:
            self.access.require(project, actor, "backlog:read")
            if self.repository.active_leases(project_id):
                raise AccessError(409, "Backlog has an active write; retry after it finishes")
            generation = self.repository.lease_generation(project_id)
        self.repository.end_read()
        work_items = self.collaboration.backlog_items(project_id) if task_context else None
        directory = self.collaboration.directory()
        self.repository.end_read()
        return {"work_items": work_items, "directory": directory, "lease_generation": generation}

    def access_usage(
        self, actor: UUID, project_id: UUID, members: set[str], constraints: dict[str, Any]
    ) -> dict[str, Any]:
        project = self.repository.project(project_id)
        assert project is not None
        days = constraints.get("unused_days", self.inactivity_days)
        if type(days) is not int or not 1 <= days <= 3650:
            raise AccessError(422, "Invalid inactivity window")
        now = utc(self.collaboration.clock())
        cutoff = now - timedelta(days=days)
        rows = self.repository.observations(project_id)
        reports: list[dict[str, Any]] = []
        inactive: list[str] = []
        for user_id in sorted(members):
            user = UUID(user_id)
            if (
                user in {actor, project.owner_id}
                or not self.access.access_for(project, user).permissions
            ):
                continue
            observation = rows.get(user)
            known = observation is not None and observation[
                "access_signature"
            ] == self.repository.access_signature(project, user)
            if not known:
                reports.append(
                    {
                        "user_id": user_id,
                        "status": "unknown",
                        "observed_since": None,
                        "last_activity_at": None,
                    }
                )
                continue
            assert observation is not None
            since = utc(observation["observed_since"])
            last = utc(observation["last_activity_at"]) if observation["last_activity_at"] else None
            eligible = since <= cutoff and (last is None or last < cutoff)
            status = (
                "inactive"
                if eligible
                else "recent"
                if last is not None and last >= cutoff
                else "observing"
            )
            reports.append(
                {
                    "user_id": user_id,
                    "status": status,
                    "observed_since": since.isoformat(),
                    "last_activity_at": last.isoformat() if last else None,
                }
            )
            if eligible:
                inactive.append(user_id)
        return {
            "status": "available"
            if any(report["status"] != "unknown" for report in reports)
            else "unknown",
            "semantics": "authorized_activity_observed",
            "unused_days": days,
            "cutoff": cutoff.isoformat(),
            "users": reports,
            "inactive_user_ids": inactive,
        }

    def validate(self, kind: str, output: dict[str, Any], context: dict[str, Any]) -> None:
        users = {c["id"] for c in context["candidates"]}
        roles = {r["key"] for r in context["roles"]}
        teams = {str(t["id"]) for t in context["teams"]}
        known_skills = set(
            context["project"]["technology_stack"]
            + context["project"]["technical_requirements"]
            + context["project"]["soft_skills"]
        )
        known_skills.update(
            s["name"]
            for c in context["candidates"]
            for s in c.get("skills", [])
            if isinstance(s, dict) and isinstance(s.get("name"), str)
        )
        if not set(output["evidence"]).issubset(context["evidence"]) or not valid_suggestions(
            kind,
            output["suggestions"],
            users=users,
            members=set(
                context["access_usage"]["inactive_user_ids"]
                if kind == "access_revocation"
                else context["members"]
            ),
            teams=teams,
            roles=roles,
            owner=str(context["project"]["owner_id"]),
            known_skills=known_skills,
        ):
            raise AccessError(
                503, "Recommendation provider returned invalid suggestions or evidence"
            )

    def create(self, actor: UUID, project_id: UUID, draft: RecommendationDraft) -> dict[str, Any]:
        context = self.context(actor, project_id, draft.kind, draft.constraints)
        if draft.kind == "access_revocation" and not context["access_usage"]["inactive_user_ids"]:
            raise AccessError(409, "No access has a complete observed inactivity window")
        version = fingerprint(context)
        self.repository.end_read()
        result = self.generate(draft.kind, context)
        self.validate(draft.kind, result, context)
        latest = self.capture_external(actor, project_id, draft.kind)
        with self.repository.locked_project(project_id):
            if draft.kind == "access_revocation":
                self.repository.lock_observations(project_id)
            current = self.context(
                actor, project_id, draft.kind, draft.constraints, external=latest
            )
            if fingerprint(current) != version:
                raise AccessError(409, "Recommendation context changed")
            record = {
                "id": str(uuid4()),
                "project_id": str(project_id),
                "kind": draft.kind,
                "status": "pending",
                "version": 1,
                "created_at": utc(self.collaboration.clock()).isoformat(),
                **result,
                "context_version": version,
                "_constraints": draft.constraints,
            }
            self.repository.recommendation_save(record)
        return public(record)

    def list(self, actor: UUID, project_id: UUID, limit: int, offset: int) -> dict[str, Any]:
        self.access.require(self.repository.project(project_id), actor, "project:members:manage")
        rows = sorted(
            self.repository.recommendations(project_id),
            key=lambda r: (r["created_at"], r["id"]),
            reverse=True,
        )
        return {
            "items": [public(r) for r in rows[offset : offset + limit]],
            "total": len(rows),
            "limit": limit,
            "offset": offset,
        }

    def get(self, actor: UUID, project_id: UUID, recommendation_id: UUID) -> dict[str, Any]:
        self.access.require(self.repository.project(project_id), actor, "project:members:manage")
        row = next(
            (
                r
                for r in self.repository.recommendations(project_id)
                if r["id"] == str(recommendation_id)
            ),
            None,
        )
        if row is None:
            raise AccessError(404, "Recommendation unavailable")
        return public(row)

    def decide(
        self,
        actor: UUID,
        project_id: UUID,
        recommendation_id: UUID,
        expected_version: int,
        approve: bool,
    ) -> dict[str, Any]:
        conflict = False
        latest = None
        if approve:
            self.access.require(
                self.repository.project(project_id), actor, "project:members:manage"
            )
            pending = next(
                (
                    r
                    for r in self.repository.recommendations(project_id)
                    if r["id"] == str(recommendation_id)
                ),
                None,
            )
            if pending is not None and pending["status"] == "pending":
                latest = self.capture_external(actor, project_id, pending["kind"])
        with self.repository.locked_project(project_id) as project:
            self.access.require(project, actor, "project:members:manage")
            assert project is not None
            self.access.writable(project, administrative=True, revocation=not approve)
            record = next(
                (
                    dict(r)
                    for r in self.repository.recommendations(project_id)
                    if r["id"] == str(recommendation_id)
                ),
                None,
            )
            if record is None:
                raise AccessError(404, "Recommendation unavailable")
            target_status = "approved" if approve else "rejected"
            if record["status"] == target_status:
                return public(record)
            if record["version"] != expected_version or record["status"] != "pending":
                raise AccessError(409, "Recommendation version conflict")
            if approve:
                if latest is None:
                    raise AccessError(409, "Recommendation snapshot unavailable; retry")
                if record["kind"] == "access_revocation":
                    self.repository.lock_observations(project_id)
                current = self.context(
                    actor, project_id, record["kind"], record["_constraints"], external=latest
                )
                if fingerprint(current) != record["context_version"]:
                    record.update(status="expired", version=record["version"] + 1)
                    self.repository.recommendation_save(record)
                    conflict = True
                else:
                    self.validate(record["kind"], record, current)
                    recipients = self.apply(actor, project_id, record)
                    self.repository.outbox(
                        record,
                        recipients=recipients if record["kind"] == "teams" else None,
                        created_at=utc(self.collaboration.clock()),
                    )
            if not conflict:
                record.update(status=target_status, version=record["version"] + 1)
                self.repository.recommendation_save(record)
                self.repository.event(
                    project_id,
                    actor,
                    "recommendation." + target_status,
                    project.version,
                    {"recommendation_id": record["id"], "kind": record["kind"]},
                )
        if conflict:
            raise AccessError(409, "Recommendation context changed; generate a new draft")
        return public(record)

    def apply(self, actor: UUID, project_id: UUID, record: dict[str, Any]) -> set[UUID]:
        project = self.repository.project(project_id)
        assert project is not None
        recipients: set[UUID] = set()
        for suggestion in record["suggestions"]:
            kind = record["kind"]
            if kind == "roles":
                target = UUID(suggestion["user_id"])
                self.collaboration.require_active(target)
                draft = MembershipPatch(roles=suggestion["roles"])
                self.access.validate_roles(project, actor, draft)
                member = self.repository.member(project_id, target)
                merged = sorted(set((member.roles if member else []) + suggestion["roles"]))
                # Preserve existing expiry; recommended grants are approved explicitly.
                existing_grants = list(member.role_grants) if member else []
                if member:
                    legacy_expiry = (
                        utc(member.expires_at).isoformat() if member.expires_at else None
                    )
                    existing_grants += [
                        {"role": role, "expires_at": legacy_expiry}
                        for role in member.roles
                        if role not in {grant["role"] for grant in existing_grants}
                    ]
                grants = existing_grants + [
                    {"role": r, "expires_at": None}
                    for r in suggestion["roles"]
                    if r not in {g["role"] for g in existing_grants}
                ]
                value = Member(
                    user_id=target,
                    roles=merged,
                    expires_at=member.expires_at if member else None,
                    role_grants=grants,
                )
                self.repository.deny(project_id, target, False)
                if member:
                    self.repository.update_member(project_id, value)
                else:
                    self.repository.add_member(project_id, value)
                self.repository.change_state(project_id, actor, {}, "access.recommendation.roles")
            elif kind == "access_revocation":
                target = UUID(suggestion["user_id"])
                self.repository.delete_member(project_id, target)
                self.repository.deny(project_id, target, True)
                self.repository.invalidate(project_id, target)
                self.repository.change_state(
                    project_id, actor, {}, "access.recommendation.revocation"
                )
            elif kind == "teams":
                draft = MembershipPatch(roles=suggestion["roles"])
                self.access.validate_roles(project, actor, draft)
                if "team_id" in suggestion:
                    team_id = UUID(suggestion["team_id"])
                    self.collaboration.team_access(
                        actor, self.repository.team(team_id), manage=True
                    )
                else:
                    team_id = uuid4()
                    self.repository.team_save(
                        team_id,
                        {
                            "owner_id": actor,
                            "name": suggestion["name"],
                            "description": "",
                            "cost_center": None,
                            "created_at": utc(self.collaboration.clock()),
                            "version": 1,
                        },
                    )
                    self.repository.team_member_save(team_id, actor, {"is_manager": True})
                    for user_id in suggestion["user_ids"]:
                        target = UUID(user_id)
                        self.collaboration.require_active(target)
                        if target != actor:
                            self.repository.team_member_save(team_id, target, {"is_manager": False})
                previous = next(
                    (
                        link
                        for link in self.repository.project_teams(project_id)
                        if link["team_id"] == team_id
                    ),
                    None,
                )
                self.repository.link_team(
                    project_id,
                    team_id,
                    {
                        "roles": suggestion["roles"],
                        "expires_at": previous["expires_at"] if previous else None,
                    },
                )
                recipients.update(
                    member["user_id"]
                    for member in self.repository.team_members(team_id)
                    if self.access.access_for(project, member["user_id"]).permissions
                )
                self.repository.change_state(project_id, actor, {}, "access.recommendation.team")
            # skills_map and training record a human decision, never mutate profiles or permissions.

        return recipients
