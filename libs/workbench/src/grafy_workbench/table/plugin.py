from grafy_core.table_contracts import TABLE_DATA

from grafy_workbench.table.declaration import TABLES
from grafy_workbench.table.persistence import TableArtifactResolver, TableArtifactWriter


TABLES.register_artifact_type(TABLE_DATA)
TABLES.register_resolver(
    lambda context: TableArtifactResolver(
        uow=context.uow,
        storage=context.storage,
    )
)
TABLES.register_writer(
    lambda context: TableArtifactWriter(
        storage=context.storage,
        uow=context.uow,
        bucket=context.bucket,
        storage_backend=context.storage_backend,
    )
)


__all__ = ["TABLES"]
