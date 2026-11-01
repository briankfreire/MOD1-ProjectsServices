"""Guard architectural dependencies, including imports nested inside methods."""

import ast
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "src" / "projects_service"
LAYERS = {
    "domain": ("domain", "access_domain", "collaboration_domain", "recommendation_domain"),
    "application": ("service", "access_service", "collaboration_service", "recommendation_service"),
    "presentation": ("routes", "access_routes", "collaboration_routes"),
}
FORBIDDEN = {
    "domain": {
        "fastapi",
        "starlette",
        "sqlalchemy",
        "httpx",
        "httpx2",
        "projects_service.models",
        "projects_service.repository",
        "projects_service.access_repository",
        "projects_service.database",
        "projects_service.config",
        "projects_service.security",
        "projects_service.service",
        "projects_service.access_service",
        "projects_service.dependencies",
        "projects_service.routes",
        "projects_service.access_routes",
        "projects_service.app",
        "projects_service.cli",
        "projects_service.readiness",
        "projects_service.collaboration_service",
        "projects_service.recommendation_service",
        "projects_service.collaboration_repository",
        "projects_service.integrations",
        "projects_service.collaboration_routes",
    },
    "application": {
        "fastapi",
        "starlette",
        "sqlalchemy",
        "projects_service.models",
        "projects_service.database",
        "projects_service.dependencies",
        "projects_service.routes",
        "projects_service.access_routes",
    },
    "presentation": {
        "sqlalchemy",
        "projects_service.models",
        "projects_service.repository",
        "projects_service.access_repository",
        "projects_service.database",
    },
}


@pytest.mark.parametrize("layer", LAYERS)
def test_layer_import_boundaries(layer):
    violations = []
    for module in LAYERS[layer]:
        tree = ast.parse((SOURCE / f"{module}.py").read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            imports = []
            if isinstance(node, ast.Import):
                imports = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                if node.level:
                    base = ".".join(["projects_service", base]).rstrip(".")
                imports = [base] + [f"{base}.{a.name}" for a in node.names]
            for name in imports:
                if any(
                    name == banned or name.startswith(banned + ".") for banned in FORBIDDEN[layer]
                ):
                    violations.append(f"{module}:{node.lineno}: {name}")
            if (
                layer == "application"
                and isinstance(node, ast.Attribute)
                and node.attr == "session"
            ):
                violations.append(f"{module}:{node.lineno}: application accesses ORM session")
    assert not violations, "\n".join(violations)
