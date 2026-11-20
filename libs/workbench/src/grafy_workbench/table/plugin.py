from grafy_workbench.table.declaration import TABLES
from grafy_workbench.table.persistence import table_artifact


TABLES.register(table_artifact())


__all__ = ["TABLES"]
