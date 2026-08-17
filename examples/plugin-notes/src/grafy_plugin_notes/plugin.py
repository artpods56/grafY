from grafy_core.artifacts import Artifact

from grafy_plugin_notes import nodes
from grafy_plugin_notes.artifacts import TABLE_SUMMARY
from grafy_plugin_notes.declaration import NOTES, RUNTIME_PROFILE
from grafy_plugin_notes.persistence import (
    table_summary_resolver,
    table_summary_writer,
)

_NODE_MODULES = (nodes,)


NOTES.register(
    Artifact(
        spec=TABLE_SUMMARY,
        resolver=lambda context: table_summary_resolver(context.uow),
        writer=lambda context: table_summary_writer(context.uow),
    )
)

__all__ = ["NOTES", "RUNTIME_PROFILE"]
