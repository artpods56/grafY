from grafy_core.artifacts import UnitOfWorkPort
from grafy_core.runtime.persistence import InlineModelOutputWriter
from grafy_core.runtime.resolvers import InlineModelResolver

from grafy_plugin_notes.artifacts import TABLE_SUMMARY
from grafy_plugin_notes.models import TableSummary


def table_summary_writer(uow: UnitOfWorkPort) -> InlineModelOutputWriter[TableSummary]:
    """Runs in the isolated freeze, not in the API process."""

    return InlineModelOutputWriter(
        artifact_type=TABLE_SUMMARY.key,
        model=TableSummary,
        uow=uow,
    )


def table_summary_resolver(uow: UnitOfWorkPort) -> InlineModelResolver[TableSummary]:
    """Runs in the isolated freeze, not in the API process."""

    return InlineModelResolver(
        source=TABLE_SUMMARY.key,
        target=TableSummary,
        uow=uow,
    )
