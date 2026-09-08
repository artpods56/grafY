from hashlib import sha256
from pathlib import Path

import pytest
from typing_extensions import override

from grafy_api.plugins.runtime.admission import isolated_release_admission
from grafy_api.plugins.runtime.egress import (
    PluginEgressBrokerPolicy,
    PluginEgressDestination,
)
from grafy_api.plugins.runtime.network_policy import legacy_network_policy
from grafy_api.plugins.profiles import runtime_profile
from grafy_api.plugins.publication.oci import PluginOciImageBuilder
from grafy_api.plugins.publication.workflow import SystemPluginPublicationWorkflow
from grafy_api.plugins.publication.source import (
    PluginPublishingError,
    VerifiedPluginCandidate,
)
from grafy_api.system_host_bindings import SystemHostPluginBinding
from grafy_api.system_plugin_inventory import (
    CHECKED_IN_SYSTEM_PLUGIN_INVENTORY_PATH,
    SystemPluginInventory,
    load_system_plugin_inventory,
)
from grafy_core.application.plugin_releases import PluginReleaseService
from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_core.domain.plugin_releases import (
    PlatformPluginActor,
    PluginCapabilityManifest,
    PluginCatalogManifest,
    PluginExecutionPolicy,
    PluginNodeContract,
    PluginNodeHttpEgressContract,
    PluginReleaseError,
    PluginReleaseScope,
    PluginRuntimeArtifact,
    plugin_contract_digest,
)
from grafy_persistence.database import create_database
from grafy_persistence.unit_of_work import SqlAlchemyUnitOfWork
from grafy_storage import LocalFileObjectStore
from tests.support.identity import TEST_USER_ID, WORKSPACE_ID, create_schema


class RecordingSystemImageBuilder(PluginOciImageBuilder):
    def __init__(self) -> None:
        self.build_count = 0
        self.loader_targets: list[str] = []

    @override
    async def build_and_store(
        self,
        *,
        candidate: VerifiedPluginCandidate,
    ) -> PluginRuntimeArtifact:
        self.build_count += 1
        self.loader_targets.append(candidate.loader_target)
        return PluginRuntimeArtifact(
            object_key=(
                f"plugin-releases/{candidate.catalog.slug}/runtime/"
                f"{candidate.source_digest}.oci.tar"
            ),
            archive_digest=candidate.source_digest,
            manifest_digest=plugin_contract_digest(candidate.catalog),
            config_digest="a" * 64,
        )


_LLM_CAPABILITIES = (
    PluginRuntimeCapability.NETWORK_EGRESS,
    PluginRuntimeCapability.NODE_SECRETS,
)


def _catalog(
    *,
    slug: str = "external.llm",
    operator_id: str = "llm.openai_compatible.chat_completion",
    required_capabilities: tuple[PluginRuntimeCapability, ...] = _LLM_CAPABILITIES,
) -> PluginCatalogManifest:
    http_egress = None
    if PluginRuntimeCapability.NETWORK_EGRESS in set(required_capabilities):
        http_egress = PluginNodeHttpEgressContract(configured_inputs=("base_url",))
    return PluginCatalogManifest(
        slug=slug,
        title=slug,
        nodes=(
            PluginNodeContract(
                operator_id=operator_id,
                operator_version=1,
                title="Echo",
                description="Echo a value.",
                config_schema={"type": "object"},
                input_schema={"type": "object"},
                output_schema={"type": "object"},
                inputs=(),
                outputs=(),
                required_capabilities=required_capabilities,
                http_egress=http_egress,
            ),
        ),
    )


def _verified(
    source: bytes,
    *,
    catalog: PluginCatalogManifest | None = None,
    capabilities: PluginCapabilityManifest | None = None,
    loader_target: str = "grafy_plugin_llm.plugin:LLM",
) -> VerifiedPluginCandidate:
    release_catalog = catalog or _catalog()
    return VerifiedPluginCandidate(
        catalog=release_catalog,
        capabilities=capabilities
        or PluginCapabilityManifest(
            capabilities=release_catalog.nodes[0].required_capabilities
        ),
        loader_target=loader_target,
        source_archive=source,
        lock_digest=sha256(b"lock").hexdigest(),
        runtime_profile="python-uv",
    )


def _workflow(
    image_builder: RecordingSystemImageBuilder,
    releases: PluginReleaseService,
    inventory: SystemPluginInventory,
    *,
    bindings: tuple[SystemHostPluginBinding, ...] = (),
) -> SystemPluginPublicationWorkflow:
    destination = PluginEgressDestination.parse("https://api.openai.com:443")
    return SystemPluginPublicationWorkflow(
        image_builder,
        releases,
        isolated_release_admission(
            profile=runtime_profile("python-uv"),
            egress_policy=PluginEgressBrokerPolicy(
                broker_image="registry.example/grafy-egress@sha256:" + "a" * 64,
                destinations=(destination,),
            ),
            network_policy=legacy_network_policy(
                http_destinations=(destination,),
            ),
            system_host_bindings=bindings,
        ),
        inventory,
    )


@pytest.mark.asyncio
async def test_system_publication_stages_then_explicitly_promotes_and_rolls_back(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'system.sqlite3'}"
    await create_schema(database_url)
    database = create_database(database_url)
    releases = PluginReleaseService(
        lambda: SqlAlchemyUnitOfWork(database.sessions),
        LocalFileObjectStore(tmp_path / "objects"),
        bucket="plugins",
    )
    image_builder = RecordingSystemImageBuilder()
    inventory = load_system_plugin_inventory(CHECKED_IN_SYSTEM_PLUGIN_INVENTORY_PATH)
    workflow = _workflow(image_builder, releases, inventory)
    actor = PlatformPluginActor("ci:system-release")

    first = await workflow.publish_verified(
        _verified(b"first"),
        platform_actor=actor,
    )
    second = await workflow.publish_verified(
        _verified(b"second"),
        platform_actor=actor,
    )

    assert first.revision == 1
    assert second.revision == 2
    assert first.runtime_artifact is not None
    assert first.contract_digest == plugin_contract_digest(first.catalog)
    assert await releases.list_current_system() == []
    assert image_builder.build_count == 2
    assert image_builder.loader_targets == [
        inventory.entry_for(first.slug).loader_target,
        inventory.entry_for(second.slug).loader_target,
    ]

    selected = await workflow.promote(
        slug=second.slug,
        revision=second.revision,
        platform_actor=actor,
        expected_generation=0,
    )
    assert selected.selected_release_id == second.id
    assert selected.selected_revision == 2
    assert selected.generation == 1
    assert await releases.list_current_system() == [second]

    selected_again = await workflow.promote(
        slug=second.slug,
        revision=second.revision,
        platform_actor=actor,
        expected_generation=selected.generation,
    )
    assert selected_again.generation == 1

    with pytest.raises(PluginReleaseError, match="changed concurrently"):
        await workflow.promote(
            slug=second.slug,
            revision=second.revision,
            platform_actor=actor,
            expected_generation=selected_again.generation + 1,
        )
    unchanged = await releases.get_selection(
        WORKSPACE_ID,
        second.slug,
        scope=PluginReleaseScope.SYSTEM,
    )
    assert unchanged is not None
    assert unchanged.selected_release_id == second.id
    assert unchanged.generation == 1

    rolled_back = await workflow.promote(
        slug=first.slug,
        revision=first.revision,
        platform_actor=actor,
        expected_generation=selected.generation,
    )
    assert rolled_back.selected_release_id == first.id
    assert rolled_back.selected_revision == 1
    assert rolled_back.generation == 2
    assert await releases.list_current_system() == [first]

    await database.dispose()


@pytest.mark.asyncio
async def test_system_publication_rejects_unauthorized_identity_before_image_build(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'authority.sqlite3'}"
    await create_schema(database_url)
    database = create_database(database_url)
    releases = PluginReleaseService(
        lambda: SqlAlchemyUnitOfWork(database.sessions),
        LocalFileObjectStore(tmp_path / "objects"),
        bucket="plugins",
    )
    image_builder = RecordingSystemImageBuilder()
    inventory = load_system_plugin_inventory(CHECKED_IN_SYSTEM_PLUGIN_INVENTORY_PATH)
    workflow = _workflow(image_builder, releases, inventory)

    with pytest.raises(PluginPublishingError, match="allowlisted prefixes"):
        await workflow.publish_verified(
            _verified(b"bad", catalog=_catalog(operator_id="external.evil.echo")),
            platform_actor=PlatformPluginActor("ci:system-release"),
        )

    assert image_builder.build_count == 0
    await database.dispose()


@pytest.mark.asyncio
async def test_isolated_llm_system_release_promotes_without_a_host_manifest(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'llm.sqlite3'}"
    await create_schema(database_url)
    database = create_database(database_url)
    releases = PluginReleaseService(
        lambda: SqlAlchemyUnitOfWork(database.sessions),
        LocalFileObjectStore(tmp_path / "objects"),
        bucket="plugins",
    )
    image_builder = RecordingSystemImageBuilder()
    inventory = load_system_plugin_inventory(CHECKED_IN_SYSTEM_PLUGIN_INVENTORY_PATH)
    destination = PluginEgressDestination.parse("https://api.openai.com:443")
    workflow = SystemPluginPublicationWorkflow(
        image_builder,
        releases,
        isolated_release_admission(
            profile=runtime_profile("python-uv"),
            egress_policy=PluginEgressBrokerPolicy(
                broker_image="registry.example/grafy-egress@sha256:" + "a" * 64,
                destinations=(destination,),
            ),
            network_policy=legacy_network_policy(
                http_destinations=(destination,),
            ),
        ),
        inventory,
    )
    entry = inventory.entry_for("external.llm")
    candidate = _verified(
        b"llm",
        catalog=_catalog(
            slug=entry.slug,
            operator_id="llm.openai_compatible.chat_completion",
            required_capabilities=entry.capabilities,
        ),
        capabilities=PluginCapabilityManifest(capabilities=entry.capabilities),
        loader_target=entry.loader_target,
    )
    actor = PlatformPluginActor("ci:system-release")

    release = await workflow.publish_verified(candidate, platform_actor=actor)
    selection = await workflow.promote(
        slug=release.slug,
        revision=release.revision,
        platform_actor=actor,
        expected_generation=0,
    )

    assert release.execution_policy is PluginExecutionPolicy.ISOLATED_ONLY
    assert selection.selected_release_id == release.id
    assert image_builder.loader_targets == [entry.loader_target]
    await database.dispose()


@pytest.mark.asyncio
async def test_system_install_reuses_workspace_release_and_runtime_artifact(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'shared-release.sqlite3'}"
    await create_schema(database_url)
    database = create_database(database_url)
    releases = PluginReleaseService(
        lambda: SqlAlchemyUnitOfWork(database.sessions),
        LocalFileObjectStore(tmp_path / "objects"),
        bucket="plugins",
    )
    image_builder = RecordingSystemImageBuilder()
    inventory = load_system_plugin_inventory(CHECKED_IN_SYSTEM_PLUGIN_INVENTORY_PATH)
    entry = inventory.entry_for("external.llm")
    candidate = _verified(
        b"shared-llm",
        catalog=_catalog(
            slug=entry.slug,
            operator_id="llm.openai_compatible.chat_completion",
            required_capabilities=entry.capabilities,
        ),
        capabilities=PluginCapabilityManifest(capabilities=entry.capabilities),
        loader_target=entry.loader_target,
    )
    runtime_artifact = PluginRuntimeArtifact(
        object_key=(
            f"plugin-releases/{candidate.catalog.slug}/runtime/"
            f"{candidate.source_digest}.oci.tar"
        ),
        archive_digest=candidate.source_digest,
        manifest_digest=plugin_contract_digest(candidate.catalog),
        config_digest="a" * 64,
    )
    workspace_release = await releases.publish(
        workspace_id=WORKSPACE_ID,
        catalog=candidate.catalog,
        capabilities=candidate.capabilities,
        source_archive=candidate.source_archive,
        lock_digest=candidate.lock_digest,
        runtime_profile=candidate.runtime_profile,
        runtime_artifact=runtime_artifact,
        loader_target=candidate.loader_target,
        published_by_user_id=TEST_USER_ID,
    )

    system_release = await _workflow(
        image_builder,
        releases,
        inventory,
    ).publish_verified(
        candidate,
        platform_actor=PlatformPluginActor("ci:system-release"),
    )

    assert system_release.id == workspace_release.id
    assert system_release.installation_id != workspace_release.installation_id
    assert system_release.runtime_artifact == workspace_release.runtime_artifact
    assert system_release.scope is PluginReleaseScope.SYSTEM
    assert workspace_release.scope is PluginReleaseScope.WORKSPACE
    assert image_builder.build_count == 0
    await database.dispose()


@pytest.mark.asyncio
async def test_direct_workspace_publish_cannot_reuse_historical_system_identity(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'collision.sqlite3'}"
    await create_schema(database_url)
    database = create_database(database_url)
    releases = PluginReleaseService(
        lambda: SqlAlchemyUnitOfWork(database.sessions),
        LocalFileObjectStore(tmp_path / "objects"),
        bucket="plugins",
    )
    image_builder = RecordingSystemImageBuilder()
    inventory = load_system_plugin_inventory(CHECKED_IN_SYSTEM_PLUGIN_INVENTORY_PATH)
    workflow = _workflow(image_builder, releases, inventory)
    gis_entry = inventory.entry_for("external.gis")
    system_catalog = _catalog(
        slug="external.gis",
        operator_id="gis.node",
        required_capabilities=gis_entry.capabilities,
    )
    await workflow.publish_verified(
        _verified(
            b"retained-system",
            catalog=system_catalog,
            capabilities=PluginCapabilityManifest(capabilities=gis_entry.capabilities),
            loader_target=gis_entry.loader_target,
        ),
        platform_actor=PlatformPluginActor("ci:system-release"),
    )

    workspace_catalog = _catalog(slug="gis", operator_id="gis.node")
    with pytest.raises(PluginReleaseError, match="retained System Plugin identity"):
        await releases.publish(
            workspace_id=WORKSPACE_ID,
            catalog=workspace_catalog,
            capabilities=PluginCapabilityManifest(),
            source_archive=b"workspace",
            lock_digest=sha256(b"workspace-lock").hexdigest(),
                runtime_profile="python-uv",
                runtime_artifact=None,
                loader_target="grafy_plugin:PLUGIN",
                published_by_user_id=TEST_USER_ID,
        )

    await database.dispose()
