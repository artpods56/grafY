from grafy_core.artifacts import Artifact

from grafy_plugin.artifacts import TABLE_SUMMARY
from grafy_plugin.declaration import PLUGIN
from grafy_plugin.nodes import render_summary, summarize_table
from grafy_plugin.persistence import (
    table_summary_resolver,
    table_summary_writer,
)


PLUGIN.register(
    Artifact(
        spec=TABLE_SUMMARY,
        resolver=lambda context: table_summary_resolver(context.uow),
        writer=lambda context: table_summary_writer(context.uow),
    )
)

__all__ = ["PLUGIN", "render_summary", "summarize_table"]
