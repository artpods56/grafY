from grafy_core.artifacts import Artifact
from grafy_core.table_contracts import TABLE_DATA

from grafy_workbench.table.declaration import TABLES
from grafy_workbench.table.persistence import TableArtifactResolver, TableArtifactWriter


TABLES.register(
    Artifact(
        spec=TABLE_DATA,
        resolver=lambda context: TableArtifactResolver(
            uow=context.uow,
            storage=context.storage,
        ),
        writer=lambda context: TableArtifactWriter(
            storage=context.storage,
            uow=context.uow,
            bucket=context.bucket,
            storage_backend=context.storage_backend,
        ),
    )
)


__all__ = ["TABLES"]
