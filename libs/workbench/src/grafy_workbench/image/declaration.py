from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_core.file_contracts import (
    BMP_FILE,
    JPEG_FILE,
    PNG_FILE,
    TIFF_FILE,
    WEBP_FILE,
)
from grafy_core.plugins import Plugin


IMAGES = Plugin(
    slug="image",
    title="Image",
    capabilities=(PluginRuntimeCapability.STAGED_UPLOADS,),
)
IMAGES.register_artifact_type_dependency(PNG_FILE)
IMAGES.register_artifact_type_dependency(JPEG_FILE)
IMAGES.register_artifact_type_dependency(WEBP_FILE)
IMAGES.register_artifact_type_dependency(TIFF_FILE)
IMAGES.register_artifact_type_dependency(BMP_FILE)
