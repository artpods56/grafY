"""Catalog contracts a Plugin family declares for its nodes."""

import re
from typing import ClassVar, Literal, Self, cast

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    field_validator,
    model_validator,
)
from pydantic.errors import PydanticInvalidForJsonSchema

from grafy_core.artifacts import (
    ArtifactBundleContract,
    ArtifactBundleFormat,
    ArtifactConfirmationRule,
    ArtifactReferenceContract,
    ArtifactReferenceShape,
    ArtifactTypeKey,
    ArtifactTypeSpec,
    ConfirmationRule,
    MaterializedJsonType,
    validate_extension_claims,
)
from grafy_core.conversions import ArtifactConversion, ArtifactConversionKey
from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_core.nodes import (
    ArtifactTypeVariable,
    InputPortSpec,
    OutputPortSpec,
    PortShape,
)
from grafy_core.plugins import NodeCachePolicy, NodeRegistration, Plugin

PluginPortDirection = Literal["input", "output"]


class PluginReleaseError(ValueError):
    """A Plugin release or catalog contract is invalid."""


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


class PluginMagicSegment(PluginReleaseValue):
    """One magic signature segment, with its bytes carried as lowercase hex."""

    offset: int = Field(ge=0, strict=True)
    value: str = Field(pattern=r"^(?:[0-9a-f]{2})+$", max_length=4_096)


class PluginMagicSignature(PluginReleaseValue):
    segments: tuple[PluginMagicSegment, ...] = Field(min_length=1)


class PluginConfirmationRule(PluginReleaseValue):
    rule: ConfirmationRule = "none"
    signatures: tuple[PluginMagicSignature, ...] = ()

    @model_validator(mode="after")
    def validate_signatures(self) -> Self:
        if self.rule == "magic" and not self.signatures:
            raise ValueError("A magic confirmation rule requires a signature")
        if self.rule != "magic" and self.signatures:
            raise ValueError("Only a magic confirmation rule may declare signatures")
        return self

    @classmethod
    def from_rule(cls, rule: ArtifactConfirmationRule) -> Self:
        return cls(
            rule=rule.rule,
            signatures=tuple(
                PluginMagicSignature(
                    segments=tuple(
                        PluginMagicSegment(
                            offset=segment.offset,
                            value=segment.value.hex(),
                        )
                        for segment in signature.segments
                    )
                )
                for signature in rule.signatures
            ),
        )


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
    extensions: tuple[str, ...] = ()
    confirmation_rule: PluginConfirmationRule = PluginConfirmationRule()

    @model_validator(mode="after")
    def validate_extension_claims(self) -> Self:
        validate_extension_claims(self.key.id, self.extensions)
        return self

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
            extensions=spec.extensions,
            confirmation_rule=PluginConfirmationRule.from_rule(spec.confirmation_rule),
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
    also_accepts: tuple[PluginArtifactTypeKey, ...] = ()
    shape: PortShape
    accepted_shapes: tuple[PortShape, ...] = Field(min_length=1)
    instance_plugs: bool = False
    variadic: bool = False
    required: bool = True
    shape_field: str | None = Field(default=None, min_length=1, max_length=255)

    @model_validator(mode="after")
    def validate_artifact_type_contract(self) -> Self:
        if (self.artifact_type is None) == (self.artifact_type_variable is None):
            raise ValueError(
                "Plugin port must declare exactly one artifact type or type variable"
            )
        if not self.also_accepts:
            return self
        if self.artifact_type is None:
            raise ValueError(
                "Plugin port additional accepted artifact types require a primary "
                "artifact type"
            )
        if self.artifact_type in self.also_accepts:
            raise ValueError(
                "Plugin port repeats its primary artifact type among its additional "
                "accepted artifact types"
            )
        if len(set(self.also_accepts)) != len(self.also_accepts):
            raise ValueError(
                "Plugin port declares duplicate additional accepted artifact types"
            )
        return self

    @property
    def accepted_types(self) -> tuple[PluginArtifactTypeKey, ...]:
        """Concrete artifact types this port accepts, primary type first."""

        if self.artifact_type is None:
            return ()
        return (self.artifact_type, *self.also_accepts)

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
            also_accepts=tuple(
                PluginArtifactTypeKey.from_key(key) for key in port.also_accepts
            ),
            shape=port.shape,
            accepted_shapes=port.accepted_shapes,
            instance_plugs=port.instance_plugs,
            variadic=port.variadic,
            required=port.required,
            shape_field=port.shape_field,
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
            shape_field=port.shape_field,
        )


class PluginSecretInputContract(PluginReleaseValue):
    name: str = Field(min_length=1, max_length=255)
    config_dependencies: tuple[str, ...] = ()
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4_000)


class PluginNodeHttpEgressContract(PluginReleaseValue):
    """Immutable declaration of one node's network.egress destination sources."""

    configured_inputs: tuple[str, ...] = ()
    fixed_destinations: tuple[str, ...] = ()
    dynamic_destinations: bool = False

    @field_validator("fixed_destinations")
    @classmethod
    def validate_fixed_destinations(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        origins: list[str] = []
        for origin in value:
            url = TypeAdapter(AnyHttpUrl).validate_python(origin)
            if (
                origin != origin.strip()
                or url.username is not None
                or url.password is not None
                or url.query is not None
                or url.fragment is not None
                or url.path not in {None, "/"}
            ):
                raise ValueError(
                    "Fixed HTTP destinations must be origins without credentials, paths, queries, or fragments"
                )
            origins.append(str(url).rstrip("/"))
        if len(origins) != len(set(origins)) or len(origins) > 8:
            raise ValueError(
                "Fixed HTTP destinations must be unique and contain at most eight origins"
            )
        return tuple(origins)

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
            if (
                re.fullmatch(r"[a-z][a-z0-9_]*", field_name) is None
                or len(field_name) > 255
            ):
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
    required_capabilities: tuple[PluginRuntimeCapability, ...] = ()
    cache_policy: NodeCachePolicy = NodeCachePolicy.NEVER
    http_egress: PluginNodeHttpEgressContract | None = None
    listed: bool = True

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
                    fixed_destinations=registration.http_egress.fixed_destinations,
                    dynamic_destinations=registration.http_egress.dynamic_destinations,
                )
            ),
            listed=registration.listed,
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


__all__ = [
    "PluginArtifactBundleContract",
    "PluginConfirmationRule",
    "PluginMagicSegment",
    "PluginMagicSignature",
    "PluginArtifactReferenceContract",
    "PluginArtifactConversionContract",
    "PluginArtifactConversionKey",
    "PluginArtifactTypeContract",
    "PluginArtifactTypeKey",
    "PluginCatalogManifest",
    "PluginExportFormat",
    "PluginFieldProjection",
    "PluginNodeContract",
    "PluginNodeHttpEgressContract",
    "PluginPortContract",
    "PluginPortDirection",
    "PluginReleaseError",
    "PluginSecretInputContract",
]
