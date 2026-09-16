from asyncio import sleep
from ipaddress import ip_address
from typing import Annotated, final, override

from pydantic import (
    AnyHttpUrl,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    TypeAdapter,
    field_validator,
)

from grafy_core.artifacts import ArtifactRef, NodeConfig, NodeInput, NodeOutput
from grafy_core.domain.errors import NotFoundError
from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_core.file_artifacts import FileArtifactError, load_file_artifact
from grafy_core.file_contracts import JSON_FILE
from grafy_core.nodes import (
    InPort,
    Node,
    NodeExecutionContext,
    OutPort,
    UserFacingNodeError,
)
from grafy_core.plugins import (
    NodeCachePolicy,
    NodeHttpEgressContract,
    NodeHttpEgressInput,
    NodeSecretInput,
    PluginRuntimeContext,
)
from grafy_core.ports.artifacts import UnitOfWorkPort
from grafy_core.ports.node_secrets import NodeSecretResolverPort
from grafy_core.ports.storage import FileStoragePort
from grafy_core.table_contracts import TABLE_DATA, Table

from grafy_plugin.artifacts import (
    SGKP_DATASET,
    SGKP_REFERENCE_CANDIDATE,
    SGKP_REFERENCE_DECISION,
)
from grafy_plugin.declaration import PLUGIN
from grafy_plugin.dictionaries import bundled_abbreviations, bundled_settlement_mapping
from grafy_plugin.models import ReferenceCandidate, ReferenceDecision, SgkpDataset
from grafy_plugin.processing import (
    DEFAULT_LONG_TEXT_THRESHOLD,
    ModelResponseError,
    apply_decisions,
    build_prompt,
    candidates_table,
    collect_candidates,
    correction_prompt,
    normalize_response,
    parse_model_json,
    parse_sgkp_records,
    results_table,
    short_error,
)
from grafy_plugin.provider import (
    ClassificationProvider,
    ClassificationProviderError,
    OpenAICompatibleClassificationProvider,
    ProviderSettings,
)


class ImportJsonInput(NodeInput):
    file: Annotated[
        ArtifactRef,
        InPort(JSON_FILE),
        Field(description="SGKP JSON file artifact to import."),
    ]


class ImportJsonOutput(NodeOutput):
    dataset: Annotated[
        SgkpDataset,
        OutPort(SGKP_DATASET),
        Field(description="Parsed SGKP gazetteer records."),
    ]


@PLUGIN.node(
    operator_id="sgkp.dataset.import_json",
    version=1,
    title="Import SGKP JSON",
    factory=lambda context: ImportSgkpJsonNode(
        storage=context.storage,
        uow=context.uow,
    ),
    cache_policy=NodeCachePolicy.EXACT,
)
@final
class ImportSgkpJsonNode(Node[NodeConfig, ImportJsonInput, ImportJsonOutput]):
    """Imports one SGKP JSON array of gazetteer records from a file artifact."""

    def __init__(self, *, storage: FileStoragePort, uow: UnitOfWorkPort) -> None:
        self._storage = storage
        self._uow = uow

    @override
    async def run(
        self,
        context: NodeExecutionContext,
        _config: NodeConfig,
        inputs: ImportJsonInput,
        /,
    ) -> ImportJsonOutput:
        try:
            file = await load_file_artifact(
                storage=self._storage,
                uow=self._uow,
                workspace_id=context.workspace_id,
                ref=inputs.file,
            )
        except (FileArtifactError, NotFoundError) as exc:
            raise UserFacingNodeError(str(exc)) from exc
        await context.progress("Parsing SGKP JSON")
        # A missing recorded name hits the parser's blank-source rule.
        source_name = file.original_filename or ""
        try:
            dataset = parse_sgkp_records(file.content, source_name=source_name)
        except ValueError as exc:
            raise UserFacingNodeError(str(exc)) from exc
        return ImportJsonOutput(dataset=dataset)


class SelectReferencesConfig(NodeConfig):
    all_references: StrictBool = Field(
        default=False,
        description="Include every odsyłacz, including entries without a text signal.",
    )
    long_text_threshold: StrictInt = Field(
        default=DEFAULT_LONG_TEXT_THRESHOLD,
        ge=1,
        le=10_000,
        description="Minimum text length treated as a broader-description signal.",
    )


class SelectReferencesInput(NodeInput):
    dataset: Annotated[
        SgkpDataset,
        InPort(SGKP_DATASET),
        Field(description="Imported SGKP gazetteer records."),
    ]


class SelectReferencesOutput(NodeOutput):
    candidates: Annotated[
        list[ReferenceCandidate],
        OutPort(SGKP_REFERENCE_CANDIDATE),
        Field(description="Reference entries selected for classification."),
    ]
    table: Annotated[
        Table,
        OutPort(TABLE_DATA),
        Field(description="Inspectable candidate table."),
    ]


@PLUGIN.function_node(
    operator_id="sgkp.references.select",
    version=1,
    title="Select SGKP reference candidates",
    cache_policy=NodeCachePolicy.EXACT,
)
async def select_references(
    context: NodeExecutionContext,
    config: SelectReferencesConfig,
    inputs: SelectReferencesInput,
) -> SelectReferencesOutput:
    """Find odsyłacz entries that may also name a settlement type."""

    await context.progress("Selecting SGKP reference candidates")
    try:
        selection = collect_candidates(
            inputs.dataset,
            all_references=config.all_references,
            long_text_threshold=config.long_text_threshold,
        )
    except ValueError as exc:
        raise UserFacingNodeError(str(exc)) from exc
    await context.progress(
        "Selected SGKP reference candidates",
        current=len(selection.candidates),
        total=selection.reference_count,
    )
    return SelectReferencesOutput(
        candidates=list(selection.candidates),
        table=candidates_table(selection.candidates),
    )


class ClassifyReferenceConfig(NodeConfig):
    base_url: StrictStr = Field(
        default="https://ai-test.ihpan.edu.pl/v1",
        min_length=1,
        description="OpenAI-compatible API base URL including the version path.",
    )
    model: StrictStr = Field(
        default="gemma-4-31b-it",
        min_length=1,
        description="Provider model identifier.",
    )
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    max_completion_tokens: StrictInt = Field(default=2_048, ge=1, le=1_000_000)
    timeout_ms: StrictInt = Field(default=120_000, ge=1_000, le=900_000)
    max_retries: StrictInt = Field(
        default=5,
        ge=1,
        le=8,
        description="Attempts for transient provider failures and invalid JSON.",
    )
    retry_delay_ms: StrictInt = Field(
        default=5_000,
        ge=0,
        le=60_000,
        description="Delay between transient retries.",
    )

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("base_url must not have surrounding whitespace")
        url = TypeAdapter(AnyHttpUrl).validate_python(value)
        if url.username is not None or url.password is not None:
            raise ValueError("base_url must not include user information")
        if url.query is not None or url.fragment is not None:
            raise ValueError("base_url must not include a query or fragment")
        host = url.host
        if host is None:
            raise ValueError("base_url must include a host")
        if url.scheme == "http":
            normalized_host = host[1:-1] if host.startswith("[") else host
            is_loopback = normalized_host == "localhost"
            if not is_loopback:
                try:
                    is_loopback = ip_address(normalized_host).is_loopback
                except ValueError:
                    is_loopback = False
            if not is_loopback:
                raise ValueError(
                    "base_url must use HTTPS unless it targets localhost or a "
                    "loopback IP address"
                )
        return str(url).rstrip("/")


class ClassifyReferenceInput(NodeInput):
    candidate: Annotated[
        ReferenceCandidate,
        InPort(SGKP_REFERENCE_CANDIDATE),
        Field(description="One selected SGKP reference candidate."),
    ]


class ClassifyReferenceOutput(NodeOutput):
    decision: Annotated[
        ReferenceDecision,
        OutPort(SGKP_REFERENCE_DECISION),
        Field(description="Validated model decision for one candidate."),
    ]


def build_classify_reference_node(
    context: PluginRuntimeContext,
) -> "ClassifyReferenceNode":
    return ClassifyReferenceNode(
        provider=OpenAICompatibleClassificationProvider(),
        node_secrets=context.node_secrets,
    )


@PLUGIN.node(
    operator_id="sgkp.references.classify",
    version=1,
    title="Classify SGKP reference type",
    factory=build_classify_reference_node,
    required_capabilities=(
        PluginRuntimeCapability.NETWORK_EGRESS,
        PluginRuntimeCapability.NODE_SECRETS,
    ),
    secret_inputs=(
        NodeSecretInput(
            name="api_key",
            title="API key",
            description="Write-only bearer credential for the configured endpoint.",
            config_dependencies=("base_url",),
        ),
    ),
    http_egress=NodeHttpEgressContract(
        configured_inputs=(NodeHttpEgressInput(config_field="base_url"),),
    ),
    cache_policy=NodeCachePolicy.NEVER,
)
@final
class ClassifyReferenceNode(
    Node[ClassifyReferenceConfig, ClassifyReferenceInput, ClassifyReferenceOutput]
):
    """Ask an OpenAI-compatible model whether one odsyłacz names a settlement."""

    def __init__(
        self,
        *,
        provider: ClassificationProvider,
        node_secrets: NodeSecretResolverPort,
    ) -> None:
        self._provider = provider
        self._node_secrets = node_secrets

    @override
    async def run(
        self,
        context: NodeExecutionContext,
        config: ClassifyReferenceConfig,
        inputs: ClassifyReferenceInput,
        /,
    ) -> ClassifyReferenceOutput:
        try:
            api_key = await self._node_secrets.resolve_secret(
                workspace_id=context.workspace_id,
                graph_id=context.secret_graph_id,
                graph_revision=context.secret_graph_revision,
                node_id=context.node_id,
                name="api_key",
                dependencies={"base_url": config.base_url},
            )
        except Exception as exc:
            raise UserFacingNodeError(
                "SGKP classification could not resolve its API key for "
                f"node {context.node_id!r} and base URL {config.base_url!r}"
            ) from exc

        abbreviations_text, abbreviations = bundled_abbreviations()
        settlement_mapping = bundled_settlement_mapping()
        prompt = build_prompt(inputs.candidate, abbreviations_text)
        current_prompt = prompt
        settings = ProviderSettings(
            base_url=config.base_url,
            model=config.model,
            temperature=config.temperature,
            max_completion_tokens=config.max_completion_tokens,
            timeout_ms=config.timeout_ms,
        )
        last_output = ""
        await context.progress(f"Classifying {inputs.candidate.entry_id}")
        for attempt in range(1, config.max_retries + 1):
            try:
                last_output = await self._provider.complete(
                    current_prompt, settings, api_key
                )
                decision = normalize_response(
                    parse_model_json(last_output),
                    inputs.candidate,
                    settlement_mapping=settlement_mapping,
                    abbreviations=abbreviations,
                    model=config.model,
                )
                return ClassifyReferenceOutput(decision=decision)
            except ClassificationProviderError as exc:
                if not exc.transient or attempt == config.max_retries:
                    raise UserFacingNodeError(str(exc)) from exc
                await sleep(config.retry_delay_ms / 1_000)
            except (ModelResponseError, ValueError) as exc:
                if attempt == config.max_retries:
                    raw_output = getattr(exc, "raw_output", last_output)
                    raise UserFacingNodeError(
                        f"Model response for {inputs.candidate.entry_id} was invalid: "
                        f"{short_error(exc)}"
                    ) from ModelResponseError(short_error(exc), raw_output)
                current_prompt = correction_prompt(prompt, exc, last_output)
                await sleep(min(5.0, config.retry_delay_ms / 1_000))
        raise UserFacingNodeError(
            f"Model response for {inputs.candidate.entry_id} was invalid"
        )


class ApplyReferenceTypesConfig(NodeConfig):
    apply_medium_confidence: StrictBool = Field(
        default=False,
        description="Also apply decisions whose confidence is średnia.",
    )


class ApplyReferenceTypesInput(NodeInput):
    dataset: Annotated[
        SgkpDataset,
        InPort(SGKP_DATASET),
        Field(description="Original SGKP gazetteer records."),
    ]
    decisions: Annotated[
        list[ReferenceDecision],
        InPort(SGKP_REFERENCE_DECISION),
        Field(description="Validated classification decisions."),
    ]


class ApplyReferenceTypesOutput(NodeOutput):
    dataset: Annotated[
        SgkpDataset,
        OutPort(SGKP_DATASET),
        Field(description="SGKP records with accepted type repairs applied."),
    ]
    table: Annotated[
        Table,
        OutPort(TABLE_DATA),
        Field(description="Inspectable apply results."),
    ]


@PLUGIN.function_node(
    operator_id="sgkp.references.apply",
    version=1,
    title="Apply SGKP reference types",
    cache_policy=NodeCachePolicy.EXACT,
)
async def apply_reference_types(
    context: NodeExecutionContext,
    config: ApplyReferenceTypesConfig,
    inputs: ApplyReferenceTypesInput,
) -> ApplyReferenceTypesOutput:
    """Write high-confidence settlement types back into the SGKP dataset."""

    await context.progress("Applying SGKP reference-type decisions")
    try:
        applied = apply_decisions(
            inputs.dataset,
            inputs.decisions,
            apply_medium_confidence=config.apply_medium_confidence,
        )
    except ValueError as exc:
        raise UserFacingNodeError(str(exc)) from exc
    await context.progress(
        "Applied SGKP reference-type decisions",
        current=applied.changed_records,
        total=len(inputs.decisions),
    )
    return ApplyReferenceTypesOutput(
        dataset=applied.dataset,
        table=results_table(applied),
    )
