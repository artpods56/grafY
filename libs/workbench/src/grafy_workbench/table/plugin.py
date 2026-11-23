from grafy_workbench.table.declaration import TABLES
from grafy_workbench.table.persistence import table_artifact

# Note Table before the node class is created. Port derivation runs at class
# table port.
TABLES.register(table_artifact())

from grafy_workbench.table import concat  # noqa: E402, F401  # pyright: ignore[reportUnusedImport]
from grafy_workbench.table import markdown_tables  # noqa: E402, F401  # pyright: ignore[reportUnusedImport]


__all__ = ["TABLES"]
