from grafy_core.file_contracts import BUILTIN_FILE_FORMATS, TXT_FILE
from grafy_core.plugins import Plugin

from grafy_workbench.file.resolvers import FileBytesResolver


FILES = Plugin(
    slug="file",
    title="File",
)
for _file_format in BUILTIN_FILE_FORMATS:
    FILES.register_artifact_type_dependency(_file_format)

# Read by the canonical file.txt -> scalar.text conversion on an edge.
FILES.register_resolver(
    lambda context: FileBytesResolver(
        source=TXT_FILE.key,
        storage=context.storage,
        uow=context.uow,
    )
)


__all__ = ["FILES"]
