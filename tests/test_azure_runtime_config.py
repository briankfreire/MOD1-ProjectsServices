"""App-scoped release patches must preserve security, data and routing."""

import copy
import importlib.util
import json
from pathlib import Path

import pytest


def module():
    path = Path(__file__).parents[1] / "scripts/azure_runtime_config.py"
    assert path.is_file(), "Missing app-scoped runtime release helper"
    spec = importlib.util.spec_from_file_location("azure_runtime_config", path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def app(service="backlog"):
    return {
        "location": "brazilsouth",
        "properties": {
            "managedEnvironmentId": "/keep/environment",
            "configuration": {
                "activeRevisionsMode": "Single",
                "ingress": {"fqdn": "keep.invalid"},
                "registries": [{"server": "registrytest.azurecr.io"}],
                "secrets": [
                    {
                        "name": "database-url",
                        "keyVaultUrl": "https://vault.invalid/db",
                        "identity": "/keep/identity",
                    },
                    {"name": "native-old"},
                ],
            },
            "template": {
                "revisionSuffix": "old",
                "volumes": [{"name": "jwt", "storageType": "Secret"}],
                "scale": {"minReplicas": 0, "maxReplicas": 1},
                "containers": [
                    {
                        "name": "api",
                        "image": "registrytest.azurecr.io/" + service + "@sha256:" + "a" * 64,
                        "resources": {"cpu": 0.5, "memory": "1Gi"},
                        "probes": [{"type": "Readiness"}],
                        "volumeMounts": [{"volumeName": "jwt", "mountPath": "/mnt/secrets"}],
                        "env": [
                            {"name": "DATABASE_URL", "secretRef": "database-url"},
                            {"name": "DATABASE_SCHEMA", "value": service},
                            {
                                "name": "CORS_ORIGINS",
                                "value": json.dumps(
                                    ["https://frontend.invalid", "http://localhost:5173"]
                                ),
                            },
                            {"name": "JWT_ISSUER", "value": "https://issuer.invalid"},
                            {"name": "MFA_ENCRYPTION_KEY", "secretRef": "mfa-encryption-key"},
                        ],
                    }
                ],
            },
        },
    }


def image(service):
    return "registrytest.azurecr.io/" + service + "@sha256:" + "b" * 64


def test_patch_preserves_cors_jwt_mounts_ingress_and_original_object():
    helper = module()
    before = app()
    original = copy.deepcopy(before)
    patch = helper.build_runtime_patch(
        before, image("backlog"), service="backlog", enable_notifications=True
    )
    assert before == original
    assert set(patch) == {"location", "properties"} and set(patch["properties"]) == {"template"}
    template = patch["properties"]["template"]
    assert "revisionSuffix" not in template
    api = template["containers"][0]
    env = {v["name"]: v for v in api["env"]}
    assert env["CORS_ORIGINS"] == before["properties"]["template"]["containers"][0]["env"][2]
    assert env["JWT_ISSUER"]["value"] == "https://issuer.invalid"
    assert env["MFA_ENCRYPTION_KEY"]["secretRef"] == "mfa-encryption-key"
    assert (
        api["volumeMounts"] == original["properties"]["template"]["containers"][0]["volumeMounts"]
    )
    assert env["AI_PROVIDER"]["value"] == "gemini"
    assert env["GEMINI_API_KEY"] == {"name": "GEMINI_API_KEY", "secretRef": "gemini-api-key"}


def test_backlog_worker_is_private_uses_same_image_and_keeps_queue_alive():
    helper = module()
    patch = helper.build_runtime_patch(
        app(), image("backlog"), service="backlog", enable_notifications=True
    )
    t = patch["properties"]["template"]
    assert t["scale"] == {"minReplicas": 1, "maxReplicas": 1}
    worker = t["containers"][1]
    assert worker["name"] == "module6-worker" and worker["image"] == image("backlog")
    assert worker["command"] == ["python", "-m", "backlog_service.module6_cli"]
    assert worker["args"][0] == "run" and "probes" not in worker
    env = {v["name"]: v for v in worker["env"]}
    assert set(env) == {
        "DATABASE_URL",
        "DATABASE_SCHEMA",
        "MODULE6_KEY",
        "MODULE6_ENABLED",
        "MODULE6_SOURCE",
    }
    assert env["MODULE6_SOURCE"]["value"] == "backlog"
    again = helper.build_runtime_patch(
        {**app(), "properties": {**app()["properties"], "template": t}},
        image("backlog"),
        service="backlog",
        enable_notifications=True,
    )
    assert len(again["properties"]["template"]["containers"]) == 2


def test_projects_notifications_stay_off_without_agreed_source():
    helper = module()
    t = helper.build_runtime_patch(app("projects"), image("projects"), service="projects")[
        "properties"
    ]["template"]
    assert len(t["containers"]) == 1 and t["scale"]["minReplicas"] == 0
    env = {v["name"]: v for v in t["containers"][0]["env"]}
    assert env["MODULE6_ENABLED"]["value"] == "false"
    assert "MODULE6_SOURCE" not in env
    with pytest.raises(ValueError):
        helper.build_runtime_patch(
            app("projects"), image("projects"), service="projects", enable_notifications=True
        )


def test_projects_worker_uses_explicit_module1_source_and_own_schema():
    helper = module()
    before = app("projects")
    patch = helper.build_runtime_patch(
        before,
        image("projects"),
        service="projects",
        enable_notifications=True,
        notification_source="backlog",
    )
    template = patch["properties"]["template"]
    api, worker = template["containers"]
    api_env = {v["name"]: v for v in api["env"]}
    worker_env = {v["name"]: v for v in worker["env"]}
    assert api_env["MODULE6_ENABLED"]["value"] == "true"
    assert api_env["MODULE6_SOURCE"]["value"] == "backlog"
    assert worker["command"] == ["python", "-m", "projects_service.module6_cli"]
    assert worker["image"] == image("projects") and "probes" not in worker
    assert worker_env["DATABASE_SCHEMA"]["value"] == "projects"
    assert worker_env["DATABASE_URL"]["secretRef"] == "database-url"
    assert worker_env["MODULE6_KEY"]["secretRef"] == "module6-key"
    assert set(worker_env) == {
        "DATABASE_URL",
        "DATABASE_SCHEMA",
        "MODULE6_KEY",
        "MODULE6_ENABLED",
        "MODULE6_SOURCE",
    }
    assert template["scale"]["minReplicas"] == 1
    assert api_env["CORS_ORIGINS"] == before["properties"]["template"]["containers"][0]["env"][2]
    again = helper.build_runtime_patch(
        {**before, "properties": {**before["properties"], "template": template}},
        image("projects"),
        service="projects",
        enable_notifications=True,
        notification_source="backlog",
    )
    assert len(again["properties"]["template"]["containers"]) == 2


@pytest.mark.parametrize("source", ["github", "projects", "modulo1", ""])
def test_projects_release_refuses_unselected_source(source):
    with pytest.raises(ValueError):
        module().build_runtime_patch(
            app("projects"),
            image("projects"),
            service="projects",
            enable_notifications=True,
            notification_source=source,
        )


def test_identity_cannot_publish_project_wide_notifications():
    with pytest.raises(ValueError):
        module().build_runtime_patch(
            app("identity"),
            image("identity"),
            service="identity",
            enable_notifications=True,
            notification_source="backlog",
            resend_from="Example <noreply@ckenzo.me>",
        )


def test_disabling_projects_stops_its_worker_and_preserves_api_configuration():
    helper = module()
    before = app("projects")
    enabled = helper.build_runtime_patch(
        before,
        image("projects"),
        service="projects",
        enable_notifications=True,
        notification_source="backlog",
    )
    current = {**before, "properties": {**before["properties"], **enabled["properties"]}}
    disabled = helper.build_runtime_patch(current, image("projects"), service="projects")
    containers = disabled["properties"]["template"]["containers"]
    assert [c["name"] for c in containers] == ["api"]
    env = {v["name"]: v for v in containers[0]["env"]}
    assert env["MODULE6_ENABLED"]["value"] == "false"
    assert env["CORS_ORIGINS"] == before["properties"]["template"]["containers"][0]["env"][2]
    assert env["DATABASE_URL"]["secretRef"] == "database-url"


def test_identity_sender_and_gemini_are_backend_only_and_rsa_is_preserved():
    helper = module()
    before = app("identity")
    t = helper.build_runtime_patch(
        before, image("identity"), service="identity", resend_from="Example <noreply@ckenzo.me>"
    )["properties"]["template"]
    env = {v["name"]: v for v in t["containers"][0]["env"]}
    assert env["RESEND_FROM"]["value"] == "Example <noreply@ckenzo.me>"
    assert t["volumes"] == before["properties"]["template"]["volumes"]
    assert env["LOCAL_MAILBOX_ENABLED"]["value"] == "false"


@pytest.mark.parametrize(
    "bad_image",
    [
        "registrytest.azurecr.io/backlog:latest",
        "evil.azurecr.io/backlog@sha256:" + "b" * 64,
        "registrytest.azurecr.io/projects@sha256:" + "b" * 64,
    ],
)
def test_only_owned_registry_and_matching_immutable_repository_are_accepted(bad_image):
    with pytest.raises(ValueError):
        module().build_runtime_patch(app(), bad_image, service="backlog", enable_notifications=True)


def test_unexpected_sidecar_aborts_instead_of_overwriting_it():
    before = app()
    before["properties"]["template"]["containers"].append({"name": "unrelated", "image": "keep"})
    with pytest.raises(ValueError):
        module().build_runtime_patch(
            before, image("backlog"), service="backlog", enable_notifications=True
        )


def test_secret_patch_preserves_native_and_keyvault_secrets():
    helper = module()
    before = app()
    patch = helper.build_secret_patch(
        before, [{"name": "native-old", "value": "keep-native"}], {"gemini-api-key": "synthetic"}
    )
    assert set(patch["properties"]) == {"configuration"}
    values = {s["name"]: s for s in patch["properties"]["configuration"]["secrets"]}
    assert values["database-url"]["keyVaultUrl"] == "https://vault.invalid/db"
    assert values["native-old"]["value"] == "keep-native"
    assert values["gemini-api-key"]["value"] == "synthetic"
    with pytest.raises(ValueError):
        helper.build_secret_patch(before, [], {"gemini-api-key": "synthetic"})


@pytest.mark.parametrize("service", ["backlog", "projects"])
def test_main_applies_scoped_secrets_before_revision_and_does_not_log_values(
    monkeypatch, capsys, service
):
    from contextlib import contextmanager

    helper = module()
    current = app(service)
    current["properties"]["provisioningState"] = "Succeeded"
    patches = []
    for name, value in {
        "AZURE_RESOURCE_GROUP": "mod1",
        "AZURE_CONTAINER_APP": "mod1-" + service,
        "IMAGE_REPOSITORY": service,
        "IMAGE_REFERENCE": image(service),
        "GEMINI_API_KEY": "synthetic-private-gemini",
        "MODULE6_KEY": "synthetic-private-module6",
        "MODULE6_ENABLED": "true",
        "MODULE6_SOURCE": "backlog",
        "GITHUB_RUN_ID": "123",
        "GITHUB_RUN_ATTEMPT": "1",
    }.items():
        monkeypatch.setenv(name, value)

    def azure(*args):
        if args[:2] == ("account", "show"):
            return {"id": "11111111-1111-4111-8111-111111111111"}
        if "post" in args:
            return {"value": [{"name": "native-old", "value": "private-native"}]}
        return copy.deepcopy(current)

    def apply(url, payload):
        assert "containerApps/mod1-" + service + "?" in url
        patches.append(copy.deepcopy(payload))
        for key, value in payload["properties"].items():
            current["properties"].setdefault(key, {}).update(copy.deepcopy(value))
        if "template" in payload["properties"]:
            current["properties"].update(
                latestRevisionName="mod1-" + service + "--rel-123-1",
                latestReadyRevisionName="mod1-" + service + "--rel-123-1",
            )
            current["properties"]["configuration"]["ingress"]["fqdn"] = (
                "mod1-" + service + ".example.azurecontainerapps.io"
            )

    @contextmanager
    def health(*args, **kwargs):
        class Response:
            status = 200

        yield Response()

    monkeypatch.setattr(helper, "azure", azure)
    monkeypatch.setattr(helper, "apply_patch", apply)
    monkeypatch.setattr(helper, "urlopen", health)
    helper.main()
    assert [set(p["properties"]) for p in patches] == [{"configuration"}, {"template"}]
    result = json.loads(capsys.readouterr().out)
    assert result["ready_revision"] == "mod1-" + service + "--rel-123-1"
    assert result["notifications_enabled"]
    assert "module6-key" in {
        v["name"] for v in patches[0]["properties"]["configuration"]["secrets"]
    }
    assert not any(
        value in str(result)
        for value in ["synthetic-private-gemini", "synthetic-private-module6", "private-native"]
    )


def test_changed_template_aborts_before_overwriting_concurrent_changes(monkeypatch):
    helper = module()
    before = app()
    for name, value in {
        "AZURE_RESOURCE_GROUP": "mod1",
        "AZURE_CONTAINER_APP": "mod1-backlog",
        "IMAGE_REPOSITORY": "backlog",
        "IMAGE_REFERENCE": image("backlog"),
        "GEMINI_API_KEY": "synthetic",
        "MODULE6_KEY": "synthetic",
    }.items():
        monkeypatch.setenv(name, value)

    def azure(*args):
        if args[:2] == ("account", "show"):
            return {"id": "11111111-1111-4111-8111-111111111111"}
        if "post" in args:
            return {"value": [{"name": "native-old", "value": "private-native"}]}
        return copy.deepcopy(before)

    calls = []

    def changed(url):
        after = copy.deepcopy(before)
        after["properties"]["template"]["scale"]["minReplicas"] = 2
        return after

    monkeypatch.setattr(helper, "azure", azure)
    monkeypatch.setattr(helper, "apply_patch", lambda url, payload: calls.append(payload))
    monkeypatch.setattr(helper, "wait_provisioned", changed)
    with pytest.raises(RuntimeError, match="concurrently"):
        helper.main()
    assert len(calls) == 1 and "template" not in calls[0]["properties"]


def test_multiple_revision_traffic_mode_aborts_before_release_patch():
    before = app()
    before["properties"]["configuration"]["activeRevisionsMode"] = "Multiple"
    with pytest.raises(ValueError, match="single-revision"):
        module().build_runtime_patch(
            before, image("backlog"), service="backlog", enable_notifications=True
        )
