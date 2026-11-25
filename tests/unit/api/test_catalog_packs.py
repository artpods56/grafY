import asyncio
from dataclasses import replace
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import SecretStr

from grafy_api.catalog_packs import PACKS, CatalogPolicy
from grafy_api.main import create_app
from grafy_api.services.families import build_application_registry
from grafy_api.settings import Settings
from grafy_api.v1.routes.auth.dependencies import workspace_actor
from grafy_core.domain.identity import (
    PAT_ALLOWED_CAPABILITIES,
    ActorContext,
    WorkspaceMembership,
    WorkspacePatPrincipal,
    WorkspaceRole,
)
from grafy_core.nodes import ServiceContractKey
from grafy_persistence.database import create_database
from grafy_persistence.unit_of_work import SqlAlchemyUnitOfWork
from grafy_shared.config import AppConfig, CatalogConfig
from grafy_shared.config.catalog import CatalogOverrides
from tests.support.factories.identity import IdentitySeeder
from tests.support.identity import (
    TEST_USER_ID,
    WORKSPACE_ID,
    browser_actor_override,
    create_schema,
    workspace_api_path,
)
from tests.testkit import client_with_overrides


@pytest.mark.parametrize(
    ("content", "error"),
    [
        ("[defaults", "GRAFY_CATALOG_CONFIG"),
        ('[packs]\nai = "false"', "valid boolean"),
        ('[defaults]\nworkspace_packs = ["typo"]', "unknown packs"),
        ("[packs]\ntypo = false", "unknown packs"),
        ("[packs]\nessentials = false", "cannot disable always-on"),
        ('[operators]\n"typo.node" = true', "unknown operators"),
    ],
)
def test_invalid_catalog_file_fails_app_composition(
    tmp_path: Path, content: str, error: str
) -> None:
    path = tmp_path / "catalog.toml"
    path.write_text(content)
    with pytest.raises(ValueError, match=error):
        create_app(_settings(tmp_path, path))


def _settings(tmp_path: Path, path: Path) -> Settings:
    return Settings(
        app=AppConfig(
            workspace=tmp_path / "workspace",
            database_url=SecretStr(
                f"sqlite+aiosqlite:///{tmp_path / 'catalog.sqlite3'}"
            ),
        ),
        catalog=CatalogConfig(catalog_config=path),
    )


def test_pack_definitions_cover_the_registry_and_validate_references() -> None:
    registry = build_application_registry()
    overrides = CatalogOverrides()
    policy = CatalogPolicy(registry, overrides)
    assert len(registry.nodes) == 42
    assert policy.default_workspace_pack_slugs == ("essentials", "document_ocr")
    assert [
        (p.definition.slug, p.operator_count, p.provider_count) for p in policy.packs
    ] == [
        ("essentials", 8, 0),
        ("document_ocr", 2, 3),
        ("ai", 4, 0),
        ("maps", 9, 0),
        ("map_toponyms", 10, 3),
        ("label_studio", 2, 0),
        ("subgraphs", 2, 0),
    ]
    with pytest.raises(ValueError, match="Duplicate catalog pack slug"):
        CatalogPolicy(registry, overrides, (*PACKS, PACKS[0]))
    with pytest.raises(ValueError, match="unknown operators"):
        CatalogPolicy(registry, overrides, (replace(PACKS[0], operators=("missing",)),))
    with pytest.raises(ValueError, match="unknown service contract"):
        CatalogPolicy(
            registry,
            overrides,
            (
                replace(
                    PACKS[0], include_providers_for=(ServiceContractKey("missing", 1),)
                ),
            ),
        )
    with pytest.raises(ValueError, match="has no catalog pack"):
        CatalogPolicy(registry, overrides, PACKS[:-1])


def test_pack_subscriptions_change_discovery_without_omitting_nodes(
    tmp_path: Path,
) -> None:
    path = tmp_path / "catalog.toml"
    path.write_text(
        '[defaults]\nworkspace_packs = ["ai"]\n'
        "[packs]\nlabel_studio = false\n"
        '[operators]\n"ocr.filter_tiff_jev" = false\n'
    )
    settings = _settings(tmp_path, path)
    database_url = settings.app.resolved_database_url
    asyncio.run(create_schema(database_url))

    async def seed_other_workspace() -> tuple[UUID, UUID]:
        database = create_database(database_url)
        try:
            seeder = IdentitySeeder(lambda: SqlAlchemyUnitOfWork(database.sessions))
            viewer = await seeder.user()
            other = await seeder.workspace(slug="other")
            await seeder.membership(user=viewer, workspace=other)
            async with SqlAlchemyUnitOfWork(database.sessions) as uow:
                await uow.identity.add_membership(
                    WorkspaceMembership(
                        workspace_id=WORKSPACE_ID,
                        user_id=viewer.id,
                        role=WorkspaceRole.VIEWER,
                    )
                )
                await uow.workspace_packs.disable(WORKSPACE_ID, "essentials")
                await uow.commit()
            return viewer.id, other.id
        finally:
            await database.dispose()

    viewer_id, other_id = asyncio.run(seed_other_workspace())
    actor: ActorContext | WorkspacePatPrincipal = browser_actor_override()
    with client_with_overrides(
        settings=settings, overrides={workspace_actor: lambda: actor}
    ) as client:
        packs_url = workspace_api_path("/packs")
        nodes_url = workspace_api_path("/nodes")
        packs = client.get(packs_url).json()
        assert [pack["slug"] for pack in packs] == [
            "essentials",
            "document_ocr",
            "ai",
            "maps",
            "map_toponyms",
            "subgraphs",
        ]
        assert [pack["slug"] for pack in packs if pack["subscribed"]] == [
            "essentials",
            "document_ocr",
        ]

        def get_nodes():
            response = client.get(nodes_url)
            assert response.status_code == 200
            return {node["operator_id"]: node for node in response.json()["nodes"]}

        before = get_nodes()
        assert len(before) == 42
        assert before["table.import"]["catalog_visible"]
        assert before["mistral.ocr.provider"]["catalog_visible"]
        assert not before["text.input"]["catalog_visible"]
        assert before["text.input"]["pack_slugs"] == ["ai", "subgraphs"]

        assert (
            client.put(
                f"{packs_url}/essentials", json={"subscribed": False}
            ).status_code
            == 400
        )
        for slug in ("label_studio", "typo"):
            assert (
                client.put(f"{packs_url}/{slug}", json={"subscribed": True}).status_code
                == 404
            )
        assert (
            client.put(
                f"{packs_url}/ai",
                json={"subscribed": True, "workspace_id": str(WORKSPACE_ID)},
            ).status_code
            == 422
        )
        for slug, subscribed in (
            ("ai", True),
            ("ai", True),
            ("map_toponyms", True),
            ("document_ocr", False),
        ):
            response = client.put(
                f"{packs_url}/{slug}", json={"subscribed": subscribed}
            )
            assert response.status_code == 200, response.text
            assert response.json()["subscribed"] is subscribed

        after = get_nodes()
        assert after.keys() == before.keys()
        assert all(node["runnable"] for node in after.values())
        assert after["text.input"]["catalog_visible"]
        assert after["ocr.craft_provider"]["catalog_visible"]
        assert not after["ocr.filter_tiff_jev"]["catalog_visible"]
        assert not after["ocr.export_label_studio"]["catalog_visible"]
        assert not after["ocr.read_document"]["catalog_visible"]
        assert not after["mistral.ocr.provider"]["catalog_visible"]

        actor = ActorContext(user_id=viewer_id)
        assert client.get(packs_url).status_code == 200
        assert (
            client.put(f"{packs_url}/ai", json={"subscribed": False}).status_code == 403
        )
        actor = WorkspacePatPrincipal(
            actor=ActorContext(user_id=TEST_USER_ID),
            token_id=UUID(int=99),
            workspace_id=WORKSPACE_ID,
            capabilities=PAT_ALLOWED_CAPABILITIES,
        )
        assert client.get(packs_url).status_code == 200
        assert (
            client.put(f"{packs_url}/ai", json={"subscribed": False}).status_code == 403
        )
        actor = browser_actor_override()
        other_packs_url = f"/v1/workspaces/{other_id}/packs"
        assert client.get(other_packs_url).status_code == 404
        assert (
            client.put(f"{other_packs_url}/ai", json={"subscribed": True}).status_code
            == 404
        )
        actor = ActorContext(user_id=viewer_id)
        assert [
            pack["slug"]
            for pack in client.get(other_packs_url).json()
            if pack["subscribed"]
        ] == [
            "essentials",
            "document_ocr",
        ]
