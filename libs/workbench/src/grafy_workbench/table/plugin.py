from grafy_workbench.table.declaration import TABLES
from grafy_workbench.table.persistence import table_artifact

# Port derivation runs at class definition, so Table must be registered before
# the node modules import.
TABLES.register(table_artifact())

from grafy_workbench.table import concat  # noqa: E402, F401  # pyright: ignore[reportUnusedImport]
from grafy_workbench.table import markdown_tables  # noqa: E402, F401  # pyright: ignore[reportUnusedImport]


__all__ = ["TABLES"]
