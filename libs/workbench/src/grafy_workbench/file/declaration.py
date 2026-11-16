from grafy_core.file_contracts import (
    BMP_FILE,
    BUILTIN_FILE_FORMATS,
    JPEG_FILE,
    PNG_FILE,
    TIFF_FILE,
    TXT_FILE,
    WEBP_FILE,
)
from grafy_core.plugins import Plugin

from grafy_workbench.file.resolvers import FileBytesResolver


FILES = Plugin(
    slug="file",
    title="File",
)
for _file_format in BUILTIN_FILE_FORMATS:
    FILES.register_artifact_type_dependency(_file_format)

# Canonical conversions materialize file bytes before converting them.
for _source in (TXT_FILE, PNG_FILE, JPEG_FILE, WEBP_FILE, TIFF_FILE, BMP_FILE):
    FILES.register_resolver(
        lambda context, source=_source: FileBytesResolver(
            source=source.key,
            storage=context.storage,
            uow=context.uow,
        )
    )


__all__ = ["FILES"]
