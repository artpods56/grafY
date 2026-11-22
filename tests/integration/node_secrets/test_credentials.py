import asyncio
from pathlib import Path
from typing import TypedDict
from uuid import UUID

import httpx
import pytest
from grafy_api.credentials import CredentialRateLimitError, CredentialService
from grafy_api.node_secrets import NodeSecretService
from grafy_api.services import application
from grafy_api.settings import Settings
from grafy_api.v1.routes.auth.dependencies import browser_actor, workspace_actor
from grafy_api.v1.routes.credentials.dependencies import credential_service
from grafy_api.v1.routes.node_secrets.dependencies import node_secret_service
from grafy_core.application.project_creation import MAIN_GRAPH_ID
from grafy_core.domain.credentials import (
    SharedCredentialBindingMode,
    UserCredentialOverrideMode,
)
from grafy_core.domain.errors import NotFoundError
from grafy_core.domain.identity import (
    User,
    Workspace,
    WorkspaceKind,
    WorkspaceMembership,
    WorkspaceRole,
)
from grafy_core.domain.runs import RunTarget
from grafy_core.egress import EgressRejectedError
from grafy_core.kernel.implementation_identity import RegistryImplementationDigests
from grafy_core.nodes import NodeExecutionContext
from grafy_core.ports.node_secrets import NodeSecretUnavailableError
from grafy_persistence.database import Database
from grafy_persistence.unit_of_work import SqlAlchemyUnitOfWork
from grafy_shared.config import AppConfig
from pydantic import SecretStr

from tests.integration.node_secrets.test_node_secrets import (
    EmptyInput,
    EmptyOutput,
    SecretTestConfig,
    SecretTestNode,
    _encryption_key,  # pyright: ignore[reportPrivateUsage]
    _secret_project,  # pyright: ignore[reportPrivateUsage]
    _secret_registry,  # pyright: ignore[reportPrivateUsage]
)
from tests.support.identity import TEST_USER_ID, WORKSPACE_ID, ActorSwitcher
from tests.testkit import (
    client_with_overrides,
    create_db_url,
    db,
    seed_shared_workspace,
    with_setting_values,
)

EDITOR = UUID(int=2)
OTHER = UUID(int=8)
ENDPOINT = "https://llm.example/v1"
VALUE = "explicit-personal-key"


class NodeAddress(TypedDict):
    workspace_id: UUID
    project_id: UUID
    graph_id: str
    node_id: str
    name: str


async def seed(database: Database) -> UUID:
    await seed_shared_workspace(database)
    async with SqlAlchemyUnitOfWork(database.sessions) as uow:
        await uow.identity.add_user(
            User(id=EDITOR, email="editor@example.test", display_name="Editor")
        )
        await uow.identity.add_workspace(
            Workspace(id=OTHER, slug="other", name="Other", kind=WorkspaceKind.SHARED)
        )
        await uow.identity.add_membership(
            WorkspaceMembership(
                workspace_id=WORKSPACE_ID, user_id=EDITOR, role=WorkspaceRole.EDITOR
            )
        )
        await uow.identity.add_membership(
            WorkspaceMembership(
                workspace_id=OTHER, user_id=TEST_USER_ID, role=WorkspaceRole.OWNER
            )
        )
        await uow.commit()
    return await _secret_project(database)


def services(database: Database) -> tuple[CredentialService, NodeSecretService]:
    registry = _secret_registry()

    def uow_factory() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(database.sessions)

    vault = CredentialService(
        unit_of_work_factory=uow_factory,
        plugin_registry=registry,
        encryption_key=_encryption_key(),
    )
    secrets = NodeSecretService(
        unit_of_work_factory=uow_factory,
        plugin_registry=registry,
        encryption_key=_encryption_key(),
        credentials=vault,
    )
    return vault, secrets


def settings_for(tmp_path: Path, database_url: str) -> Settings:
    return with_setting_values(
        Settings(
            app=AppConfig(
                public_origin="http://testserver",
                workspace=tmp_path,
                database_url=SecretStr(database_url),
            )
        ),
        credential_encryption_key=_encryption_key(),
    )


def test_credential_http_scopes_and_editor_binding(tmp_path: Path) -> None:
    database_url = create_db_url(tmp_path, "vault.sqlite3")

    async def exercise() -> None:
        async with db(database_url) as database:
            project_id = await seed(database)
            vault, secrets = services(database)
            switcher = ActorSwitcher(TEST_USER_ID)
            with client_with_overrides(
                settings=settings_for(tmp_path, database_url),
                overrides={
                    browser_actor: switcher.actor,
                    workspace_actor: switcher.actor,
                    credential_service: lambda: vault,
                    node_secret_service: lambda: secrets,
                },
            ) as client:
                personal = "/v1/me/credentials"
                shared = f"/v1/workspaces/{WORKSPACE_ID}/credentials"
                other = f"/v1/workspaces/{OTHER}/credentials"
                node = f"/v1/workspaces/{WORKSPACE_ID}/projects/{project_id}/graphs/{MAIN_GRAPH_ID}/nodes/llm/secrets/api_key"
                body = {
                    "label": "Example",
                    "provider_kind": "generic",
                    "value": VALUE,
                    "verify_config": {"base_url": ENDPOINT},
                }
                rejected = client.post(personal, json=body)
                assert rejected.status_code == 422
                assert rejected.json()["detail"]["can_save_unverified"] is True
                assert (
                    rejected.json()["detail"]["verification"]["status"] == "unsupported"
                )
                assert client.get(personal).json() == {"credentials": []}

                saved = client.post(personal, json={**body, "save_if_unverified": True})
                assert saved.status_code == 201
                assert saved.json()["verification_status"] == "unsupported"
                assert saved.json()["key_hint"] == "••••-key"
                assert VALUE not in saved.text
                personal_id = saved.json()["id"]
                saved_shared = client.post(shared, json={**body, "verify": False})
                assert saved_shared.status_code == 201
                shared_id = saved_shared.json()["id"]
                assert (
                    client.patch(
                        f"{other}/{shared_id}", json={"label": "Foreign"}
                    ).status_code
                    == 404
                )

                foreign = client.post(other, json={**body, "verify": False})
                assert foreign.status_code == 201
                assert (
                    client.put(
                        f"{node}/shared-binding",
                        json={
                            "mode": "credential",
                            "credential_id": foreign.json()["id"],
                            "expected_head_sequence": 0,
                        },
                    ).status_code
                    == 404
                )
                reverified = client.post(f"{shared}/{shared_id}/verify")
                assert reverified.status_code == 200
                assert reverified.json()["verification_status"] == "unsupported"
                assert (
                    client.get(shared).json()["credentials"][0]["verified_at"]
                    is not None
                )

                switcher.as_user(EDITOR)
                assert client.get(personal).json() == {"credentials": []}
                assert (
                    client.post(f"{personal}/{personal_id}/verify").status_code == 404
                )
                assert client.delete(f"{personal}/{personal_id}").status_code == 404
                assert client.post(shared, json=body).status_code == 403
                assert (
                    client.patch(
                        f"{shared}/{shared_id}", json={"label": "New"}
                    ).status_code
                    == 403
                )
                assert client.delete(f"{shared}/{shared_id}").status_code == 403
                assert client.get(shared).json()["credentials"][0]["id"] == shared_id
                assert (
                    client.put(
                        f"{node}/personal-selection",
                        json={"mode": "credential", "credential_id": personal_id},
                    ).status_code
                    == 404
                )
                binding = {
                    "mode": "credential",
                    "credential_id": shared_id,
                    "expected_head_sequence": 0,
                }
                applied = client.put(f"{node}/shared-binding", json=binding)
                assert applied.status_code == 200
                assert applied.json()["effective_source"] == "shared_credential"
                assert (
                    client.put(
                        f"{node}/shared-binding",
                        json={**binding, "expected_head_sequence": 1},
                    ).status_code
                    == 409
                )

                switcher.as_user(TEST_USER_ID)
                assert client.delete(f"{shared}/{shared_id}").status_code == 204
                status = client.get(
                    f"/v1/workspaces/{WORKSPACE_ID}/projects/{project_id}/node-secrets"
                )
                assert status.json()["secrets"][0]["shared_credential_missing"] is True
                assert status.json()["secrets"][0]["configured"] is False

    asyncio.run(exercise())


@pytest.mark.asyncio
async def test_personal_resolution_and_rotation_match_saved_endpoint(
    tmp_path: Path,
) -> None:
    async with db(create_db_url(tmp_path, "resolution.sqlite3")) as database:
        project_id = await seed(database)
        vault, secrets = services(database)
        address = NodeAddress(
            workspace_id=WORKSPACE_ID,
            project_id=project_id,
            graph_id=MAIN_GRAPH_ID,
            node_id="llm",
            name="api_key",
        )
        dependencies = {"base_url": ENDPOINT}
        await secrets.set_shared_binding(
            **address,
            mode=SharedCredentialBindingMode.PERSONAL,
            credential_id=None,
            actor_user_id=TEST_USER_ID,
            expected_head_sequence=0,
        )
        with pytest.raises(
            NodeSecretUnavailableError, match="requires a personal credential"
        ):
            await secrets.resolve_secret(
                **address, dependencies=dependencies, actor_user_id=EDITOR
            )

        first = await vault.create_personal(
            user_id=EDITOR,
            label="First",
            value=SecretStr(VALUE),
            provider_kind="generic",
            verify=False,
            verify_config=dependencies,
        )
        assert (
            await secrets.resolve_secret(
                **address, dependencies=dependencies, actor_user_id=EDITOR
            )
        ).get_secret_value() == VALUE
        second = await vault.create_personal(
            user_id=EDITOR,
            label="Second",
            value=SecretStr("another-key"),
            provider_kind="generic",
            verify=False,
            verify_config={"base_url": "https://other.example/v1"},
        )
        with pytest.raises(
            NodeSecretUnavailableError, match="Multiple personal credentials"
        ):
            await secrets.resolve_secret(
                **address, dependencies=dependencies, actor_user_id=EDITOR
            )
        assert (
            await secrets.cache_revision(**address, dependencies=dependencies)
            == "mode:personal"
        )

        for credential, expected in ((second, False), (first, True)):
            state = await secrets.set_personal_override(
                **address,
                mode=UserCredentialOverrideMode.CREDENTIAL,
                credential_id=credential.id,
                actor_user_id=EDITOR,
            )
            assert state.configured is expected
        with pytest.raises(NotFoundError):
            await vault.update_personal(
                user_id=TEST_USER_ID, credential_id=first.id, label="Foreign"
            )

        rotated = await vault.update_personal(
            user_id=EDITOR,
            credential_id=first.id,
            value=SecretStr("rotated-key"),
            verify=False,
        )
        assert rotated.updated_at > first.updated_at
        assert (
            await secrets.resolve_secret(
                **address, dependencies=dependencies, actor_user_id=EDITOR
            )
        ).get_secret_value() == "rotated-key"
        assert (
            not (
                await secrets.status(
                    WORKSPACE_ID, project_id, MAIN_GRAPH_ID, actor_user_id=TEST_USER_ID
                )
            )
            .secrets[0]
            .configured
        )

        await vault.delete_personal(EDITOR, first.id)
        state = (
            await secrets.status(
                WORKSPACE_ID, project_id, MAIN_GRAPH_ID, actor_user_id=EDITOR
            )
        ).secrets[0]
        assert state.personal_override_mode == "none"


@pytest.mark.asyncio
async def test_run_resolves_the_starters_personal_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = create_db_url(tmp_path, "credential-run.sqlite3")
    received: asyncio.Future[tuple[UUID | None, str]] = (
        asyncio.get_running_loop().create_future()
    )

    async def read_key(
        context: NodeExecutionContext, config: SecretTestConfig, inputs: EmptyInput
    ) -> EmptyOutput:
        key = await context.secrets.require("api_key")
        received.set_result((context.actor_user_id, key.get_secret_value()))
        return EmptyOutput()

    async def run_node(
        self: SecretTestNode,
        context: NodeExecutionContext,
        config: SecretTestConfig,
        inputs: EmptyInput,
    ) -> EmptyOutput:
        return await read_key(context, config, inputs)

    monkeypatch.setattr(SecretTestNode, "run", run_node)
    monkeypatch.setattr(application, "build_application_registry", _secret_registry)

    def digest_fixture(
        registry: object, *, uv_lock: Path
    ) -> RegistryImplementationDigests:
        # The test-only node is not a family package in the production lock.
        return RegistryImplementationDigests(
            {("test.secret-node", 1): "grafy_core.nodes"},
            uv_lock=uv_lock,
        )

    monkeypatch.setattr(RegistryImplementationDigests, "from_registry", digest_fixture)
    async with db(database_url) as database:
        project_id = await seed(database)
        resources = await application.build_app_resources(
            settings=settings_for(tmp_path, database_url),
            database=database,
            owner_lease=None,
        )
        try:
            personal = await resources.credentials.create_personal(
                user_id=EDITOR,
                provider_kind="generic",
                label="Run key",
                value=SecretStr(VALUE),
                verify=False,
                verify_config={"base_url": ENDPOINT},
            )
            await resources.node_secrets.set_personal_override(
                workspace_id=WORKSPACE_ID,
                project_id=project_id,
                graph_id=MAIN_GRAPH_ID,
                node_id="llm",
                name="api_key",
                mode=UserCredentialOverrideMode.CREDENTIAL,
                credential_id=personal.id,
                actor_user_id=EDITOR,
            )
            await resources.runs.start(
                workspace_id=WORKSPACE_ID,
                project_id=project_id,
                graph_id=MAIN_GRAPH_ID,
                targets=[RunTarget(node_id="llm")],
                started_by_user_id=EDITOR,
            )
            assert await asyncio.wait_for(received, timeout=3) == (EDITOR, VALUE)
        finally:
            await resources.cleanup()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        (200, "valid"),
        (401, "invalid"),
        (404, "unreachable"),
        ("network", "unreachable"),
        ("egress", "egress_blocked"),
    ],
)
async def test_openai_verifier_returns_sanitized_results(
    outcome: int | str, expected: str
) -> None:
    registry = application.build_application_registry()

    def transport(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://api.openai.com/v1/models"
        assert request.headers["Authorization"] == f"Bearer {VALUE}"
        if outcome == "egress":
            raise EgressRejectedError(VALUE)
        if outcome == "network":
            raise httpx.ReadTimeout(VALUE)
        assert isinstance(outcome, int)
        return httpx.Response(outcome, json={"data": [{}, {}], "error": VALUE})

    def unused_database() -> SqlAlchemyUnitOfWork:
        raise AssertionError("Candidate verification should not use persistence")

    vault = CredentialService(
        unit_of_work_factory=unused_database,
        plugin_registry=registry,
        encryption_key=_encryption_key(),
        http_client_factory=lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(transport)
        ),
    )
    result = await vault.verify_candidate(
        provider_kind="openai_compatible", value=SecretStr(VALUE)
    )
    assert result.status == expected
    assert VALUE not in repr(result)
    assert result.account_hint == (
        "2 models available" if expected == "valid" else None
    )

    unsupported = await vault.verify_candidate(
        provider_kind="reducto", value=SecretStr(VALUE)
    )
    assert unsupported.status == "unsupported"


def test_verification_limit_expires_per_user() -> None:
    elapsed = 0.0

    def clock() -> float:
        return elapsed

    def unused_database() -> SqlAlchemyUnitOfWork:
        raise AssertionError("Rate limiting should not use persistence")

    vault = CredentialService(
        unit_of_work_factory=unused_database,
        plugin_registry=_secret_registry(),
        encryption_key=_encryption_key(),
        clock=clock,
        verify_limit=2,
    )
    vault.check_verify_rate(TEST_USER_ID)
    vault.check_verify_rate(TEST_USER_ID)
    vault.check_verify_rate(EDITOR)
    with pytest.raises(CredentialRateLimitError):
        vault.check_verify_rate(TEST_USER_ID)
    elapsed = 60.0
    vault.check_verify_rate(TEST_USER_ID)
