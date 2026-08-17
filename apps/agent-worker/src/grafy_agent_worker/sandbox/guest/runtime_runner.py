"""Load generated node.py and emit bounded JSON outputs on stdout."""

from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import inspect
import json
import pathlib
import resource
import sys


def main() -> None:
    input_limit = int(sys.argv[1])
    output_limit = int(sys.argv[2])
    task_limit = int(sys.argv[3])
    resource.setrlimit(resource.RLIMIT_NPROC, (task_limit, task_limit))
    resource.setrlimit(resource.RLIMIT_FSIZE, (output_limit, output_limit))
    raw = sys.stdin.buffer.read(input_limit + 1)
    if len(raw) > input_limit:
        raise RuntimeError("generated-node input exceeds its limit")
    inputs = json.loads(raw)
    source = pathlib.Path("src/node.py").resolve()
    spec = importlib.util.spec_from_file_location("grafy_generated_node", source)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load generated node")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    run = getattr(module, "run", None)
    if not callable(run):
        raise RuntimeError("generated node must export callable run(inputs)")
    with contextlib.redirect_stdout(sys.stderr):
        result: object = run(inputs)
    if inspect.iscoroutine(result):
        with contextlib.redirect_stdout(sys.stderr):
            result = asyncio.run(result)
    encoded = json.dumps(
        result,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    if len(encoded) > output_limit:
        raise RuntimeError("generated-node output exceeds its limit")
    sys.stdout.buffer.write(encoded)


if __name__ == "__main__":
    main()
