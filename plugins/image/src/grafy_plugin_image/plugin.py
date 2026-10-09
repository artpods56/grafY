from grafy_core.artifact_contracts import IMAGE_REGIONS, ImageRegionSet
from grafy_core.artifacts import Artifact
from grafy_core.runtime.persistence import InlineModelOutputWriter
from grafy_core.runtime.resolvers import InlineModelResolver

from grafy_plugin_image import nodes, persistence
from grafy_plugin_image.declaration import IMAGES


_RUNTIME_MODULES = (nodes, persistence)


IMAGES.register(
    Artifact(
        spec=IMAGE_REGIONS,
        resolver=lambda context: InlineModelResolver(
            source=IMAGE_REGIONS.key,
            target=ImageRegionSet,
            uow=context.uow,
        ),
        writer=lambda context: InlineModelOutputWriter(
            artifact_type=IMAGE_REGIONS.key,
            model=ImageRegionSet,
            uow=context.uow,
        ),
    )
)


__all__ = ["IMAGES"]
