import json
from pathlib import Path
import subprocess
import sys

from grafy_core.domain.saved_graphs import (
    GraphPoint,
    SavedGraphDocument,
    SavedGraphEdge,
    SavedGraphNode,
)


SCRIPT = Path(__file__).resolve().parents[3] / "scripts/audit_builtin_cleanup.py"


def test_cleanup_audit_reports_live_collect_dependencies_without_configuration(
    tmp_path: Path,
) -> None:
    path = tmp_path / "graph.json"
    document = SavedGraphDocument(
        nodes=(
            SavedGraphNode(
                id="input",
                kind="builtin",
                operator_id="text.input",
                operator_version=1,
                position=GraphPoint(x=0, y=0),
                config={"text": "do-not-print"},
            ),
            SavedGraphNode(
                id="collect",
                kind="builtin",
                operator_id="sequence.collect",
                operator_version=1,
                position=GraphPoint(x=0, y=0),
            ),
        ),
        edges=(
            SavedGraphEdge(
                id="edge",
                from_node="input",
                from_port="text",
                to_node="collect",
                to_port="items",
            ),
        ),
    )
    _ = path.write_text(document.model_dump_json())

    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(path)],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "do-not-print" not in result.stdout
    assert json.loads(result.stdout) == {
        "findings": [
            {
                "document": str(path),
                "node_id": "collect",
                "operator_id": "sequence.collect",
                "action": "rebuild_with_artifact_cards",
                "incoming_edges": 1,
                "outgoing_edges": 0,
            },
        ],
    }
