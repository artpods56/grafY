"""Outer sandbox-provider adapters for the agent worker."""

from grafy_agent_worker.sandbox.daytona import (
    DaytonaSandboxSettings,
    DaytonaSandboxWorkspace,
)
from grafy_agent_worker.sandbox.docker import (
    DockerSandboxSettings,
    DockerSandboxWorkspace,
)

__all__ = [
    "DaytonaSandboxSettings",
    "DaytonaSandboxWorkspace",
    "DockerSandboxSettings",
    "DockerSandboxWorkspace",
]
