"""Auditable deployment cutover from unpinned host nodes to System releases."""

from collections.abc import Mapping, Sequence
from hashlib import sha256
import json
from typing import ClassVar, Literal, Self, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import (
    JSON,
    Table,
    delete,
    literal,
    select,
    text,
    type_coerce,
    update,
)
from sqlalchemy.engine import CursorResult
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from grafy_core.domain.plugin_releases import (
    PluginCatalogManifest,
    PluginReleaseScope,
)
from grafy_persistence import schema


class SystemCutoverError(RuntimeError):
    """The deployment baseline cannot be cut over safely."""


class SystemCutoverBlockedError(SystemCutoverError):
    """Mutable runtime state prevents a cutover transaction."""


class SystemCutoverPreconditionError(SystemCutoverError):
    """The database changed after its cutover audit."""


class _CutoverValue(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)


class SystemBaselineOperator(_CutoverValue):
    operator_id: str = Field(min_length=1, max_length=255)
    operator_version: int = Field(ge=1, strict=True)


class SystemBaselineArtifactType(_CutoverValue):
    artifact_type_id: str = Field(min_length=1, max_length=255)
    schema_version: int = Field(ge=1, strict=True)


class SystemBaselineRelease(_CutoverValue):
    """Exact selected release and the catalog identities it owns."""

    release_id: UUID
    slug: str = Field(pattern=r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$", max_length=100)
    revision: int = Field(ge=1, strict=True)
    selection_generation: int = Field(ge=1, strict=True)
    source_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    lock_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    descriptor_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    contract_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    capability_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    protocol_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    profile_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    runtime_image_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    runtime_archive_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    operators: tuple[SystemBaselineOperator, ...] = Field(min_length=1)
    artifact_types: tuple[SystemBaselineArtifactType, ...] = ()

    @model_validator(mode="after")
    def require_unique_catalog_identities(self) -> Self:
        for label, identities in (
            (
                "operator",
                [(item.operator_id, item.operator_version) for item in self.operators],
            ),
            (
                "artifact type",
                [
                    (item.artifact_type_id, item.schema_version)
                    for item in self.artifact_types
                ],
            ),
        ):
            if len(identities) != len(set(identities)):
                raise ValueError(
                    f"System baseline release {self.slug!r} has duplicate {label} "
                    "identities"
                )
        return self


class SystemBaselineManifest(_CutoverValue):
    """Verified, deployment-owned mapping used by the one-time cutover."""

    schema_version: Literal[1] = 1
    releases: tuple[SystemBaselineRelease, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def refuse_family_and_catalog_collisions(self) -> Self:
        slugs = [release.slug for release in self.releases]
        release_ids = [release.release_id for release in self.releases]
        if len(slugs) != len(set(slugs)):
            raise ValueError("System baseline must select exactly one release per slug")
        if len(release_ids) != len(set(release_ids)):
            raise ValueError("System baseline release IDs must be unique")

        for label, identities in (
            (
                "operator",
                [
                    (item.operator_id, item.operator_version)
                    for release in self.releases
                    for item in release.operators
                ],
            ),
            (
                "artifact type",
                [
                    (item.artifact_type_id, item.schema_version)
                    for release in self.releases
                    for item in release.artifact_types
                ],
            ),
        ):
            if len(identities) != len(set(identities)):
                raise ValueError(f"System baseline has colliding {label} mappings")
        return self


class CutoverRollbackUnit(_CutoverValue):
    """Checksums proving the assets restored together if cutover is rolled back."""

    rollback_unit_id: str = Field(min_length=1, max_length=255)
    database_backup_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    release_objects_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_storage_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    migration_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class SystemCutoverCommand(_CutoverValue):
    mode: Literal["dry-run", "apply"]
    baseline: SystemBaselineManifest
    rollback_unit: CutoverRollbackUnit
    expected_precondition_token: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )

    @model_validator(mode="after")
    def require_apply_precondition(self) -> Self:
        if self.mode == "apply" and self.expected_precondition_token is None:
            raise ValueError("Apply requires a dry-run precondition token")
        if self.mode == "dry-run" and self.expected_precondition_token is not None:
            raise ValueError("Dry-run does not accept a precondition token")
        return self


CutoverStoreName = Literal[
    "saved_graphs",
    "saved_graph_revisions",
    "collaborative_graph_heads",
    "templates",
    "graph_executions",
]


class CutoverUnknownNode(_CutoverValue):
    store: CutoverStoreName
    row_identity: str
    node_id: str
    operator_id: str
    operator_version: int


class CutoverStoreReport(_CutoverValue):
    store: CutoverStoreName
    scanned_rows: int = Field(ge=0)
    changed_rows: int = Field(ge=0)
    pinned_nodes: int = Field(ge=0)
    already_pinned_nodes: int = Field(ge=0)
    excluded_module_nodes: int = Field(ge=0)


class SystemCutoverReport(_CutoverValue):
    mode: Literal["dry-run", "apply"]
    applied: bool
    precondition_token: str = Field(pattern=r"^[0-9a-f]{64}$")
    rollback_unit_id: str
    stores: tuple[CutoverStoreReport, ...]
    unknown_nodes: tuple[CutoverUnknownNode, ...]
    invalidated_invocation_cache_entries: int = Field(ge=0)
    invalidated_materialized_node_outputs: int = Field(ge=0)
    legacy_provenance_marked: int = Field(ge=0)


class _AuditedDocument:
    def __init__(
        self,
        *,
        store: CutoverStoreName,
        table: Table,
        column_name: str,
        identity_conditions: tuple[ColumnElement[bool], ...],
        row_identity: str,
        workspace_id: UUID,
        graph_id: UUID | None,
        original: dict[str, object],
        rewritten: dict[str, object],
        pinned_nodes: int,
        already_pinned_nodes: int,
        excluded_module_nodes: int,
        unknown_nodes: tuple[CutoverUnknownNode, ...],
    ) -> None:
        self.store = store
        self.table = table
        self.column_name = column_name
        self.identity_conditions = identity_conditions
        self.row_identity = row_identity
        self.workspace_id = workspace_id
        self.graph_id = graph_id
        self.original = original
        self.rewritten = rewritten
        self.pinned_nodes = pinned_nodes
        self.already_pinned_nodes = already_pinned_nodes
        self.excluded_module_nodes = excluded_module_nodes
        self.unknown_nodes = unknown_nodes

    @property
    def changed(self) -> bool:
        return self.original != self.rewritten


class _AuditedProvenance:
    def __init__(
        self,
        *,
        table: Table,
        column_name: str,
        identity_conditions: tuple[ColumnElement[bool], ...],
        row_identity: str,
        original: dict[str, object],
        rewritten: dict[str, object],
    ) -> None:
        self.table = table
        self.column_name = column_name
        self.identity_conditions = identity_conditions
        self.row_identity = row_identity
        self.original = original
        self.rewritten = rewritten


class SystemBaselineCutoverService:
    """Audit and atomically backfill known unpinned System Plugin nodes."""

    _ACTIVE_EXECUTION_STATUSES = ("queued", "running", "cancelling")
    _CUTOVER_FENCE_TABLES: ClassVar[tuple[str, ...]] = (
        "plugin_releases",
        "plugin_release_selections",
        "plugin_release_revocations",
        "saved_graphs",
        "saved_graph_revisions",
        "collaborative_graph_heads",
        "templates",
        "graph_executions",
        "artifact_objects",
        "graph_execution_nodes",
        "invocation_cache_entries",
        "materialized_node_outputs",
    )

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def execute(self, command: SystemCutoverCommand) -> SystemCutoverReport:
        async with self._sessions() as session:
            async with session.begin():
                if command.mode == "apply":
                    await self._acquire_apply_maintenance_fence(session)
                return await self._run_cutover(command, session)

    async def _acquire_apply_maintenance_fence(
        self,
        session: AsyncSession,
    ) -> None:
        """Fence every cutover-scanned or mutated table before the first audit read.

        The fence must be the first operation of the apply transaction:
        PostgreSQL acquires ``SHARE ROW EXCLUSIVE`` table locks, which conflict
        with every data-changing statement, while SQLite reserves the database
        write lock with ``BEGIN IMMEDIATE`` before any other statement runs.
        Any other dialect fails closed instead of pretending to be safe.
        """
        dialect_name = session.get_bind().dialect.name
        if dialect_name == "postgresql":
            for table_name in self._CUTOVER_FENCE_TABLES:
                await session.execute(
                    text(f"LOCK TABLE {table_name} IN SHARE ROW EXCLUSIVE MODE")
                )
        elif dialect_name == "sqlite":
            await session.execute(text("BEGIN IMMEDIATE"))
        else:
            raise SystemCutoverError(
                f"System cutover apply requires an explicit maintenance fence; "
                f"database dialect {dialect_name!r} is unsupported"
            )

    async def _run_cutover(
        self,
        command: SystemCutoverCommand,
        session: AsyncSession,
    ) -> SystemCutoverReport:
        await self._refuse_active_executions(session)
        operator_pins = await self._verify_baseline(
            session,
            command.baseline,
        )
        audited = await self._audit_documents(session, operator_pins)
        provenance = await self._audit_legacy_provenance(session)
        precondition_token = self._precondition_token(
            command.baseline,
            command.rollback_unit,
            audited,
            provenance,
        )
        if command.mode == "apply":
            if command.expected_precondition_token != precondition_token:
                raise SystemCutoverPreconditionError(
                    "System cutover state changed after dry-run; run the audit "
                    "again before applying"
                )
            cache_count, materialized_count = await self._apply(
                session,
                audited,
                provenance,
            )
        else:
            cache_count = 0
            materialized_count = 0

        reports: list[CutoverStoreReport] = []
        unknown_nodes: list[CutoverUnknownNode] = []
        for store in cast(
            tuple[CutoverStoreName, ...],
            (
                "saved_graphs",
                "saved_graph_revisions",
                "collaborative_graph_heads",
                "templates",
                "graph_executions",
            ),
        ):
            rows = [item for item in audited if item.store == store]
            reports.append(
                CutoverStoreReport(
                    store=store,
                    scanned_rows=len(rows),
                    changed_rows=sum(item.changed for item in rows),
                    pinned_nodes=sum(item.pinned_nodes for item in rows),
                    already_pinned_nodes=sum(
                        item.already_pinned_nodes for item in rows
                    ),
                    excluded_module_nodes=sum(
                        item.excluded_module_nodes for item in rows
                    ),
                )
            )
            for item in rows:
                unknown_nodes.extend(item.unknown_nodes)

        return SystemCutoverReport(
            mode=command.mode,
            applied=command.mode == "apply",
            precondition_token=precondition_token,
            rollback_unit_id=command.rollback_unit.rollback_unit_id,
            stores=tuple(reports),
            unknown_nodes=tuple(unknown_nodes),
            invalidated_invocation_cache_entries=cache_count,
            invalidated_materialized_node_outputs=materialized_count,
            legacy_provenance_marked=(
                len(provenance) if command.mode == "apply" else 0
            ),
        )

    async def _refuse_active_executions(self, session: AsyncSession) -> None:
        identities = (
            await session.execute(
                select(
                    schema.graph_executions.c.execution_id,
                    schema.graph_executions.c.status,
                ).where(
                    schema.graph_executions.c.status.in_(
                        self._ACTIVE_EXECUTION_STATUSES
                    )
                )
            )
        ).all()
        if identities:
            rendered = ", ".join(
                f"{execution_id}:{status}" for execution_id, status in identities
            )
            raise SystemCutoverBlockedError(
                "System cutover requires a drained execution queue; active "
                f"executions: {rendered}"
            )

    async def _verify_baseline(
        self,
        session: AsyncSession,
        baseline: SystemBaselineManifest,
    ) -> dict[tuple[str, int], dict[str, object]]:
        selections = (
            await session.execute(
                select(
                    schema.plugin_release_selections.c.slug,
                    schema.plugin_release_selections.c.selected_release_id,
                    schema.plugin_release_selections.c.selected_revision,
                    schema.plugin_release_selections.c.generation,
                ).where(
                    schema.plugin_release_selections.c.scope
                    == PluginReleaseScope.SYSTEM,
                    schema.plugin_release_selections.c.lifecycle != "withdrawn",
                )
            )
        ).all()
        selected_by_slug = {row.slug: row for row in selections}
        baseline_by_slug = {release.slug: release for release in baseline.releases}
        if set(selected_by_slug) != set(baseline_by_slug):
            missing = sorted(set(selected_by_slug) - set(baseline_by_slug))
            unexpected = sorted(set(baseline_by_slug) - set(selected_by_slug))
            raise SystemCutoverError(
                "System baseline does not exactly cover enabled selections; "
                f"missing={missing}, unexpected={unexpected}"
            )

        pins: dict[tuple[str, int], dict[str, object]] = {}
        for declared in baseline.releases:
            selection = selected_by_slug[declared.slug]
            if (
                selection.selected_release_id != declared.release_id
                or selection.selected_revision != declared.revision
                or selection.generation != declared.selection_generation
            ):
                raise SystemCutoverError(
                    f"System baseline selection for {declared.slug!r} does not "
                    "match the database"
                )
            row = (
                (
                    await session.execute(
                        select(
                            schema.plugin_releases,
                            schema.plugin_installations.c.id.label(
                                "installation_id"
                            ),
                        )
                        .join(
                            schema.plugin_installations,
                            schema.plugin_installations.c.release_id
                            == schema.plugin_releases.c.id,
                        )
                        .where(
                            schema.plugin_releases.c.id == declared.release_id,
                            schema.plugin_installations.c.scope
                            == PluginReleaseScope.SYSTEM,
                            schema.plugin_installations.c.workspace_id.is_(None),
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise SystemCutoverError(
                    f"System baseline release {declared.release_id} is missing"
                )
            revoked = await session.scalar(
                select(schema.plugin_release_revocations.c.installation_id).where(
                    schema.plugin_release_revocations.c.installation_id
                    == row["installation_id"]
                )
            )
            if revoked is not None:
                raise SystemCutoverError(
                    f"System baseline release {declared.release_id} is revoked"
                )
            runtime_artifact = row["runtime_artifact"]
            actual = {
                "slug": row["slug"],
                "revision": row["revision"],
                "source_digest": row["source_digest"],
                "lock_digest": row["lock_digest"],
                "descriptor_digest": row["descriptor_digest"],
                "contract_digest": row["contract_digest"],
                "capability_digest": row["capability_digest"],
                "protocol_digest": row["protocol_digest"],
                "profile_digest": row["profile_digest"],
                "runtime_image_digest": row["runtime_image_digest"],
                "runtime_archive_digest": (
                    None
                    if runtime_artifact is None
                    else runtime_artifact.archive_digest
                ),
            }
            expected = declared.model_dump(
                include=set(actual),
                mode="python",
            )
            if actual != expected:
                mismatches = sorted(
                    key for key in actual if actual[key] != expected[key]
                )
                raise SystemCutoverError(
                    f"System baseline release {declared.slug!r} digest/identity "
                    f"mismatch: {mismatches}"
                )
            catalog = cast(PluginCatalogManifest, row["catalog"])
            self._verify_catalog_mappings(declared, catalog)
            pin: dict[str, object] = {
                "scope": PluginReleaseScope.SYSTEM.value,
                "slug": declared.slug,
                "revision": declared.revision,
            }
            for operator in declared.operators:
                key = (operator.operator_id, operator.operator_version)
                if key in pins:
                    raise SystemCutoverError(
                        f"Ambiguous System baseline operator {key[0]}@{key[1]}"
                    )
                pins[key] = pin
        return pins

    def _verify_catalog_mappings(
        self,
        declared: SystemBaselineRelease,
        catalog: PluginCatalogManifest,
    ) -> None:
        actual_operators = {
            (node.operator_id, node.operator_version) for node in catalog.nodes
        }
        expected_operators = {
            (node.operator_id, node.operator_version) for node in declared.operators
        }
        actual_artifacts = {
            (artifact.key.id, artifact.key.schema_version)
            for artifact in catalog.artifact_types
        }
        expected_artifacts = {
            (artifact.artifact_type_id, artifact.schema_version)
            for artifact in declared.artifact_types
        }
        if (
            actual_operators != expected_operators
            or actual_artifacts != expected_artifacts
        ):
            raise SystemCutoverError(
                f"System baseline mappings for {declared.slug!r} do not exactly "
                "match its retained catalog"
            )

    async def _audit_documents(
        self,
        session: AsyncSession,
        operator_pins: Mapping[tuple[str, int], dict[str, object]],
    ) -> list[_AuditedDocument]:
        audited: list[_AuditedDocument] = []
        definitions = (
            (
                cast(CutoverStoreName, "saved_graphs"),
                schema.saved_graphs,
                "document",
                ("id",),
                "workspace_id",
                "id",
            ),
            (
                cast(CutoverStoreName, "saved_graph_revisions"),
                schema.saved_graph_revisions,
                "document",
                ("workspace_id", "graph_id", "revision"),
                "workspace_id",
                "graph_id",
            ),
            (
                cast(CutoverStoreName, "collaborative_graph_heads"),
                schema.collaborative_graph_heads,
                "document",
                ("workspace_id", "graph_id"),
                "workspace_id",
                "graph_id",
            ),
            (
                cast(CutoverStoreName, "templates"),
                schema.templates,
                "snapshot_document",
                ("id",),
                "workspace_id",
                "source_graph_id",
            ),
            (
                cast(CutoverStoreName, "graph_executions"),
                schema.graph_executions,
                "submitted_request",
                ("execution_id",),
                "workspace_id",
                "graph_id",
            ),
        )
        for (
            store,
            table,
            column_name,
            primary_keys,
            workspace_key,
            graph_key,
        ) in definitions:
            typed_store = cast(CutoverStoreName, store)
            payload = type_coerce(table.c[column_name], JSON).label("payload")
            rows = (
                await session.execute(
                    select(
                        *(table.c[key] for key in primary_keys),
                        table.c[workspace_key],
                        table.c[graph_key],
                        payload,
                    )
                )
            ).mappings()
            for row in rows:
                value = row["payload"]
                if value is None:
                    continue
                if not isinstance(value, dict):
                    raise SystemCutoverError(
                        f"Cannot audit {store}: document root is not an object"
                    )
                original = cast(dict[str, object], value)
                identity = "/".join(str(row[key]) for key in primary_keys)
                rewritten, pinned, already, excluded, unknown = self._rewrite_nodes(
                    typed_store,
                    identity,
                    original,
                    operator_pins,
                    pin_field=(
                        "plugin_release"
                        if store == "graph_executions"
                        else "plugin_release_pin"
                    ),
                )
                audited.append(
                    _AuditedDocument(
                        store=typed_store,
                        table=table,
                        column_name=column_name,
                        identity_conditions=tuple(
                            table.c[key] == row[key] for key in primary_keys
                        ),
                        row_identity=identity,
                        workspace_id=cast(UUID, row[workspace_key]),
                        graph_id=cast(UUID | None, row[graph_key]),
                        original=original,
                        rewritten=rewritten,
                        pinned_nodes=pinned,
                        already_pinned_nodes=already,
                        excluded_module_nodes=excluded,
                        unknown_nodes=unknown,
                    )
                )
        return audited

    def _rewrite_nodes(
        self,
        store: CutoverStoreName,
        row_identity: str,
        document: dict[str, object],
        operator_pins: Mapping[tuple[str, int], dict[str, object]],
        *,
        pin_field: Literal["plugin_release", "plugin_release_pin"],
    ) -> tuple[
        dict[str, object],
        int,
        int,
        int,
        tuple[CutoverUnknownNode, ...],
    ]:
        raw_nodes = document.get("nodes")
        if not isinstance(raw_nodes, list):
            raise SystemCutoverError(
                f"Cannot audit {store} row {row_identity}: nodes is not an array"
            )
        rewritten_nodes: list[object] = []
        pinned = 0
        already = 0
        excluded = 0
        unknown: list[CutoverUnknownNode] = []
        for raw_node in cast(list[object], raw_nodes):
            if not isinstance(raw_node, dict):
                raise SystemCutoverError(
                    f"Cannot audit {store} row {row_identity}: node is not an object"
                )
            node = cast(dict[str, object], raw_node)
            operator_id = node.get("operator_id")
            operator_version = node.get("operator_version")
            node_id = node.get("id")
            if (
                not isinstance(operator_id, str)
                or not isinstance(operator_version, int)
                or isinstance(operator_version, bool)
                or not isinstance(node_id, str)
            ):
                raise SystemCutoverError(
                    f"Cannot audit {store} row {row_identity}: malformed node identity"
                )
            if pin_field in node and node[pin_field] is not None:
                already += 1
                rewritten_nodes.append(node)
                continue
            if operator_id in {
                "module.input",
                "module.output",
            } or operator_id.startswith("graph.module."):
                excluded += 1
                rewritten_nodes.append(node)
                continue
            pin = operator_pins.get((operator_id, operator_version))
            if pin is None:
                unknown.append(
                    CutoverUnknownNode(
                        store=store,
                        row_identity=row_identity,
                        node_id=node_id,
                        operator_id=operator_id,
                        operator_version=operator_version,
                    )
                )
                rewritten_nodes.append(node)
                continue
            rewritten_node = dict(node)
            rewritten_node[pin_field] = dict(pin)
            rewritten_nodes.append(rewritten_node)
            pinned += 1
        rewritten = dict(document)
        rewritten["nodes"] = rewritten_nodes
        return rewritten, pinned, already, excluded, tuple(unknown)

    async def _audit_legacy_provenance(
        self,
        session: AsyncSession,
    ) -> list[_AuditedProvenance]:
        audited: list[_AuditedProvenance] = []
        for table, column_name, primary_keys in (
            (schema.artifact_objects, "metadata", ("id",)),
            (
                schema.graph_execution_nodes,
                "diagnostics",
                ("workspace_id", "execution_id", "node_id"),
            ),
        ):
            payload = type_coerce(table.c[column_name], JSON).label("payload")
            rows = (
                await session.execute(
                    select(*(table.c[key] for key in primary_keys), payload)
                )
            ).mappings()
            for row in rows:
                value = row["payload"]
                if not isinstance(value, dict):
                    continue
                document = cast(dict[str, object], value)
                release = document.get("plugin_release")
                if not isinstance(release, dict):
                    continue
                release_mapping = cast(dict[str, object], release)
                if release_mapping.get("scope") != PluginReleaseScope.SYSTEM.value:
                    continue
                exact_fields = {
                    "slug",
                    "revision",
                    "source_digest",
                    "contract_digest",
                    "protocol_digest",
                    "descriptor_digest",
                }
                if exact_fields.issubset(release_mapping):
                    continue
                rewritten = dict(document)
                rewritten["plugin_release"] = {
                    "status": "legacy_unpinned",
                    "recorded": release_mapping,
                }
                audited.append(
                    _AuditedProvenance(
                        table=table,
                        column_name=column_name,
                        identity_conditions=tuple(
                            table.c[key] == row[key] for key in primary_keys
                        ),
                        row_identity="/".join(str(row[key]) for key in primary_keys),
                        original=document,
                        rewritten=rewritten,
                    )
                )
        return audited

    def _precondition_token(
        self,
        baseline: SystemBaselineManifest,
        rollback_unit: CutoverRollbackUnit,
        audited: Sequence[_AuditedDocument],
        provenance: Sequence[_AuditedProvenance],
    ) -> str:
        rows = [
            {
                "store": item.store,
                "identity": item.row_identity,
                "document": item.original,
            }
            for item in audited
        ]
        document = {
            "baseline": baseline.model_dump(mode="json"),
            "rollback_unit": rollback_unit.model_dump(mode="json"),
            "rows": sorted(rows, key=lambda item: (item["store"], item["identity"])),
            "legacy_provenance": sorted(
                (
                    {
                        "table": item.table.name,
                        "column": item.column_name,
                        "identity": item.row_identity,
                        "document": item.original,
                    }
                    for item in provenance
                ),
                key=lambda item: (
                    item["table"],
                    item["column"],
                    item["identity"],
                ),
            ),
        }
        encoded = json.dumps(
            document,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return sha256(encoded).hexdigest()

    async def _apply(
        self,
        session: AsyncSession,
        audited: Sequence[_AuditedDocument],
        provenance: Sequence[_AuditedProvenance],
    ) -> tuple[int, int]:
        affected_workspaces: set[UUID] = set()
        affected_graphs: set[tuple[UUID, UUID]] = set()
        for item in audited:
            if not item.changed:
                continue
            await self._cas_swap_payload(
                session,
                table=item.table,
                column_name=item.column_name,
                identity_conditions=item.identity_conditions,
                row_identity=item.row_identity,
                store=item.store,
                original=item.original,
                rewritten=item.rewritten,
            )
            affected_workspaces.add(item.workspace_id)
            if item.graph_id is not None:
                affected_graphs.add((item.workspace_id, item.graph_id))
        for item in provenance:
            await self._cas_swap_payload(
                session,
                table=item.table,
                column_name=item.column_name,
                identity_conditions=item.identity_conditions,
                row_identity=item.row_identity,
                store=item.table.name,
                original=item.original,
                rewritten=item.rewritten,
            )

        cache_count = 0
        if affected_workspaces:
            result = cast(
                CursorResult[tuple[object, ...]],
                await session.execute(
                    delete(schema.invocation_cache_entries).where(
                        schema.invocation_cache_entries.c.workspace_id.in_(
                            affected_workspaces
                        )
                    ),
                ),
            )
            cache_count = max(0, result.rowcount)
        materialized_count = 0
        for workspace_id, graph_id in affected_graphs:
            result = cast(
                CursorResult[tuple[object, ...]],
                await session.execute(
                    delete(schema.materialized_node_outputs).where(
                        schema.materialized_node_outputs.c.workspace_id == workspace_id,
                        schema.materialized_node_outputs.c.graph_id == graph_id,
                    ),
                ),
            )
            materialized_count += max(0, result.rowcount)
        return cache_count, materialized_count

    async def _cas_swap_payload(
        self,
        session: AsyncSession,
        *,
        table: Table,
        column_name: str,
        identity_conditions: tuple[ColumnElement[bool], ...],
        row_identity: str,
        store: str,
        original: dict[str, object],
        rewritten: dict[str, object],
    ) -> None:
        """Swap one audited payload only while it still equals the audited original.

        The locked re-read comparison is authoritative: JSON representation
        differences cannot weaken it. The payload equality predicate in the
        update and the exact row count keep the swap atomic even if the
        dialect's column equality is only textual.
        """
        payload = type_coerce(table.c[column_name], JSON)
        current = (
            await session.execute(select(payload).where(*identity_conditions))
        ).scalar_one_or_none()
        if current is None or current != original:
            raise SystemCutoverPreconditionError(
                f"System cutover {store} row {row_identity} changed after audit"
            )
        result = cast(
            CursorResult[tuple[object, ...]],
            await session.execute(
                update(table)
                .where(
                    *identity_conditions,
                    payload == literal(original, type_=JSON),
                )
                .values({column_name: literal(rewritten, type_=JSON)})
            ),
        )
        if result.rowcount != 1:
            raise SystemCutoverPreconditionError(
                f"System cutover {store} row {row_identity} changed after audit"
            )


__all__ = [
    "CutoverRollbackUnit",
    "CutoverStoreReport",
    "CutoverUnknownNode",
    "SystemBaselineArtifactType",
    "SystemBaselineCutoverService",
    "SystemBaselineManifest",
    "SystemBaselineOperator",
    "SystemBaselineRelease",
    "SystemCutoverBlockedError",
    "SystemCutoverCommand",
    "SystemCutoverError",
    "SystemCutoverPreconditionError",
    "SystemCutoverReport",
]
