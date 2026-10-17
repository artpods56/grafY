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
from tests.support.identity import create_schema

PLATFORM_ACTOR = "ci:publisher"


def _release(
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
    runtime_artifact = PluginRuntimeArtifact(
        object_key=f"plugin-releases/system/{slug}/runtime.oci.tar",
        archive_digest="a" * 64,
        manifest_digest="b" * 64,
        config_digest="c" * 64,
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
        source_object_key=f"plugin-releases/{slug}.tar.gz",
        source_digest=digest_character * 64,
        lock_digest="f" * 64,
        runtime_profile="python-uv",
        loader_target="grafy_plugin:PLUGIN",
        runtime_image_digest=runtime_artifact.manifest_digest,
        runtime_artifact=runtime_artifact,
        published_by_platform_actor=PLATFORM_ACTOR,
    )
    installation = PluginInstallation.from_release(
        release,
        namespace=PluginReleaseNamespace(),
        execution_policy=PluginExecutionPolicy.HOST_ELIGIBLE,
        installed_by_platform_actor=PLATFORM_ACTOR,
    )
    return InstalledPluginRelease(release=release, installation=installation)


@pytest.mark.asyncio
async def test_revocation_service_enforces_exact_identity_and_idempotency(
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
    namespace = PluginReleaseNamespace()
    first = _release(slug="notes", revision=1, digest_character="1")
    current = _release(slug="notes", revision=2, digest_character="2")
    other = _release(slug="other", revision=1, digest_character="3")
    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        for release in (first, current, other):
            await unit_of_work.plugin_releases.add(release.release)
            await unit_of_work.plugin_releases.add_installation(release.installation)
        for release in (current, other):
            await unit_of_work.plugin_releases.add_selection(
                PluginReleaseSelection.from_release(
                    release,
                    actor_reference=f"platform:{PLATFORM_ACTOR}",
                )
            )
        await unit_of_work.commit()

    revocation = await service.revoke_system(
        slug=first.release.slug,
        revision=first.release.revision,
        reason=PluginReleaseRevocationReason.SECURITY,
        platform_actor=PlatformPluginActor(PLATFORM_ACTOR),
    )
    assert revocation.installation_id == first.installation.id
    assert revocation.revoked_by_user_id is None
    assert revocation.revoked_by_platform_actor == PLATFORM_ACTOR
    assert (
        await service.get_system_revocation(
            slug=first.release.slug,
            revision=first.release.revision,
        )
        == revocation
    )
    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        assert await unit_of_work.plugin_releases.list_current(namespace) == [
            current,
            other,
        ]
    assert (
        await service.revoke_system(
            slug=first.release.slug,
            revision=first.release.revision,
            reason=PluginReleaseRevocationReason.SECURITY,
            platform_actor=PlatformPluginActor(PLATFORM_ACTOR),
        )
        == revocation
    )

    with pytest.raises(
        PluginReleaseRevocationError,
        match="different immutable intent",
    ):
        await service.revoke_system(
            slug=first.release.slug,
            revision=first.release.revision,
            reason=PluginReleaseRevocationReason.POLICY,
            platform_actor=PlatformPluginActor(PLATFORM_ACTOR),
        )

    with pytest.raises(NotFoundError, match="System Plugin release not found"):
        await service.revoke_system(
            slug="absent",
            revision=1,
            reason=PluginReleaseRevocationReason.SECURITY,
            platform_actor=PlatformPluginActor(PLATFORM_ACTOR),
        )

    assert [item.release for item in await service.list_catalog()] == [current, other]
    retained = await service.get_by_revision(
        first.release.slug,
        first.release.revision,
    )
    assert retained is not None
    assert retained.release.runtime_artifact == first.release.runtime_artifact

    await database.dispose()
