"""Report retired builtin nodes in exported SavedGraphDocument JSON files."""

import argparse
from pathlib import Path
from typing import Literal

from grafy_core.domain.saved_graphs import SavedGraphDocument
from pydantic import BaseModel


class BuiltinCleanupFinding(BaseModel):
    document: Path
    node_id: str
    operator_id: str
    action: Literal[
        "replace_with_plugin",
        "remove",
        "manually_rebuild_or_remove",
    ]
    incoming_edges: int
    outgoing_edges: int


class BuiltinCleanupAudit(BaseModel):
    findings: list[BuiltinCleanupFinding]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument("documents", type=Path, nargs="+")
    args = parser.parse_args()
    findings: list[BuiltinCleanupFinding] = []
    for path in args.documents:
        document = SavedGraphDocument.model_validate_json(path.read_text())
        for node in document.nodes:
            if node.kind != "builtin":
                continue
            if node.operator_id in {"image.decode", "table.import"}:
                action = "replace_with_plugin"
            elif node.operator_id in {
                "text.as_markdown",
                "text.split",
                "text.replace",
                "text.join",
            }:
                action = "manually_rebuild_or_remove"
            elif node.operator_id in {
                "table.text.normalize",
                "table.fuzzy_match",
            }:
                action = "remove"
            else:
                continue
            findings.append(
                BuiltinCleanupFinding(
                    document=path,
                    node_id=node.id,
                    operator_id=node.operator_id,
                    action=action,
                    incoming_edges=sum(edge.to_node == node.id for edge in document.edges),
                    outgoing_edges=sum(edge.from_node == node.id for edge in document.edges),
                )
            )
    print(BuiltinCleanupAudit(findings=findings).model_dump_json(indent=2))
