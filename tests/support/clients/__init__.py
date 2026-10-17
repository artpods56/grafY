"""Typed HTTP clients for exercising the Grafy ``/v1`` API from tests."""

from tests.support.clients.artifacts import ArtifactsApi
from tests.support.clients.auth import AuthApi
from tests.support.clients.base import GrafyApi
from tests.support.clients.catalog import CatalogApi
from tests.support.clients.executions import ExecutionsApi
from tests.support.clients.modules import ModulesApi
from tests.support.clients.node_secrets import NodeSecretsApi
from tests.support.clients.saved_graphs import (
    GraphBrowserApi,
    GraphFoldersApi,
    SavedGraphsApi,
)
from tests.support.clients.uploads import UploadsApi
from tests.support.clients.workspaces import WorkspaceApi, WorkspacesApi

__all__ = [
    "ArtifactsApi",
    "AuthApi",
    "CatalogApi",
    "ExecutionsApi",
    "GrafyApi",
    "GraphBrowserApi",
    "GraphFoldersApi",
    "ModulesApi",
    "NodeSecretsApi",
    "SavedGraphsApi",
    "UploadsApi",
    "WorkspaceApi",
    "WorkspacesApi",
]
