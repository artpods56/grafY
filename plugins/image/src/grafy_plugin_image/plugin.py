from grafy_core.artifact_contracts import IMAGE_REGIONS, ImageRegionSet
from grafy_core.runtime.artifact_values import inline_model_artifact

from grafy_plugin_image import nodes
from grafy_plugin_image.declaration import IMAGES


_RUNTIME_MODULES = (nodes,)


IMAGES.register(inline_model_artifact(IMAGE_REGIONS, ImageRegionSet))


__all__ = ["IMAGES"]
