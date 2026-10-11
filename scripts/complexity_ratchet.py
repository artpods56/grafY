"""Fail when changed Python files get more complex than on the base ref.

Measures Cognitive Complexity with `cccc` (https://github.com/moznion/cccc)
for every Python file changed since the base ref and rejects the change if:

- a file's total cognitive complexity grows;
- an existing function gets more complex;
- a new function exceeds the new-function limit;
- a new function takes too many parameters or a boolean flag parameter;
- a `--target` function is still above its limit.

Functions are matched by name, so renaming a function counts it as new.
"""

import argparse
import ast
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

NEW_FUNCTION_LIMIT = 15
MAX_NEW_PARAMETERS = 5


@dataclass(frozen=True)
class Target:
    path: str
    function: str
    limit: int


def parse_target(value: str) -> Target:
    try:
        location, limit = value.rsplit("<=", 1)
        path, function = location.split("::", 1)
        return Target(path=path, function=function, limit=int(limit))
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            f"expected PATH::FUNCTION<=N, got {value!r}"
        ) from error


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], check=True, capture_output=True, text=True
    ).stdout


def changed_python_files(base: str) -> list[str]:
    output = git("diff", "--name-only", "--diff-filter=AMR", base, "--", "*.py")
    return [
        path
        for path in output.splitlines()
        if Path(path).exists() and "/tests/" not in f"/{path}"
    ]


def base_source(base: str, path: str) -> str | None:
    result = subprocess.run(
        ["git", "show", f"{base}:{path}"], capture_output=True, text=True
    )
    return result.stdout if result.returncode == 0 else None


class CcccFunction(BaseModel):
    name: str
    cognitive: int
    children: list["CcccFunction"] = []


class CcccFile(BaseModel):
    cognitive: int
    functions: list[CcccFunction]


class CcccReport(BaseModel):
    files: list[CcccFile]


def flatten(functions: list[CcccFunction]) -> Iterator[CcccFunction]:
    for function in functions:
        yield function
        yield from flatten(function.children)


def measure(path: Path) -> tuple[int, dict[str, int]]:
    """Return the file's total cognitive score and the worst score per name."""
    output = subprocess.run(
        ["cccc", "--no-config", "--no-cache", "--lang", "python", str(path)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    files = CcccReport.model_validate_json(output).files
    if not files:
        return 0, {}
    scores: dict[str, int] = {}
    for function in flatten(files[0].functions):
        scores[function.name] = max(scores.get(function.name, 0), function.cognitive)
    return files[0].cognitive, scores


def measure_source(source: str) -> tuple[int, dict[str, int]]:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "base.py"
        path.write_text(source)
        return measure(path)


def signature_problems(path: str, new_names: set[str]) -> Iterator[str]:
    tree = ast.parse(Path(path).read_text())
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if node.name not in new_names:
            continue
        arguments = [
            *node.args.posonlyargs,
            *node.args.args,
            *node.args.kwonlyargs,
        ]
        parameters = [a for a in arguments if a.arg not in {"self", "cls"}]
        if len(parameters) > MAX_NEW_PARAMETERS:
            yield (
                f"{path}:{node.lineno} new function {node.name} takes "
                f"{len(parameters)} parameters (max {MAX_NEW_PARAMETERS})"
            )
        for argument in parameters:
            if isinstance(argument.annotation, ast.Name) and (
                argument.annotation.id == "bool"
            ):
                yield (
                    f"{path}:{node.lineno} new function {node.name} takes "
                    f"boolean flag parameter {argument.arg}"
                )


def file_problems(base: str, path: str) -> Iterator[str]:
    total, scores = measure(Path(path))
    source = base_source(base, path)
    base_total, base_scores = measure_source(source) if source else (0, {})

    if source is not None and total > base_total:
        yield f"{path} total cognitive grew {base_total} -> {total}"
    for name, score in sorted(scores.items()):
        if name in base_scores:
            if score > base_scores[name]:
                yield (f"{path} {name} cognitive grew {base_scores[name]} -> {score}")
        elif score > NEW_FUNCTION_LIMIT:
            yield (
                f"{path} new function {name} has cognitive {score} "
                f"(max {NEW_FUNCTION_LIMIT})"
            )
    yield from signature_problems(path, set(scores) - set(base_scores))


def target_problems(target: Target) -> Iterator[str]:
    _, scores = measure(Path(target.path))
    score = scores.get(target.function)
    if score is None:
        yield f"{target.path} has no function {target.function}"
    elif score > target.limit:
        yield (
            f"{target.path} {target.function} cognitive {score} "
            f"(target <= {target.limit})"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument(
        "--base",
        default="HEAD",
        help="git ref to compare with (default: the last commit)",
    )
    parser.add_argument(
        "--target",
        action="append",
        default=[],
        type=parse_target,
        help="require PATH::FUNCTION<=N; may be repeated",
    )
    args = parser.parse_args()

    base = git("merge-base", args.base, "HEAD").strip()
    paths = changed_python_files(base)
    problems = [
        *(problem for path in paths for problem in file_problems(base, path)),
        *(problem for target in args.target for problem in target_problems(target)),
    ]
    for problem in problems:
        print(f"FAIL {problem}")
    print(f"checked {len(paths)} changed file(s); {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
