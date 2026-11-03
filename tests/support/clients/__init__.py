"""Typed HTTP clients for exercising the Grafy ``/v1`` API from tests."""

from tests.support.clients.artifacts import ArtifactsApi
from tests.support.clients.auth import AuthApi
from tests.support.clients.base import GrafyApi
from tests.support.clients.catalog import CatalogApi
from tests.support.clients.node_secrets import NodeSecretsApi
from tests.support.clients.projects import (
    ProjectBrowserApi,
    ProjectFoldersApi,
    ProjectsApi,
)
from tests.support.clients.uploads import UploadsApi
from tests.support.clients.workspaces import WorkspaceApi, WorkspacesApi

__all__ = [
    "ArtifactsApi",
    "AuthApi",
    "CatalogApi",
    "GrafyApi",
    "NodeSecretsApi",
    "ProjectBrowserApi",
    "ProjectFoldersApi",
    "ProjectsApi",
    "UploadsApi",
    "WorkspaceApi",
    "WorkspacesApi",
]
