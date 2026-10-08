# Build and run a graph with Python

> Historical example. The upload and sequence operators shown below are retired.
> Use Library uploads, artifact-card Collect, and the published Image Plugin.
> See [the builtin cleanup migration](how-to-deploy-builtin-cleanup.md).

Use `grafy-client` to build a typed graph, save it through the HTTP API, and
wait for its execution. The client uses the public API only.

## Prepare access

In Workspace Settings, create a PAT with the **Graph automation** purpose. It
contains these scopes:

- `view_graph`
- `view_artifacts`
- `view_materializations`
- `view_history`
- `view_execution`
- `create_graph`
- `edit_graph`
- `checkpoint_graph`
- `execute_graph`
- `cancel_execution`
- `manage_secrets`

Set the API URL and workspace ID. Store the PAT and provider key in protected
files that are readable only by your user and are excluded from source control:

```bash
export GRAFY_API_URL=http://localhost:8000
export GRAFY_WORKSPACE_ID=34463782-60c4-4094-b106-d0201e0614e0
export GRAFY_TOKEN_FILE=/secure/path/grafy-token
export GRAFY_PROVIDER_SECRET_FILE=/secure/path/provider-api-key
chmod 600 "$GRAFY_TOKEN_FILE" "$GRAFY_PROVIDER_SECRET_FILE"
```

Install the workspace with the optional LLM plugin:

```bash
uv sync --all-extras
```

The deployment must also assign `external.llm` an execution network profile.
Use `configured-public` for a public HTTPS provider, or an exact `curated`
profile with deployment-owned CA trust for a private RFC1918 provider. The
node's `base_url` selects a destination inside that deployment ceiling; it does
not grant network access by itself.

## Build and execute the graph

Save this example as `vision_graph.py`. Replace `image.png`, the provider URL,
and the model with values for your environment.

```python
import asyncio
import os
from pathlib import Path
from uuid import UUID

from pydantic import SecretStr

from grafy_client import GrafyClient, GraphBuilder
from grafy_core.artifacts import NoConfig
from grafy_workbench.image.nodes import (
    ImageUploadConfig,
    ImageUploadItem,
    UploadImagesNode,
)
from grafy_plugin_llm.openai_compatible import (
    OpenAICompatibleConfig,
    OpenAICompatibleNode,
)
from grafy_plugin_llm.prompt import (
    CreatePromptMessageNode,
    PromptMessageConfig,
)
from grafy_workbench.sequence.nodes import CollectNode
from grafy_workbench.text.nodes import TextInputConfig, TextInputNode


async def main() -> None:
    workspace_id = UUID(os.environ["GRAFY_WORKSPACE_ID"])
    token = SecretStr(
        Path(os.environ["GRAFY_TOKEN_FILE"]).read_text().strip()
    )
    provider_key = SecretStr(
        Path(os.environ["GRAFY_PROVIDER_SECRET_FILE"]).read_text().strip()
    )

    async with GrafyClient(
        base_url=os.environ["GRAFY_API_URL"],
        token=token,
    ) as grafy:
        image_bytes = Path("image.png").read_bytes()
        upload = await grafy.uploads.create(
            workspace_id,
            filename="image.png",
            content=image_bytes,
            content_type="image/png",
        )

        catalog = await grafy.catalog.get(workspace_id)
        graph = GraphBuilder(catalog)

        image = graph.add(
            UploadImagesNode,
            ImageUploadConfig(
                uploads=[
                    ImageUploadItem(
                        upload_key=upload.upload_key,
                        filename=upload.filename,
                        byte_size=upload.byte_size,
                    )
                ]
            ),
        )
        text = graph.add(
            TextInputNode,
            TextInputConfig(text="Describe this image."),
        )
        prompt = graph.add(
            CreatePromptMessageNode,
            PromptMessageConfig(),
        )
        messages = graph.add(CollectNode, NoConfig())
        llm = graph.add(
            OpenAICompatibleNode,
            OpenAICompatibleConfig(
                base_url="https://provider.example/v1",
                model="vision-model",
            ),
        )

        graph.connect(text.output("text"), prompt.input("text"))
        graph.connect(image.output("images"), prompt.input("images"))
        graph.connect(prompt.output("message"), messages.input("items"))
        graph.connect(messages.output("items"), llm.input("messages"))

        saved = await grafy.graphs.create(
            workspace_id,
            name="Vision API example",
            document=graph.build(),
        )
        await grafy.graphs.configure_secret(
            workspace_id,
            saved.id,
            node_id=llm.node_id,
            secret_name="api_key",
            value=provider_key,
            expected_revision=saved.revision,
        )

        execution = await grafy.graphs.execute(
            workspace_id,
            saved.id,
            expected_revision=saved.revision,
            idempotency_key="vision-api-example-1",
        )
        terminal = await execution.wait(timeout=60)
        if terminal.status != "succeeded" or terminal.result is None:
            raise RuntimeError(terminal.error or "Graph execution failed")

        completion = terminal.result.node(llm.node_id).output("completion")
        assert completion.artifact_type == "llm.completion"
        assert completion.artifacts[0].schema_version == 1
        print(completion.artifact_id)


asyncio.run(main())
```

Run the example:

```bash
uv run python vision_graph.py
```

`GraphBuilder` matches each local Node class against the workspace catalog. It
stores the catalog's exact runnable plugin release pin on every saved node. The
result is a canonical `SavedGraphDocument`, so the web workbench can open and
edit the saved graph after the script creates it.

## Author installed nodes directly from the catalog

An automation client does not need the installed Plugin's Python package.
Address a node by its catalog operator ID and pass JSON-compatible
configuration. `GraphBuilder` validates the configuration against the catalog
JSON Schema and validates connections against the catalog ports.

```python
from grafy_client import GraphBuilder
from grafy_core.domain.saved_graphs import GraphPoint


catalog = await grafy.catalog.get(workspace_id)
graph = GraphBuilder(catalog)
extract = graph.add_catalog_node(
    "notarius.dataset.extract_structured",
    {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4.1-mini",
        "context_strategy": "sliding_window",
        "window_size": 5,
        "max_concurrent": 5,
        "lookahead_images": True,
        "temperature": 0,
        "max_completion_tokens": 8192,
        "timeout_ms": 120000,
        "max_retries": 0,
        "schema_name": "chwalewik_entry",
        "strict": True,
    },
    position=GraphPoint(x=720, y=120),
)
```

Omit `operator_version` only when the workspace catalog contains exactly one
matching operator. Pass `operator_version` and `plugin_slug` to disambiguate
multiple catalog entries.

## Revise a graph created by automation

Read the current revision before replacing a graph. The server rejects stale
updates and graphs with uncheckpointed collaborative changes.

```python
current = await grafy.graphs.get(workspace_id, graph_id)
updated = await grafy.graphs.update(
    workspace_id,
    graph_id,
    name=current.name,
    document=graph.build(),
    expected_revision=current.revision,
)
```
