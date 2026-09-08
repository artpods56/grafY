"""Append-only Plugin releases and their catalog contracts."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
import json
import re
from typing import TYPE_CHECKING, ClassVar, Literal, Self, cast
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.errors import PydanticInvalidForJsonSchema

from grafy_core.artifacts import (
    ArtifactBundleContract,
    ArtifactBundleFormat,
    ArtifactReferenceContract,
    ArtifactReferenceShape,
    ArtifactTypeKey,
    ArtifactTypeSpec,
    MaterializedJsonType,
)
from grafy_core.conversions import ArtifactConversion, ArtifactConversionKey
from grafy_core.domain.plugin_identity import (
    PluginExecutionPolicy,
    PlatformPluginActor,
    PluginReleaseNamespace,
    PluginReleaseScope,
)
from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_core.nodes import (
    ArtifactTypeVariable,
    InputPortSpec,
    OutputPortSpec,
    PortShape,
)
from grafy_core.plugins import NodeCachePolicy, NodeRegistration, Plugin


if TYPE_CHECKING:
    from grafy_core.domain.plugin_installations import InstalledPluginRelease


PluginPortDirection = Literal["input", "output"]

PLUGIN_INVOCATION_PROTOCOL = "grafy-plugin-invocation@7"


def plugin_protocol_digest() -> str:
    """Digest of the artifact invocation protocol a release was inspected for."""

    return sha256(PLUGIN_INVOCATION_PROTOCOL.encode("utf-8")).hexdigest()


def plugin_profile_digest(runtime_profile: str) -> str:
    return sha256(runtime_profile.strip().encode("utf-8")).hexdigest()


_EMPTY_HTTP_EGRESS_SERIALIZATION = ',"http_egress":null'


def plugin_contract_digest(catalog: PluginCatalogManifest) -> str:
    """Digest of the serialized catalog contract.

    Absent HTTP-egress declarations are dropped before hashing so a catalog
    parsed with the newer contract fields digests identically to the bytes
    persisted before that field existed.
    """

    serialized = catalog.model_dump_json()
    if _EMPTY_HTTP_EGRESS_SERIALIZATION in serialized:
        serialized = serialized.replace(_EMPTY_HTTP_EGRESS_SERIALIZATION, "")
    return sha256(serialized.encode("utf-8")).hexdigest()


class PluginReleaseError(ValueError):
    """A Plugin release or catalog contract is invalid."""


class PluginReleaseHeadConflictError(PluginReleaseError):
    """Publication no longer matches the Workspace release that was reviewed."""

    def __init__(
        self,
        *,
        workspace_id: UUID,
        slug: str,
        expected_revision: int,
        actual_revision: int,
    ) -> None:
        self.workspace_id = workspace_id
        self.slug = slug
        self.expected_revision = expected_revision
        self.actual_revision = actual_revision
        super().__init__(
            f"Plugin release head changed after review for Workspace {workspace_id}, "
            f"family {slug!r}: expected revision {expected_revision}, "
            f"actual revision {actual_revision}"
        )


class PluginReleaseValue(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
    )


class PluginRuntimeArtifact(PluginReleaseValue):
    """Immutable provider-neutral reference to one stored OCI image layout."""

    format: Literal["oci-archive"] = "oci-archive"
    media_type: Literal["application/vnd.oci.image.manifest.v1+json"] = (
        "application/vnd.oci.image.manifest.v1+json"
    )
    object_key: str = Field(min_length=1, max_length=2_048)
    archive_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    config_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("object_key")
    @classmethod
    def validate_object_key(cls, value: str) -> str:
        if value.startswith("/") or ".." in value.split("/") or "\\" in value:
            raise ValueError("Plugin runtime artifact object key must be safe")
        return value


class PluginArtifactTypeKey(PluginReleaseValue):
    id: str = Field(min_length=1, max_length=255)
    schema_version: int = Field(ge=1, strict=True)

    @classmethod
    def from_key(cls, key: ArtifactTypeKey) -> Self:
        return cls(id=key.id, schema_version=key.schema_version)


class PluginFieldProjection(PluginReleaseValue):
    path: tuple[str, ...] = Field(min_length=1)
    target: PluginArtifactTypeKey
    title: str = Field(min_length=1, max_length=255)


class PluginExportFormat(PluginReleaseValue):
    format: str = Field(min_length=1, max_length=64)
    content_type: str = Field(min_length=1, max_length=255)
    filename: str = Field(min_length=1, max_length=255)


class PluginArtifactBundleContract(PluginReleaseValue):
    format: ArtifactBundleFormat
    version: int = Field(ge=1, strict=True)

    @classmethod
    def from_contract(cls, contract: ArtifactBundleContract) -> Self:
        return cls(format=contract.format, version=contract.version)


class PluginArtifactReferenceContract(PluginReleaseValue):
    path: tuple[str, ...] = Field(min_length=1)
    target: PluginArtifactTypeKey
    shape: ArtifactReferenceShape

    @classmethod
    def from_contract(
        cls,
        contract: ArtifactReferenceContract,
    ) -> "PluginArtifactReferenceContract":
        return cls(
            path=contract.path,
            target=PluginArtifactTypeKey.from_key(contract.target),
            shape=contract.shape,
        )


class PluginArtifactTypeContract(PluginReleaseValue):
    key: PluginArtifactTypeKey
    title: str = Field(min_length=1, max_length=255)
    payload_schema: dict[str, object] = Field(default_factory=dict)
    field_projections: tuple[PluginFieldProjection, ...] = ()
    materialized_json_type: MaterializedJsonType | None = None
    export_formats: tuple[PluginExportFormat, ...] = ()
    references: tuple[PluginArtifactReferenceContract, ...] = ()
    bundle: PluginArtifactBundleContract = PluginArtifactBundleContract(
        format="inline-json",
        version=1,
    )

    @classmethod
    def from_spec(cls, spec: ArtifactTypeSpec) -> Self:
        return cls(
            key=PluginArtifactTypeKey.from_key(spec.key),
            title=spec.title,
            payload_schema=spec.payload_schema,
            materialized_json_type=spec.materialized_json_type,
            field_projections=tuple(
                PluginFieldProjection(
                    path=projection.path,
                    target=PluginArtifactTypeKey.from_key(projection.target),
                    title=projection.title,
                )
                for projection in spec.field_projections
            ),
            export_formats=tuple(
                PluginExportFormat(
                    format=export_format.format,
                    content_type=export_format.content_type,
                    filename=export_format.filename,
                )
                for export_format in spec.export_formats
            ),
            references=tuple(
                PluginArtifactReferenceContract.from_contract(reference)
                for reference in spec.references
            ),
            bundle=PluginArtifactBundleContract.from_contract(spec.bundle),
        )


class PluginArtifactConversionKey(PluginReleaseValue):
    id: str = Field(min_length=1, max_length=255)
    version: int = Field(ge=1, strict=True)

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError(
                "Plugin artifact conversion id must not contain whitespace"
            )
        return value

    @classmethod
    def from_key(cls, key: ArtifactConversionKey) -> Self:
        return cls(id=key.id, version=key.version)


class PluginArtifactConversionContract(PluginReleaseValue):
    key: PluginArtifactConversionKey
    source: PluginArtifactTypeKey
    target: PluginArtifactTypeKey
    title: str = Field(min_length=1, max_length=255)

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        if value.strip() == "":
            raise ValueError("Plugin artifact conversion title must not be blank")
        return value

    @classmethod
    def from_conversion[SourceT, TargetT](
        cls,
        conversion: ArtifactConversion[SourceT, TargetT],
    ) -> Self:
        return cls(
            key=PluginArtifactConversionKey.from_key(conversion.key),
            source=PluginArtifactTypeKey.from_key(conversion.source),
            target=PluginArtifactTypeKey.from_key(conversion.target),
            title=conversion.title,
        )


class PluginPortContract(PluginReleaseValue):
    name: str = Field(min_length=1, max_length=255)
    title: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=4_000)
    direction: PluginPortDirection
    artifact_type: PluginArtifactTypeKey | None = None
    artifact_type_variable: str | None = Field(default=None, max_length=255)
    shape: PortShape
    accepted_shapes: tuple[PortShape, ...] = Field(min_length=1)
    instance_plugs: bool = False
    variadic: bool = False
    required: bool = True

    @model_validator(mode="after")
    def validate_artifact_type_contract(self) -> Self:
        if (self.artifact_type is None) == (self.artifact_type_variable is None):
            raise ValueError(
                "Plugin port must declare exactly one artifact type or type variable"
            )
        return self

    @classmethod
    def from_input_port(cls, port: InputPortSpec) -> Self:
        artifact_type: PluginArtifactTypeKey | None
        artifact_type_variable: str | None
        if isinstance(port.accepts, ArtifactTypeVariable):
            artifact_type = None
            artifact_type_variable = port.accepts.name
        else:
            artifact_type = PluginArtifactTypeKey.from_key(port.accepts)
            artifact_type_variable = None
        return cls(
            name=port.name,
            title=port.title,
            description=port.description,
            direction="input",
            artifact_type=artifact_type,
            artifact_type_variable=artifact_type_variable,
            shape=port.shape,
            accepted_shapes=port.accepted_shapes,
            instance_plugs=port.instance_plugs,
            variadic=port.variadic,
            required=port.required,
        )

    @classmethod
    def from_output_port(cls, port: OutputPortSpec) -> Self:
        artifact_type: PluginArtifactTypeKey | None
        artifact_type_variable: str | None
        if isinstance(port.produces, ArtifactTypeVariable):
            artifact_type = None
            artifact_type_variable = port.produces.name
        else:
            artifact_type = PluginArtifactTypeKey.from_key(port.produces)
            artifact_type_variable = None
        return cls(
            name=port.name,
            title=port.title,
            description=port.description,
            direction="output",
            artifact_type=artifact_type,
            artifact_type_variable=artifact_type_variable,
            shape=port.shape,
            accepted_shapes=(port.shape,),
            required=port.required,
        )


class PluginSecretInputContract(PluginReleaseValue):
    name: str = Field(min_length=1, max_length=255)
    config_dependencies: tuple[str, ...] = ()
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4_000)


class PluginStagedUploadInputContract(PluginReleaseValue):
    config_field: str = Field(
        pattern=r"^[a-z][a-z0-9_]*$",
        min_length=1,
        max_length=255,
    )


class PluginNodeHttpEgressContract(PluginReleaseValue):
    """Immutable declaration of one node's network.egress destination sources."""

    configured_inputs: tuple[str, ...] = ()
    dynamic_destinations: bool = False

    @field_validator("configured_inputs")
    @classmethod
    def validate_configured_inputs(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("Node HTTP egress config fields must be unique")
        if len(value) > 8:
            raise ValueError(
                "Node HTTP egress declares more than eight configured fields"
            )
        for field_name in value:
            if re.fullmatch(r"[a-z][a-z0-9_]*", field_name) is None or len(
                field_name
            ) > 255:
                raise ValueError(
                    "Node HTTP egress configured inputs must be config field names"
                )
        return value


class PluginNodeContract(PluginReleaseValue):
    operator_id: str = Field(min_length=1, max_length=255)
    operator_version: int = Field(ge=1, strict=True)
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(max_length=4_000)
    config_schema: dict[str, object]
    input_schema: dict[str, object]
    output_schema: dict[str, object]
    inputs: tuple[PluginPortContract, ...]
    outputs: tuple[PluginPortContract, ...]
    secret_inputs: tuple[PluginSecretInputContract, ...] = ()
    staged_upload_inputs: tuple[PluginStagedUploadInputContract, ...] = ()
    required_capabilities: tuple[PluginRuntimeCapability, ...] = ()
    cache_policy: NodeCachePolicy = NodeCachePolicy.NEVER
    http_egress: PluginNodeHttpEgressContract | None = None

    @field_validator("required_capabilities")
    @classmethod
    def normalize_required_capabilities(
        cls,
        value: tuple[PluginRuntimeCapability, ...],
    ) -> tuple[PluginRuntimeCapability, ...]:
        normalized = {PluginRuntimeCapability(capability) for capability in value}
        return tuple(sorted(normalized, key=lambda capability: capability.value))

    @model_validator(mode="after")
    def validate_capability_contract(self) -> Self:
        capabilities = set(self.required_capabilities)
        if (
            self.secret_inputs
            and PluginRuntimeCapability.NODE_SECRETS not in capabilities
        ):
            raise ValueError("Plugin node secret inputs require node.secrets")
        if (
            self.staged_upload_inputs
            and PluginRuntimeCapability.STAGED_UPLOADS not in capabilities
        ):
            raise ValueError("Plugin node staged uploads require staged.uploads")
        if (
            self.http_egress is not None
            and PluginRuntimeCapability.NETWORK_EGRESS not in capabilities
        ):
            raise ValueError("Plugin node HTTP egress requires network.egress")
        if self.operator_id == "sql.artifacts.query" and capabilities != {
            PluginRuntimeCapability.UNTRUSTED_SQL
        }:
            raise ValueError("sql.artifacts.query must require exactly sql.untrusted")
        return self

    @classmethod
    def from_registration(cls, registration: NodeRegistration) -> Self:
        node_class = registration.node_class
        return cls(
            operator_id=node_class.operator_id,
            operator_version=node_class.operator_version,
            title=registration.title,
            description=registration.description,
            config_schema=_model_json_schema(node_class.config_contract.model),
            input_schema=_model_json_schema(node_class.input_contract.model),
            output_schema=_model_json_schema(node_class.output_contract.model),
            inputs=tuple(
                PluginPortContract.from_input_port(port)
                for port in node_class.input_contract.ports.values()
            ),
            outputs=tuple(
                PluginPortContract.from_output_port(port)
                for port in node_class.output_contract.ports.values()
            ),
            secret_inputs=tuple(
                PluginSecretInputContract(
                    name=secret.name,
                    config_dependencies=secret.config_dependencies,
                    title=secret.title,
                    description=secret.description,
                )
                for secret in registration.secret_inputs
            ),
            staged_upload_inputs=tuple(
                PluginStagedUploadInputContract(
                    config_field=staged_upload.config_field,
                )
                for staged_upload in registration.staged_upload_inputs
            ),
            required_capabilities=registration.required_capabilities,
            cache_policy=registration.cache_policy,
            http_egress=(
                None
                if registration.http_egress is None
                else PluginNodeHttpEgressContract(
                    configured_inputs=tuple(
                        configured_input.config_field
                        for configured_input in registration.http_egress.configured_inputs
                    ),
                    dynamic_destinations=registration.http_egress.dynamic_destinations,
                )
            ),
        )


class PluginCatalogManifest(PluginReleaseValue):
    slug: str = Field(pattern=r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$", max_length=100)
    title: str = Field(min_length=1, max_length=160)
    artifact_types: tuple[PluginArtifactTypeContract, ...] = ()
    artifact_type_dependencies: tuple[PluginArtifactTypeContract, ...] = ()
    artifact_conversions: tuple[PluginArtifactConversionContract, ...] = ()
    nodes: tuple[PluginNodeContract, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_catalog_identity(self) -> Self:
        node_keys = [(node.operator_id, node.operator_version) for node in self.nodes]
        if len(node_keys) != len(set(node_keys)):
            raise ValueError(
                "Plugin catalog nodes must have unique operator identities"
            )
        artifact_keys = [
            (artifact.key.id, artifact.key.schema_version)
            for artifact in self.artifact_types
        ]
        if len(artifact_keys) != len(set(artifact_keys)):
            raise ValueError("Plugin artifact types must have unique identities")
        dependency_keys = [
            (dependency.key.id, dependency.key.schema_version)
            for dependency in self.artifact_type_dependencies
        ]
        if len(dependency_keys) != len(set(dependency_keys)):
            raise ValueError(
                "Plugin artifact type dependencies must have unique identities"
            )
        owned_dependency_overlap = set(artifact_keys) & set(dependency_keys)
        if owned_dependency_overlap:
            artifact_id, schema_version = sorted(owned_dependency_overlap)[0]
            raise ValueError(
                f"Plugin {self.slug!r} cannot both own and depend on artifact type "
                f"{artifact_id}@{schema_version}"
            )
        conversion_keys = [
            (conversion.key.id, conversion.key.version)
            for conversion in self.artifact_conversions
        ]
        if len(conversion_keys) != len(set(conversion_keys)):
            raise ValueError("Plugin artifact conversions must have unique identities")
        declared_artifact_keys = set(artifact_keys) | set(dependency_keys)
        for node in self.nodes:
            for port in (*node.inputs, *node.outputs):
                if port.artifact_type is None:
                    continue
                key = (
                    port.artifact_type.id,
                    port.artifact_type.schema_version,
                )
                if key in declared_artifact_keys:
                    continue
                raise ValueError(
                    f"Plugin {self.slug!r} node {node.operator_id}@"
                    f"{node.operator_version} {port.direction} port {port.name!r} "
                    f"references artifact type {key[0]}@{key[1]}, which is neither "
                    "owned nor declared as an exact dependency"
                )
        for artifact in (*self.artifact_types, *self.artifact_type_dependencies):
            for projection in artifact.field_projections:
                target = (
                    projection.target.id,
                    projection.target.schema_version,
                )
                if target in declared_artifact_keys:
                    continue
                rendered_path = ".".join(projection.path)
                raise ValueError(
                    f"Plugin {self.slug!r} artifact type {artifact.key.id}@"
                    f"{artifact.key.schema_version} field projection "
                    f"{rendered_path!r} targets artifact type {target[0]}@"
                    f"{target[1]}, which is neither owned nor declared as an exact "
                    "dependency"
                )
            for reference in artifact.references:
                target = (
                    reference.target.id,
                    reference.target.schema_version,
                )
                if target in declared_artifact_keys:
                    continue
                rendered_path = ".".join(reference.path)
                raise ValueError(
                    f"Plugin {self.slug!r} artifact type {artifact.key.id}@"
                    f"{artifact.key.schema_version} reference {rendered_path!r} "
                    f"targets artifact type {target[0]}@{target[1]}, which is "
                    "neither owned nor declared as an exact dependency"
                )
        for conversion in self.artifact_conversions:
            for endpoint_name, endpoint in (
                ("source", conversion.source),
                ("target", conversion.target),
            ):
                key = (endpoint.id, endpoint.schema_version)
                if key in declared_artifact_keys:
                    continue
                raise ValueError(
                    f"Plugin {self.slug!r} artifact conversion "
                    f"{conversion.key.id}@{conversion.key.version} references "
                    f"{endpoint_name} artifact type {key[0]}@{key[1]}, which is "
                    "neither owned nor declared as an exact dependency"
                )
        return self

    @classmethod
    def from_plugin(cls, plugin: Plugin) -> Self:
        return cls(
            slug=plugin.slug,
            title=plugin.title,
            artifact_types=tuple(
                PluginArtifactTypeContract.from_spec(spec)
                for spec in plugin.artifact_types
            ),
            artifact_type_dependencies=tuple(
                PluginArtifactTypeContract.from_spec(spec)
                for spec in plugin.artifact_type_dependencies
            ),
            artifact_conversions=tuple(
                PluginArtifactConversionContract.from_conversion(conversion)
                for conversion in plugin.artifact_conversions
            ),
            nodes=tuple(
                PluginNodeContract.from_registration(registration)
                for registration in plugin.nodes
            ),
        )


@dataclass(frozen=True, slots=True)
class PluginReleaseIdentity:
    """Exact immutable identity of one resolved Plugin release.

    Invocation fingerprints and retained provenance use this value so two
    releases containing the same operator version never share cache entries
    or diagnostics.
    """

    scope: PluginReleaseScope
    workspace_id: UUID | None
    slug: str
    revision: int
    source_digest: str
    contract_digest: str
    protocol_digest: str
    descriptor_digest: str

    @classmethod
    def from_release(cls, release: "InstalledPluginRelease") -> Self:
        return cls(
            scope=release.scope,
            workspace_id=release.workspace_id,
            slug=release.slug,
            revision=release.revision,
            source_digest=release.source_digest,
            contract_digest=release.contract_digest,
            protocol_digest=release.protocol_digest,
            descriptor_digest=release.descriptor.digest,
        )

    def fingerprint_document(self) -> dict[str, object]:
        return {
            "scope": self.scope.value,
            "workspace_id": (
                None if self.workspace_id is None else str(self.workspace_id)
            ),
            "slug": self.slug,
            "revision": self.revision,
            "source_digest": self.source_digest,
            "descriptor_digest": self.descriptor_digest,
        }

    def provenance_document(self) -> dict[str, object]:
        return {
            "scope": self.scope.value,
            "workspace_id": (
                None if self.workspace_id is None else str(self.workspace_id)
            ),
            "slug": self.slug,
            "revision": self.revision,
            "source_digest": self.source_digest,
            "contract_digest": self.contract_digest,
            "protocol_digest": self.protocol_digest,
            "descriptor_digest": self.descriptor_digest,
        }


class PluginCapabilityManifest(PluginReleaseValue):
    capabilities: tuple[PluginRuntimeCapability, ...] = ()

    @field_validator("capabilities")
    @classmethod
    def normalize_capabilities(
        cls,
        value: tuple[PluginRuntimeCapability, ...],
    ) -> tuple[PluginRuntimeCapability, ...]:
        normalized: set[PluginRuntimeCapability] = set()
        for capability in value:
            normalized.add(PluginRuntimeCapability(capability))
        return tuple(sorted(normalized, key=lambda capability: capability.value))

    @property
    def digest(self) -> str:
        payload = self.model_dump_json().encode("utf-8")
        return sha256(payload).hexdigest()


class PluginReleaseDescriptor(PluginReleaseValue):
    """Content identity inputs for idempotent immutable publication."""

    source_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    contract_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    capability_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    protocol_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    profile_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    lock_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    runtime_profile: str = Field(min_length=1, max_length=100)
    loader_target: str = Field(
        pattern=r"^[A-Za-z_][A-Za-z0-9_.]*:[A-Za-z_][A-Za-z0-9_]*$",
        max_length=255,
    )
    runtime_artifact: PluginRuntimeArtifact | None = None

    @property
    def digest(self) -> str:
        document = self.model_dump(mode="json")
        payload = json.dumps(
            document,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return sha256(payload).hexdigest()


@dataclass
class PluginRelease:
    """One immutable, scope-neutral release of a Plugin package.

    The release descriptor references independent immutable objects: the source
    archive, the inspected catalog contract, the deployment runtime profile, the
    artifact invocation protocol, and the declared capability manifest. The
    runtime image digest stays absent until the image-building slice fills it.
    """

    slug: str
    revision: int
    catalog: PluginCatalogManifest
    contract_digest: str
    capabilities: PluginCapabilityManifest
    capability_digest: str
    protocol_digest: str
    profile_digest: str
    source_object_key: str
    source_digest: str
    lock_digest: str
    runtime_profile: str
    loader_target: str
    runtime_image_digest: str | None = None
    runtime_artifact: PluginRuntimeArtifact | None = None
    descriptor_digest: str | None = None
    published_by_user_id: UUID | None = None
    published_by_platform_actor: str | None = None
    published_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        if self.published_by_platform_actor is not None:
            try:
                actor = PlatformPluginActor(self.published_by_platform_actor)
            except ValueError as exc:
                raise PluginReleaseError(str(exc)) from exc
            self.published_by_platform_actor = actor.reference
        if (
            self.published_by_user_id is not None
            and self.published_by_platform_actor is not None
        ):
            raise PluginReleaseError(
                "Plugin releases cannot have both user and platform publishers"
            )
        if self.catalog.slug != self.slug:
            raise PluginReleaseError("Plugin release slug must match its catalog")
        if isinstance(self.revision, bool) or self.revision < 1:
            raise PluginReleaseError("Plugin release revision must be positive")
        if self.contract_digest != plugin_contract_digest(self.catalog):
            raise PluginReleaseError(
                "Plugin contract digest must match the serialized catalog contract"
            )
        self.capability_digest = _sha256(
            self.capability_digest,
            "Plugin capability digest",
        )
        if self.capability_digest != self.capabilities.digest:
            raise PluginReleaseError(
                "Plugin capability digest must match the capability manifest"
            )
        has_secret_inputs = any(node.secret_inputs for node in self.catalog.nodes)
        if (
            has_secret_inputs
            and PluginRuntimeCapability.NODE_SECRETS
            not in self.capabilities.capabilities
        ):
            raise PluginReleaseError(
                "Plugin releases with secret inputs must declare the "
                "node-secrets capability"
            )
        required_node_capabilities = {
            capability
            for node in self.catalog.nodes
            for capability in node.required_capabilities
        }
        declared_capabilities = set(self.capabilities.capabilities)
        missing_node_capabilities = sorted(
            required_node_capabilities - declared_capabilities,
            key=lambda capability: capability.value,
        )
        if missing_node_capabilities:
            rendered = ", ".join(
                capability.value for capability in missing_node_capabilities
            )
            raise PluginReleaseError(
                "Plugin capability manifest omits node requirements: " + rendered
            )
        extra_release_capabilities = sorted(
            declared_capabilities - required_node_capabilities,
            key=lambda capability: capability.value,
        )
        if extra_release_capabilities:
            rendered = ", ".join(
                capability.value for capability in extra_release_capabilities
            )
            raise PluginReleaseError(
                "Plugin capability manifest exceeds exact node requirements: "
                + rendered
            )
        self.protocol_digest = _sha256(
            self.protocol_digest,
            "Plugin invocation protocol digest",
        )
        self.profile_digest = _sha256(
            self.profile_digest,
            "Plugin runtime profile digest",
        )
        if self.profile_digest != plugin_profile_digest(self.runtime_profile):
            raise PluginReleaseError(
                "Plugin profile digest must match the runtime profile"
            )
        self.source_digest = _sha256(self.source_digest, "Plugin source digest")
        self.lock_digest = _sha256(self.lock_digest, "Plugin lock digest")
        if self.runtime_image_digest is not None:
            self.runtime_image_digest = _sha256(
                self.runtime_image_digest,
                "Plugin runtime image digest",
            )
        if self.runtime_artifact is not None:
            if self.runtime_image_digest != self.runtime_artifact.manifest_digest:
                raise PluginReleaseError(
                    "Plugin runtime image digest must match its OCI artifact"
                )
        self.runtime_profile = self.runtime_profile.strip()
        if self.runtime_profile == "":
            raise PluginReleaseError("Plugin runtime profile must not be blank")
        if len(self.runtime_profile) > 100:
            raise PluginReleaseError(
                "Plugin runtime profile must be at most 100 characters"
            )
        if re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_.]*:[A-Za-z_][A-Za-z0-9_]*",
            self.loader_target,
        ) is None:
            raise PluginReleaseError("Plugin loader target is invalid")
        if self.source_object_key == "":
            raise PluginReleaseError("Plugin source object key must not be blank")
        if self.source_object_key.startswith(
            "/"
        ) or ".." in self.source_object_key.split("/"):
            raise PluginReleaseError(
                "Plugin source object key must be a safe relative path"
            )
        expected_descriptor_digest = self.descriptor.digest
        if self.descriptor_digest is None:
            self.descriptor_digest = expected_descriptor_digest
        else:
            self.descriptor_digest = _sha256(
                self.descriptor_digest,
                "Plugin release descriptor digest",
            )
            if self.descriptor_digest != expected_descriptor_digest:
                raise PluginReleaseError(
                    "Plugin release descriptor digest must match its inputs"
                )
        if self.published_at.tzinfo is None:
            raise PluginReleaseError("Plugin published_at must be timezone-aware")

    @property
    def descriptor(self) -> PluginReleaseDescriptor:
        return PluginReleaseDescriptor(
            source_digest=self.source_digest,
            contract_digest=self.contract_digest,
            capability_digest=self.capability_digest,
            protocol_digest=self.protocol_digest,
            profile_digest=self.profile_digest,
            lock_digest=self.lock_digest,
            runtime_profile=self.runtime_profile,
            loader_target=self.loader_target,
            runtime_artifact=self.runtime_artifact,
        )

    @property
    def executable(self) -> bool:
        return self.runtime_artifact is not None

def _model_json_schema(model: type[BaseModel]) -> dict[str, object]:
    try:
        return cast(dict[str, object], model.model_json_schema())
    except PydanticInvalidForJsonSchema as exc:
        return {
            "title": model.__name__,
            "type": "object",
            "x-schema-error": str(exc),
            "properties": {
                name: {
                    "title": name,
                    "x-python-type": str(model_field.annotation),
                }
                for name, model_field in model.model_fields.items()
            },
        }


def _sha256(value: str, label: str) -> str:
    if re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise PluginReleaseError(f"{label} must be a lowercase SHA-256 digest")
    return value


__all__ = [
    "PLUGIN_INVOCATION_PROTOCOL",
    "PluginArtifactBundleContract",
    "PluginArtifactReferenceContract",
    "PluginArtifactConversionContract",
    "PluginArtifactConversionKey",
    "PluginArtifactTypeContract",
    "PluginArtifactTypeKey",
    "PluginCapabilityManifest",
    "PluginCatalogManifest",
    "PluginExecutionPolicy",
    "PluginExportFormat",
    "PluginFieldProjection",
    "PluginNodeContract",
    "PluginNodeHttpEgressContract",
    "PluginPortContract",
    "PluginPortDirection",
    "PlatformPluginActor",
    "PluginRelease",
    "PluginReleaseDescriptor",
    "PluginReleaseError",
    "PluginReleaseHeadConflictError",
    "PluginReleaseIdentity",
    "PluginReleaseNamespace",
    "PluginReleaseScope",
    "PluginRuntimeArtifact",
    "PluginSecretInputContract",
    "plugin_contract_digest",
    "plugin_profile_digest",
    "plugin_protocol_digest",
]
