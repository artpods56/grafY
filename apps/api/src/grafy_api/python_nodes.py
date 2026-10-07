"""Apply for Python nodes (ADR 0012).

Apply derives the contract a Python node stores in its configuration. The host
parses the code with ``ast`` and never executes it; the selected Python runner
release executes it in the Plugin sandbox, inside a sandbox scope of its own,
through an invoker whose artifacts stay in memory.
"""

import ast
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Protocol, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError

from grafy_core.artifacts import ArtifactRef
from grafy_core.domain.plugin_installations import InstalledPluginRelease
from grafy_core.domain.plugin_releases import PluginNodeContract, PluginReleaseScope
from grafy_core.domain.plugin_revocations import PluginReleaseRevocation
from grafy_core.nodes import NodeExecutionContext, PortShape
from grafy_core.ports.storage import FileStoragePort
from grafy_core.runtime.in_memory import InMemoryUnitOfWork
from grafy_core.runtime.plugin_invocation import (
    PluginInvocationError,
    PluginReleaseNode,
    PluginReleaseNodeConfig,
)
from grafy_workbench.presets import PYTHON_PLUGIN_SLUG

from grafy_api.plugins.runtime.admission import (
    ReleaseExecutionAdmission,
    ReleaseExecutionRejection,
)
from grafy_api.plugins.runtime.artifacts import (
    ArtifactBundlePluginInvoker,
    PluginGuestRunner,
    PluginInvocationScratch,
)
from grafy_api.plugins.runtime.sandbox import (
    PluginSandboxLifecycle,
    PluginSandboxScopeId,
    activate_plugin_sandbox_scope,
    reset_plugin_sandbox_scope,
)


PYTHON_INSPECT_OPERATOR_ID = "python.inspect"
PYTHON_INSPECT_OPERATOR_VERSION = 1
MAX_PYTHON_CODE_LENGTH = 65_536


class PythonApplyUnavailableError(RuntimeError):
    """The pinned Python runner cannot analyse code in this deployment."""


class PythonReleaseLookup(Protocol):
    async def get_by_revision(
        self,
        workspace_id: UUID,
        slug: str,
        revision: int,
        *,
        scope: PluginReleaseScope = PluginReleaseScope.WORKSPACE,
    ) -> InstalledPluginRelease | None: ...

    async def get_revocation(
        self,
        *,
        workspace_id: UUID,
        slug: str,
        revision: int,
    ) -> PluginReleaseRevocation | None: ...

    async def get_system_revocation(
        self,
        *,
        slug: str,
        revision: int,
    ) -> PluginReleaseRevocation | None: ...


class PythonSandbox(
    PluginGuestRunner,
    PluginInvocationScratch,
    PluginSandboxLifecycle,
    Protocol,
):
    """The Plugin sandbox Apply runs in; ``DockerPluginRuntime`` in production."""


class _Report(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PythonDiagnostic(_Report):
    line: int = Field(ge=1)
    column: int = Field(default=0, ge=0)
    message: str


class PythonArtifactType(_Report):
    id: str
    schema_version: int = Field(ge=1)


class PythonPortContract(_Report):
    artifact_type: PythonArtifactType
    shape: PortShape


class PythonCodeContract(_Report):
    input_name: str
    input: PythonPortContract
    output: PythonPortContract
    params_schema: dict[str, JsonValue] | None = None


class PythonInspectionReport(_Report):
    """The wire form ``python.inspect@1`` returns."""

    contract: PythonCodeContract | None = None
    diagnostics: list[PythonDiagnostic] = Field(default_factory=list[PythonDiagnostic])


@dataclass(frozen=True, slots=True)
class PythonApplyResult:
    code_sha256: str
    contract: PythonCodeContract | None
    diagnostics: tuple[PythonDiagnostic, ...]


def host_diagnostics(code: str) -> tuple[PythonDiagnostic, ...]:
    """Find the ``transform`` signature with ``ast``; user code never runs here."""

    if len(code) > MAX_PYTHON_CODE_LENGTH:
        return (
            PythonDiagnostic(
                line=1,
                message=f"Code must be at most {MAX_PYTHON_CODE_LENGTH} characters",
            ),
        )
    try:
        tree = ast.parse(code, filename="transform.py")
    except SyntaxError as exc:
        return (
            PythonDiagnostic(
                line=max(1, exc.lineno or 1),
                column=max(0, (exc.offset or 1) - 1),
                message=f"SyntaxError: {exc.msg}",
            ),
        )
    functions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and node.name == "transform"
    ]
    if not functions:
        return (
            PythonDiagnostic(
                line=1, message="Define one top-level function `def transform(...)`"
            ),
        )
    if len(functions) > 1:
        return (
            PythonDiagnostic(
                line=functions[1].lineno, message="Define `transform` only once"
            ),
        )
    return ()


class PythonApplyService:
    def __init__(
        self,
        *,
        releases: PythonReleaseLookup,
        admission: ReleaseExecutionAdmission,
        sandbox: PythonSandbox,
        storage: FileStoragePort,
        bucket: str,
    ) -> None:
        self._releases = releases
        self._admission = admission
        self._sandbox = sandbox
        self._storage = storage
        self._bucket = bucket

    async def apply(
        self,
        *,
        workspace_id: UUID,
        code: str,
        scope: PluginReleaseScope,
        slug: str,
        revision: int,
    ) -> PythonApplyResult:
        code_sha256 = sha256(code.encode("utf-8")).hexdigest()
        diagnostics = host_diagnostics(code)
        if diagnostics:
            return PythonApplyResult(code_sha256, None, diagnostics)
        release = await self._runnable_release(workspace_id, scope, slug, revision)
        report = await self._inspect(workspace_id, release, code)
        if report.contract is not None:
            declared = {
                (artifact.key.id, artifact.key.schema_version)
                for artifact in (
                    *release.release.catalog.artifact_types,
                    *release.release.catalog.artifact_type_dependencies,
                )
            }
            for port in (report.contract.input, report.contract.output):
                key = (port.artifact_type.id, port.artifact_type.schema_version)
                if key not in declared:
                    raise PythonApplyUnavailableError(
                        f"Python runner returned undeclared type {key[0]}@{key[1]}"
                    )
        return PythonApplyResult(
            code_sha256,
            report.contract,
            tuple(report.diagnostics),
        )

    async def _runnable_release(
        self,
        workspace_id: UUID,
        scope: PluginReleaseScope,
        slug: str,
        revision: int,
    ) -> InstalledPluginRelease:
        if slug != PYTHON_PLUGIN_SLUG:
            raise PythonApplyUnavailableError(
                f"Plugin {slug!r} is not the Python runner {PYTHON_PLUGIN_SLUG!r}"
            )
        release = await self._releases.get_by_revision(
            workspace_id,
            slug,
            revision,
            scope=scope,
        )
        if release is None:
            raise PythonApplyUnavailableError(
                f"Python runner release {slug} revision {revision} is unavailable"
            )
        if scope is PluginReleaseScope.SYSTEM:
            revocation = await self._releases.get_system_revocation(
                slug=slug,
                revision=revision,
            )
        else:
            revocation = await self._releases.get_revocation(
                workspace_id=workspace_id,
                slug=slug,
                revision=revision,
            )
        decision = self._admission.decide(
            release,
            node_contract=self._inspect_contract(release),
            revocation=revocation,
        )
        if isinstance(decision, ReleaseExecutionRejection):
            raise PythonApplyUnavailableError(
                f"Python runner is not runnable ({decision.reason}): {decision.detail}"
            )
        return release

    def _inspect_contract(self, release: InstalledPluginRelease) -> PluginNodeContract:
        contract = next(
            (
                node
                for node in release.release.catalog.nodes
                if node.operator_id == PYTHON_INSPECT_OPERATOR_ID
                and node.operator_version == PYTHON_INSPECT_OPERATOR_VERSION
            ),
            None,
        )
        if contract is None:
            raise PythonApplyUnavailableError(
                f"Python runner revision {release.release.revision} cannot inspect code"
            )
        return contract

    async def _inspect(
        self,
        workspace_id: UUID,
        release: InstalledPluginRelease,
        code: str,
    ) -> PythonInspectionReport:
        unit_of_work = InMemoryUnitOfWork()
        node: PluginReleaseNode[Any, Any, Any] = PluginReleaseNode(
            release,
            self._inspect_contract(release),
            ArtifactBundlePluginInvoker(
                unit_of_work=unit_of_work,
                runner=self._sandbox,
                scratch=self._sandbox,
                storage=self._storage,
                bucket=self._bucket,
            ),
        )
        scope = PluginSandboxScopeId.new()
        token = activate_plugin_sandbox_scope(scope)
        try:
            output = await node.run(
                NodeExecutionContext(workspace_id=workspace_id),
                PluginReleaseNodeConfig.model_validate({"code": code}),
                node.input_contract.model(),
            )
        except PluginInvocationError as exc:
            return PythonInspectionReport(
                diagnostics=[
                    PythonDiagnostic(
                        line=1,
                        message=f"Python sandbox could not inspect the code: {exc}",
                    )
                ]
            )
        finally:
            reset_plugin_sandbox_scope(token)
            await self._sandbox.close_scope(scope)
        report_ref = cast(ArtifactRef, output.report)
        async with unit_of_work as entered:
            artifact = await entered.artifacts.get(workspace_id, report_ref.artifact_id)
        payload = None if artifact is None else artifact.inline_payload
        try:
            return PythonInspectionReport.model_validate_json(
                cast(str, (payload or {}).get("value"))
            )
        except (ValidationError, TypeError) as exc:
            raise PythonApplyUnavailableError(
                "Python runner returned an unreadable inspection report"
            ) from exc


__all__ = [
    "MAX_PYTHON_CODE_LENGTH",
    "PythonApplyResult",
    "PythonApplyService",
    "PythonApplyUnavailableError",
    "PythonCodeContract",
    "PythonDiagnostic",
    "PythonInspectionReport",
    "host_diagnostics",
]
