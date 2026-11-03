"""Artifact, upload and Library transaction used by the workbench."""

from typing import Protocol

from grafy_core.ports.artifacts import UnitOfWorkPort
from grafy_core.ports.library_folders import LibraryFolderRepositoryPort
from grafy_core.ports.uploads import UploadRepositoryPort


class WorkbenchUnitOfWorkPort(UnitOfWorkPort, Protocol):
    @property
    def uploads(self) -> UploadRepositoryPort: ...

    @property
    def library_folders(self) -> LibraryFolderRepositoryPort: ...
