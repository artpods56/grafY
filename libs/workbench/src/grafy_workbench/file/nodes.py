"""Interpret a ``file.blob@1`` artifact as one explicitly chosen file format.

Ingest writes a blob when the extension is unknown, missing, or only a leading
dot, so nothing has claimed those bytes. This node is the visible way out: the
graph binds its output to one claimed ``file.*`` format, the node confirms the
stored bytes with that format's confirmation rule, and it writes a new artifact
of that type. The blob row is never retyped.
"""

from collections.abc import Iterable, Mapping
from hashlib import sha256
from io import BytesIO
from mimetypes import guess_type
from typing import Annotated, final, override

from grafy_core.artifacts import (
    ArtifactObject,
    ArtifactRef,
    ArtifactTypeKey,
    ArtifactTypeSpec,
    JsonObject,
    NodeConfig,
    NodeInput,
    NodeOutput,
)
from grafy_core.file_artifacts import load_file_artifact
from grafy_core.file_contracts import BLOB_FILE
from grafy_core.nodes import (
    ArtifactTypeVariable,
    InPort,
    Node,
    NodeExecutionContext,
    OutPort,
    UserFacingNodeError,
)
from grafy_core.ports.artifacts import UnitOfWorkPort
from grafy_core.ports.storage import FileMetadata, FileStoragePort, SaveFileCommand
from pydantic import Field

from grafy_workbench.file.declaration import FILES


FORMAT_ARTIFACT_TYPE_VARIABLE = "format"


class InterpretFileInput(NodeInput):
    file: Annotated[
        ArtifactRef,
        InPort(BLOB_FILE),
        Field(description="Blob file artifact whose bytes should be interpreted."),
    ]


class InterpretFileOutput(NodeOutput):
    file: Annotated[
        ArtifactRef,
        OutPort(ArtifactTypeVariable(FORMAT_ARTIFACT_TYPE_VARIABLE)),
        Field(description="New file artifact of the chosen format."),
    ]


def _chosen_file_format(
    bindings: Mapping[str, ArtifactTypeKey],
    artifact_types: Mapping[ArtifactTypeKey, ArtifactTypeSpec],
) -> ArtifactTypeSpec:
    key = bindings.get(FORMAT_ARTIFACT_TYPE_VARIABLE)
    if key is None:
        raise UserFacingNodeError(
            "Interpret file needs an explicit format: bind its file output to one "
            "claimed file.* artifact type."
        )
    spec = artifact_types.get(key)
    if spec is None:
        raise UserFacingNodeError(
            f"Interpret file does not know artifact type {key.id}@{key.schema_version}"
        )
    if not spec.extensions:
        raise UserFacingNodeError(
            f"{key.id}@{key.schema_version} is not a claimed file format; choose a "
            "file.* type the deployment recognizes."
        )
    return spec


@FILES.node(
    operator_id="file.interpret",
    version=1,
    title="Interpret file",
    factory=lambda context: InterpretFileNode(
        storage=context.storage,
        uow=context.uow,
        bucket=context.bucket,
        storage_backend=context.storage_backend,
        artifact_types=context.artifact_types,
    ),
)
@final
class InterpretFileNode(Node[NodeConfig, InterpretFileInput, InterpretFileOutput]):
    """Confirm blob bytes against one claimed file.* format and claim them."""

    def __init__(
        self,
        *,
        storage: FileStoragePort,
        uow: UnitOfWorkPort,
        bucket: str,
        storage_backend: str = "local",
        artifact_types: Iterable[ArtifactTypeSpec] = (),
    ) -> None:
        self._storage = storage
        self._uow = uow
        self._bucket = bucket
        self._storage_backend = storage_backend
        self._artifact_types = {spec.key: spec for spec in artifact_types}

    @override
    async def run(
        self,
        context: NodeExecutionContext,
        _config: NodeConfig,
        inputs: InterpretFileInput,
        /,
    ) -> InterpretFileOutput:
        spec = _chosen_file_format(
            context.artifact_type_bindings,
            self._artifact_types,
        )
        source = inputs.file
        file = await load_file_artifact(
            storage=self._storage,
            uow=self._uow,
            workspace_id=context.workspace_id,
            ref=source,
        )
        if not spec.confirmation_rule.confirms(file.content):
            label = file.original_filename or f"artifact {source.artifact_id}"
            expected = spec.key.id.removeprefix("file.").upper()
            raise UserFacingNodeError(
                f"file_format_mismatch: {label} does not look like a {expected} "
                "file. Bind the file output to another format or convert the "
                "file, then try again."
            )

        key = spec.key
        content_hash = sha256(file.content).hexdigest()
        suffix = f".{spec.extensions[0]}"
        content_type = guess_type(f"file{suffix}")[0] or "application/octet-stream"
        storage_metadata: FileMetadata = {
            "artifact_kind": key.id,
            "sha256": content_hash,
        }
        if file.original_filename is not None:
            storage_metadata["original_filename"] = file.original_filename
        if context.node_id is not None:
            storage_metadata["job_id"] = context.node_id
        storage_path = (
            f"workspaces/{context.workspace_id}/{key.id}/"
            f"v{key.schema_version}/{content_hash}{suffix}"
        )
        try:
            stored_file = await self._storage.save(
                SaveFileCommand(
                    bucket=self._bucket,
                    path=storage_path,
                    stream=BytesIO(file.content),
                    content_type=content_type,
                    metadata=storage_metadata,
                    allow_overwrite=True,
                )
            )
        except Exception as exc:
            node_id = context.node_id or "<unknown>"
            raise RuntimeError(
                f"Failed to persist interpreted file output for node {node_id!r} "
                f"at {self._bucket}/{storage_path}"
            ) from exc
        metadata: JsonObject = {
            "producer_node_id": context.node_id,
            "content_hash": content_hash,
            "confirmed_with": spec.confirmation_rule.rule,
            "interpreted_from": {
                "artifact_id": str(source.artifact_id),
                "artifact_type": source.artifact_type,
                "schema_version": source.schema_version,
            },
        }
        if file.original_filename is not None:
            metadata["original_filename"] = file.original_filename
        artifact = ArtifactObject(
            workspace_id=context.workspace_id,
            artifact_type=key.id,
            schema_version=key.schema_version,
            content_type=content_type,
            storage_backend=self._storage_backend,
            bucket=stored_file.bucket,
            object_key=stored_file.path,
            byte_size=stored_file.byte_size,
            sha256=stored_file.sha256,
            metadata=metadata,
        )
        async with self._uow as uow:
            await uow.artifacts.add(artifact)
            await uow.commit()
        return InterpretFileOutput(file=artifact.ref())


__all__ = [
    "FORMAT_ARTIFACT_TYPE_VARIABLE",
    "InterpretFileInput",
    "InterpretFileNode",
    "InterpretFileOutput",
]
