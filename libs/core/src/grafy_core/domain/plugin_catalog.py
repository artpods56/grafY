"""Selected releases and their admission state for a catalog read."""

from dataclasses import dataclass

from grafy_core.domain.plugin_installations import InstalledPluginRelease
from grafy_core.domain.plugin_releases import PluginReleaseError
from grafy_core.domain.plugin_revocations import PluginReleaseRevocation
from grafy_core.domain.plugin_selection import PluginReleaseSelection


@dataclass(frozen=True, slots=True)
class PluginCatalogRelease:
    release: InstalledPluginRelease
    selection: PluginReleaseSelection
    revocation: PluginReleaseRevocation | None

    def __post_init__(self) -> None:
        release = self.release
        selection = self.selection
        if (
            selection.namespace != release.namespace
            or selection.slug != release.slug
            or selection.selected_release_id != release.id
            or selection.selected_revision != release.revision
        ):
            raise PluginReleaseError(
                f"Catalog selection does not identify {release.scope.value} "
                f"Plugin {release.slug!r} revision {release.revision}"
            )
        if self.revocation is not None and (
            self.revocation.installation_id != release.installation_id
            or self.revocation.namespace != release.namespace
            or self.revocation.slug != release.slug
            or self.revocation.revision != release.revision
        ):
            raise PluginReleaseError(
                f"Catalog revocation does not identify installation "
                f"{release.installation_id} of Plugin {release.slug!r} "
                f"revision {release.revision}"
            )
