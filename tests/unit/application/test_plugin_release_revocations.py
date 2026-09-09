from pathlib import Path

import pytest

from grafy_core.application.plugin_releases import PluginReleaseService
from grafy_core.domain.errors import NotFoundError
from grafy_core.domain.plugin_installations import (
    InstalledPluginRelease,
    PluginInstallation,
)
from grafy_core.domain.plugin_releases import (
    PlatformPluginActor,
    PluginCapabilityManifest,
    PluginCatalogManifest,
    PluginExecutionPolicy,
    PluginNodeContract,
    PluginRelease,
    PluginReleaseNamespace,
    PluginReleaseScope,
    PluginRuntimeArtifact,
    plugin_contract_digest,
    plugin_profile_digest,
    plugin_protocol_digest,
)
from grafy_core.domain.plugin_revocations import (
    PluginReleaseRevocationError,
    PluginReleaseRevocationReason,
)
from grafy_core.domain.plugin_selection import PluginReleaseSelection
from grafy_persistence.database import create_database
from grafy_persistence.unit_of_work import SqlAlchemyUnitOfWork
from grafy_storage import LocalFileObjectStore
from tests.support.identity import TEST_USER_ID, WORKSPACE_ID, create_schema


def _release(
    namespace: PluginReleaseNamespace,
    *,
    slug: str,
    revision: int,
    digest_character: str,
) -> InstalledPluginRelease:
    catalog = PluginCatalogManifest(
        slug=slug,
        title="Revocation test Plugin",
        nodes=(
            PluginNodeContract(
                operator_id=f"{slug}.echo",
                operator_version=1,
                title="Echo",
                description="Echo a value",
                config_schema={"type": "object"},
                input_schema={"type": "object"},
                output_schema={"type": "object"},
                inputs=(),
                outputs=(),
            ),
        ),
    )
    capabilities = PluginCapabilityManifest()
    is_system = namespace.scope is PluginReleaseScope.SYSTEM
    runtime_artifact = (
        PluginRuntimeArtifact(
            object_key=(
                f"plugin-releases/{namespace.storage_path}/{slug}/runtime.oci.tar"
            ),
            archive_digest="a" * 64,
            manifest_digest="b" * 64,
            config_digest="c" * 64,
        )
        if is_system
        else None
    )
    release = PluginRelease(
        slug=slug,
        revision=revision,
        catalog=catalog,
        contract_digest=plugin_contract_digest(catalog),
        capabilities=capabilities,
        capability_digest=capabilities.digest,
        protocol_digest=plugin_protocol_digest(),
        profile_digest=plugin_profile_digest("python-uv"),
        source_object_key=f"plugin-releases/{namespace.storage_path}/{slug}.tar.gz",
        source_digest=digest_character * 64,
        lock_digest="f" * 64,
        runtime_profile="python-uv",
        loader_target="grafy_plugin:PLUGIN",
        runtime_image_digest=(
            None if runtime_artifact is None else runtime_artifact.manifest_digest
        ),
        runtime_artifact=runtime_artifact,
        published_by_user_id=None if is_system else TEST_USER_ID,
        published_by_platform_actor="ci:publisher" if is_system else None,
    )
    installation = PluginInstallation.from_release(
        release,
        namespace=namespace,
        execution_policy=(
            PluginExecutionPolicy.HOST_ELIGIBLE
            if is_system
            else PluginExecutionPolicy.ISOLATED_ONLY
        ),
        installed_by_user_id=None if is_system else TEST_USER_ID,
        installed_by_platform_actor="ci:publisher" if is_system else None,
    )
    return InstalledPluginRelease(release=release, installation=installation)


@pytest.mark.asyncio
async def test_revocation_service_enforces_authority_scope_and_idempotency(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'revocations.sqlite3'}"
    await create_schema(database_url)
    database = create_database(database_url)
    service = PluginReleaseService(
        lambda: SqlAlchemyUnitOfWork(database.sessions),
        LocalFileObjectStore(tmp_path / "objects"),
        bucket="plugins",
    )
    workspace_namespace = PluginReleaseNamespace(
        scope=PluginReleaseScope.WORKSPACE,
        workspace_id=WORKSPACE_ID,
    )
    system_namespace = PluginReleaseNamespace(
        scope=PluginReleaseScope.SYSTEM,
        workspace_id=None,
    )
    first = _release(
        workspace_namespace,
        slug="workspace-notes",
        revision=1,
        digest_character="1",
    )
    current = _release(
        workspace_namespace,
        slug="workspace-notes",
        revision=2,
        digest_character="2",
    )
    system_current = _release(
        system_namespace,
        slug="system-notes",
        revision=1,
        digest_character="3",
    )
    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        for release in (first, current, system_current):
            await unit_of_work.plugin_releases.add(release.release)
            await unit_of_work.plugin_releases.add_installation(release.installation)
        await unit_of_work.plugin_releases.add_selection(
            PluginReleaseSelection.from_release(
                current,
                actor_reference=f"user:{TEST_USER_ID}",
            )
        )
        await unit_of_work.plugin_releases.add_selection(
            PluginReleaseSelection.from_release(
                system_current,
                actor_reference="platform:ci:publisher",
            )
        )
        await unit_of_work.commit()

    workspace_revocation = await service.revoke(
        workspace_id=WORKSPACE_ID,
        slug=first.release.slug,
        revision=first.release.revision,
        reason=PluginReleaseRevocationReason.SECURITY,
        revoked_by_user_id=TEST_USER_ID,
    )
    assert workspace_revocation.installation_id == first.installation.id
    assert workspace_revocation.revoked_by_user_id == TEST_USER_ID
    assert (
        await service.get_revocation(
            workspace_id=WORKSPACE_ID,
            slug=first.release.slug,
            revision=first.release.revision,
        )
        == workspace_revocation
    )
    assert await service.list_current(WORKSPACE_ID) == [current]
    assert (
        await service.revoke(
            workspace_id=WORKSPACE_ID,
            slug=first.release.slug,
            revision=first.release.revision,
            reason=PluginReleaseRevocationReason.SECURITY,
            revoked_by_user_id=TEST_USER_ID,
        )
        == workspace_revocation
    )

    with pytest.raises(
        PluginReleaseRevocationError,
        match="different immutable intent",
    ):
        await service.revoke(
            workspace_id=WORKSPACE_ID,
            slug=first.release.slug,
            revision=first.release.revision,
            reason=PluginReleaseRevocationReason.POLICY,
            revoked_by_user_id=TEST_USER_ID,
        )

    with pytest.raises(NotFoundError, match="Workspace Plugin release not found"):
        await service.revoke(
            workspace_id=WORKSPACE_ID,
            slug=system_current.release.slug,
            revision=system_current.release.revision,
            reason=PluginReleaseRevocationReason.SECURITY,
            revoked_by_user_id=TEST_USER_ID,
        )

    platform_actor = PlatformPluginActor("ci:revoker")
    system_revocation = await service.revoke_system(
        slug=system_current.release.slug,
        revision=system_current.release.revision,
        reason=PluginReleaseRevocationReason.INTEGRITY,
        platform_actor=platform_actor,
    )
    assert system_revocation.revoked_by_user_id is None
    assert system_revocation.revoked_by_platform_actor == platform_actor.reference
    assert (
        await service.get_system_revocation(
            slug=system_current.release.slug,
            revision=system_current.release.revision,
        )
        == system_revocation
    )
    assert await service.list_current_system() == [system_current]
    retained_system = await service.get_system_by_revision(
        system_current.release.slug,
        system_current.release.revision,
    )
    assert retained_system is not None
    assert (
        retained_system.release.runtime_artifact
        == system_current.release.runtime_artifact
    )

    await database.dispose()
