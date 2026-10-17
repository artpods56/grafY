from grafy_core.artifacts import UnitOfWorkPort
from grafy_core.runtime.persistence import InlineModelOutputWriter
from grafy_core.runtime.resolvers import InlineModelResolver

from grafy_plugin.artifacts import TABLE_SUMMARY
from grafy_plugin.models import TableSummary


def table_summary_writer(uow: UnitOfWorkPort) -> InlineModelOutputWriter[TableSummary]:
    return InlineModelOutputWriter(
        artifact_type=TABLE_SUMMARY.key,
        model=TableSummary,
        uow=uow,
    )


def table_summary_resolver(uow: UnitOfWorkPort) -> InlineModelResolver[TableSummary]:
    return InlineModelResolver(
        source=TABLE_SUMMARY.key,
        target=TableSummary,
        uow=uow,
    )
