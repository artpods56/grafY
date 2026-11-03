from typing import Protocol

from grafy_core.ports.collaboration import CollaborationRepositoryPort
from grafy_core.ports.projects import ProjectRepositoryPort
from grafy_core.ports.runs import ResultStoreRepositoryPort
from grafy_core.ports.workbench import WorkbenchUnitOfWorkPort


class LibraryUnitOfWorkPort(WorkbenchUnitOfWorkPort, Protocol):
    @property
    def projects(self) -> ProjectRepositoryPort: ...

    @property
    def collaboration(self) -> CollaborationRepositoryPort: ...

    @property
    def results(self) -> ResultStoreRepositoryPort: ...
