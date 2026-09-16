from grafy_core.file_contracts import BUILTIN_FILE_FORMATS
from grafy_core.plugins import Plugin


FILES = Plugin(
    slug="file",
    title="File",
)
for _file_format in BUILTIN_FILE_FORMATS:
    FILES.register_artifact_type_dependency(_file_format)


__all__ = ["FILES"]
