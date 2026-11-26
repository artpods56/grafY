"""End-to-end tests for MCP canvas, project, checkpoint, and tool metadata."""

from pathlib import Path
from typing import Any, cast


from tests.integration.mcp.support import Stage, stage_for


def _build_counting_graph(stage: Stage, token: str) -> tuple[str, str]:
    project = cast(
        dict[str, Any], stage.ok("create_project", {"name": "Canvas"}, token=token)
    )
    project_id = str(project["id"])
    _ = stage.ok(
        "add_nodes",
        {
            "project_id": project_id,
            "graph_id": "main",
            "nodes": [
                {"id": "two", "operator_id": "value.integer", "config": {"value": 2}},
                {"id": "three", "operator_id": "value.integer", "config": {"value": 3}},
                {"id": "collect", "operator_id": "sequence.collect"},
                {"id": "count", "operator_id": "sequence.count"},
            ],
        },
        token=token,
    )
    for src, dst in (
        (("two", "value"), ("collect", "items")),
        (("three", "value"), ("collect", "items")),
        (("collect", "items"), ("count", "items")),
    ):
        _ = stage.ok(
            "connect",
            {
                "project_id": project_id,
                "graph_id": "main",
                "source": {"node": src[0], "port": src[1]},
                "target": {"node": dst[0], "port": dst[1]},
            },
            token=token,
        )
    card = cast(
        dict[str, Any],
        stage.ok(
            "add_card",
            {
                "project_id": project_id,
                "graph_id": "main",
                "follows": {"node": "count", "port": "count"},
            },
            token=token,
        ),
    )
    return project_id, str(card["card_id"])


def test_an_agent_builds_a_graph_gesture_by_gesture(tmp_path: Path) -> None:
    with stage_for(tmp_path, "mcp-canvas-build.sqlite3") as stage:
        token = stage.editor_token
        project_id, card_id = _build_counting_graph(stage, token)
        run = cast(
            dict[str, Any],
            stage.ok(
                "start_run",
                {"project_id": project_id, "graph_id": "main"},
                token=token,
            ),
        )
        finished = cast(
            dict[str, Any],
            stage.ok(
                "wait_for_run",
                {
                    "project_id": project_id,
                    "run_id": run["id"],
                    "timeout_seconds": 60,
                },
                token=token,
            ),
        )
        result = cast(
            dict[str, Any],
            stage.ok(
                "get_instance_result",
                {"project_id": project_id, "graph_id": "main", "node_id": "count"},
                token=token,
            ),
        )
        canvas = cast(
            dict[str, Any],
            stage.ok(
                "get_canvas",
                {"project_id": project_id, "graph_id": "main"},
                token=token,
            ),
        )

    assert finished["status"] == "succeeded", finished
    assert "count" in result["outputs"]
    nodes = cast(list[dict[str, Any]], canvas["nodes"])
    connections = cast(list[dict[str, Any]], canvas["connections"])
    cards = cast(list[dict[str, Any]], canvas["cards"])
    assert len(nodes) == 4
    assert len(connections) == 3
    for conn in connections:
        assert "." in conn["from"]
        assert "." in conn["to"]
    wired = {(conn["from"], str(conn["to"]).split("[")[0]) for conn in connections}
    assert wired == {
        ("two.value", "collect.items"),
        ("three.value", "collect.items"),
        ("collect.items", "count.items"),
    }
    assert len(cards) == 1
    assert cards[0]["id"] == card_id
    assert cards[0]["follows"] == "count.count"


def test_moving_and_resizing_send_the_workbench_commands(tmp_path: Path) -> None:
    with stage_for(tmp_path, "mcp-canvas-move-resize.sqlite3") as stage:
        token = stage.editor_token
        project_id, card_id = _build_counting_graph(stage, token)
        before = cast(
            dict[str, Any],
            stage.ok(
                "get_canvas",
                {"project_id": project_id, "graph_id": "main"},
                token=token,
            ),
        )
        before_card = next(
            c for c in cast(list[dict[str, Any]], before["cards"]) if c["id"] == card_id
        )
        moved = cast(
            dict[str, Any],
            stage.ok(
                "move_items",
                {
                    "project_id": project_id,
                    "graph_id": "main",
                    "moves": [
                        {"id": "two", "x": 10, "y": 20},
                        {"id": card_id, "dx": 5},
                    ],
                },
                token=token,
            ),
        )
        resized = cast(
            dict[str, Any],
            stage.ok(
                "resize_item",
                {
                    "project_id": project_id,
                    "graph_id": "main",
                    "id": "two",
                    "width": 400,
                },
                token=token,
            ),
        )
        after = cast(
            dict[str, Any],
            stage.ok(
                "get_canvas",
                {"project_id": project_id, "graph_id": "main"},
                token=token,
            ),
        )
        unknown = stage.tool(
            "move_items",
            {
                "project_id": project_id,
                "graph_id": "main",
                "moves": [{"id": "missing-item", "x": 0, "y": 0}],
            },
            token=token,
        )

    assert moved["commands"] == ["move_nodes", "move_artifact_viewers"]
    assert resized["commands"] == ["update_node_layout"]
    two = next(
        n for n in cast(list[dict[str, Any]], after["nodes"]) if n["id"] == "two"
    )
    after_card = next(
        c for c in cast(list[dict[str, Any]], after["cards"]) if c["id"] == card_id
    )
    assert two["x"] == 10
    assert two["y"] == 20
    assert two["layout"]["width"] == 400
    assert after_card["x"] == before_card["x"] + 5
    assert after_card["y"] == before_card["y"]
    assert unknown["isError"] is True


def test_configure_node_is_checked_against_the_schema(tmp_path: Path) -> None:
    with stage_for(tmp_path, "mcp-canvas-configure.sqlite3") as stage:
        token = stage.editor_token
        project_id, _ = _build_counting_graph(stage, token)
        configured = cast(
            dict[str, Any],
            stage.ok(
                "configure_node",
                {
                    "project_id": project_id,
                    "graph_id": "main",
                    "node_id": "two",
                    "config": {"value": 7},
                },
                token=token,
            ),
        )
        invalid = stage.tool(
            "configure_node",
            {
                "project_id": project_id,
                "graph_id": "main",
                "node_id": "two",
                "config": {"value": "seven"},
            },
            token=token,
        )
        canvas = cast(
            dict[str, Any],
            stage.ok(
                "get_canvas",
                {"project_id": project_id, "graph_id": "main"},
                token=token,
            ),
        )

    assert configured["commands"] == ["update_node_configuration"]
    assert invalid["isError"] is True
    two = next(
        n for n in cast(list[dict[str, Any]], canvas["nodes"]) if n["id"] == "two"
    )
    assert two["config"] == {"value": 7}


def test_connect_refuses_wiring_the_catalog_rejects(tmp_path: Path) -> None:
    with stage_for(tmp_path, "mcp-canvas-connect-refuse.sqlite3") as stage:
        token = stage.editor_token
        project_id, _ = _build_counting_graph(stage, token)
        before_head = cast(
            dict[str, Any],
            stage.ok(
                "get_project",
                {"project_id": project_id, "graph_id": "main"},
                token=token,
            ),
        )
        missing_port = stage.tool(
            "connect",
            {
                "project_id": project_id,
                "graph_id": "main",
                "source": {"node": "two", "port": "value"},
                "target": {"node": "count", "port": "does_not_exist"},
            },
            token=token,
        )
        second_wire = stage.tool(
            "connect",
            {
                "project_id": project_id,
                "graph_id": "main",
                "source": {"node": "collect", "port": "items"},
                "target": {"node": "count", "port": "items"},
            },
            token=token,
        )
        after_head = cast(
            dict[str, Any],
            stage.ok(
                "get_project",
                {"project_id": project_id, "graph_id": "main"},
                token=token,
            ),
        )

    assert missing_port["isError"] is True
    assert second_wire["isError"] is True
    assert after_head["collaboration_sequence"] == before_head["collaboration_sequence"]


def test_annotations_and_removal(tmp_path: Path) -> None:
    with stage_for(tmp_path, "mcp-canvas-annotations.sqlite3") as stage:
        token = stage.editor_token
        project_id, _ = _build_counting_graph(stage, token)
        added = cast(
            dict[str, Any],
            stage.ok(
                "add_annotation",
                {"project_id": project_id, "graph_id": "main", "text": "Inputs"},
                token=token,
            ),
        )
        annotation_id = str(added["annotation_id"])
        _ = stage.ok(
            "edit_annotation",
            {
                "project_id": project_id,
                "graph_id": "main",
                "annotation_id": annotation_id,
                "text": "Sources",
            },
            token=token,
        )
        _ = stage.ok(
            "remove_items",
            {"project_id": project_id, "graph_id": "main", "ids": ["three"]},
            token=token,
        )
        canvas = cast(
            dict[str, Any],
            stage.ok(
                "get_canvas",
                {"project_id": project_id, "graph_id": "main"},
                token=token,
            ),
        )
        unknown = stage.tool(
            "remove_items",
            {"project_id": project_id, "graph_id": "main", "ids": ["does-not-exist"]},
            token=token,
        )

    annotations = cast(list[dict[str, Any]], canvas["annotations"])
    nodes = cast(list[dict[str, Any]], canvas["nodes"])
    connections = cast(list[dict[str, Any]], canvas["connections"])
    assert [ann["id"] for ann in annotations] == [annotation_id]
    assert annotations[0]["text"] == "Sources"
    assert "three" not in [node["id"] for node in nodes]
    assert all(not str(conn["from"]).startswith("three.") for conn in connections)
    assert len(connections) == 2
    assert unknown["isError"] is True


def test_arrange_graph_lays_nodes_out_by_data_flow(tmp_path: Path) -> None:
    with stage_for(tmp_path, "mcp-canvas-arrange.sqlite3") as stage:
        token = stage.editor_token
        project_id, _ = _build_counting_graph(stage, token)
        _ = stage.ok(
            "move_items",
            {
                "project_id": project_id,
                "graph_id": "main",
                "moves": [
                    {"id": node_id, "x": 100, "y": 100}
                    for node_id in ("two", "three", "collect", "count")
                ],
            },
            token=token,
        )
        arranged = cast(
            dict[str, Any],
            stage.ok(
                "arrange_graph",
                {"project_id": project_id, "graph_id": "main"},
                token=token,
            ),
        )
        canvas = cast(
            dict[str, Any],
            stage.ok(
                "get_canvas",
                {"project_id": project_id, "graph_id": "main"},
                token=token,
            ),
        )

    assert arranged["changed"] is True
    xs = {
        str(node["id"]): float(node["x"])
        for node in cast(list[dict[str, Any]], canvas["nodes"])
    }
    assert xs["two"] == xs["three"] < xs["collect"] < xs["count"]


def test_restore_checkpoint_undoes_an_edit(tmp_path: Path) -> None:
    with stage_for(tmp_path, "mcp-canvas-checkpoint.sqlite3") as stage:
        token = stage.editor_token
        project_id, _ = _build_counting_graph(stage, token)
        checkpoint = cast(
            dict[str, Any],
            stage.ok("checkpoint_project", {"project_id": project_id}, token=token),
        )
        revision = int(checkpoint["checkpoint_revision"])
        _ = stage.ok(
            "remove_items",
            {"project_id": project_id, "graph_id": "main", "ids": ["count"]},
            token=token,
        )
        removed_canvas = cast(
            dict[str, Any],
            stage.ok(
                "get_canvas",
                {"project_id": project_id, "graph_id": "main"},
                token=token,
            ),
        )
        checkpoints = cast(
            list[dict[str, Any]],
            stage.ok("list_checkpoints", {"project_id": project_id}, token=token),
        )
        restored = cast(
            dict[str, Any],
            stage.ok(
                "restore_checkpoint",
                {"project_id": project_id, "revision": revision},
                token=token,
            ),
        )
        restored_canvas = cast(
            dict[str, Any],
            stage.ok(
                "get_canvas",
                {"project_id": project_id, "graph_id": "main"},
                token=token,
            ),
        )

    assert checkpoint["new"] is True
    assert "count" not in [
        node["id"] for node in cast(list[dict[str, Any]], removed_canvas["nodes"])
    ]
    assert any(item["revision"] == revision for item in checkpoints)
    # The removal was checkpointed before the restore, so it can be redone.
    assert restored["saved_edits_as_revision"] == revision + 1
    assert "count" in [
        node["id"] for node in cast(list[dict[str, Any]], restored_canvas["nodes"])
    ]


def test_projects_can_be_filed_starred_archived_and_copied(tmp_path: Path) -> None:
    with stage_for(tmp_path, "mcp-projects-lifecycle.sqlite3") as stage:
        token = stage.editor_token
        project = cast(
            dict[str, Any],
            stage.ok("create_project", {"name": "Alpha"}, token=token),
        )
        folder = cast(
            dict[str, Any],
            stage.ok("create_project_folder", {"name": "Fieldwork"}, token=token),
        )
        filed = cast(
            dict[str, Any],
            stage.ok(
                "file_project",
                {"project_id": project["id"], "folder_id": folder["id"]},
                token=token,
            ),
        )
        starred = cast(
            dict[str, Any],
            stage.ok("star_project", {"project_id": project["id"]}, token=token),
        )
        archived = cast(
            dict[str, Any],
            stage.ok("archive_project", {"project_id": project["id"]}, token=token),
        )
        unarchived = cast(
            dict[str, Any],
            stage.ok("unarchive_project", {"project_id": project["id"]}, token=token),
        )
        copied = cast(
            dict[str, Any],
            stage.ok(
                "copy_project",
                {"project_id": project["id"], "name": "Alpha Copy"},
                token=token,
            ),
        )
        listed_both = cast(
            list[dict[str, Any]], stage.ok("list_projects", {}, token=token)
        )
        _ = stage.ok(
            "rename_project",
            {"project_id": project["id"], "name": "Beta"},
            token=token,
        )
        listed_renamed = cast(
            list[dict[str, Any]], stage.ok("list_projects", {}, token=token)
        )

    assert filed["folder_id"] == folder["id"]
    assert starred["starred"] is True
    assert archived["archived_at"] is not None
    assert unarchived["archived_at"] is None
    assert copied["id"] != project["id"]
    assert {item["id"] for item in listed_both} == {project["id"], copied["id"]}
    renamed_entry = next(item for item in listed_renamed if item["id"] == project["id"])
    assert renamed_entry["name"] == "Beta"


def test_reader_token_cannot_edit_the_canvas(tmp_path: Path) -> None:
    with stage_for(tmp_path, "mcp-canvas-reader.sqlite3") as stage:
        project_id, _ = _build_counting_graph(stage, stage.editor_token)
        refused = stage.tool(
            "move_items",
            {
                "project_id": project_id,
                "graph_id": "main",
                "moves": [{"id": "two", "x": 10, "y": 20}],
            },
            token=stage.reader_token,
        )
        canvas = cast(
            dict[str, Any],
            stage.ok(
                "get_canvas",
                {"project_id": project_id, "graph_id": "main"},
                token=stage.reader_token,
            ),
        )

    assert refused["isError"] is True
    assert "403" in refused["content"][0]["text"], refused
    assert len(cast(list[dict[str, Any]], canvas["nodes"])) == 4


def test_tools_list_carries_annotations(tmp_path: Path) -> None:
    with stage_for(tmp_path, "mcp-tools-annotations.sqlite3") as stage:
        response = stage.rpc("tools/list", {}, token=stage.editor_token)

    assert response.status_code == 200, response.text
    tools = {
        tool["name"]: tool
        for tool in cast(list[dict[str, Any]], response.json()["result"]["tools"])
    }
    assert tools["get_canvas"]["annotations"]["readOnlyHint"] is True
    assert tools["remove_items"]["annotations"]["destructiveHint"] is True
