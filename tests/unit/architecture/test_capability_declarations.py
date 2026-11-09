"""Every capability a service layer asks for must be declared by the route above it.

Effective permission is role ∩ PAT scope ∩ capability, and it is only computable where the
credential is still whole. `workspace_actor` hands a route either an `ActorContext`
(browser session, where the role *is* the permission) or a `WorkspacePatPrincipal` whose
`capabilities` are the token's granted scopes, and `require_workspace_capability`
intersects the two
(`apps/api/src/grafy_api/v1/routes/auth/dependencies.py:153`). Below the route the token
disappears: `authorize_workspace` rebuilds a `WorkspaceAccess` from the stored membership
alone (`libs/core/src/grafy_core/application/identity.py:43`), so a service-layer
`access.require(capability)` re-checks the role against the role and never consults a
scope. A service capability is therefore a promise the route must keep, not an enforcement
point: ask for less at the route than the service asks for and the narrower check wins.

That is the W11 defect, and it is structural rather than local, so it is checked here
instead of in review. `POST /checkpoints/{revision}/restore` asked EDIT_PROJECT at the
route and CHECKPOINT_PROJECT in the service, and a token scoped
`[view_project, edit_project]` restored a checkpoint, wrote a revision and reset the room
epoch.

What the model covers, and what it admits it cannot see:

* A service requirement is a `WorkspaceCapability` member named at a call that performs a
  check (`authorize`, `_authorize`, `authorize_workspace`, `require`, `grants`) inside a
  method of an application service under `libs/core/src/grafy_core/application`.
* Only routes that can carry a token are constrained. A route with a
  `require_workspace_capability` parameter admits a PAT and must declare what its services
  ask; a route that resolves its actor through `browser_actor` or
  `websocket_browser_actor` has no scope to intersect, so the role check already is the
  effective permission and demanding a second declaration would be noise.
* Requirements reached only through service-to-service delegation are not followed, nor
  are service calls inside the Project room's frame handlers
  (`v1/routes/collaboration/views.py`), which dispatch on frame type from a session the
  room opened as a browser. Both are named here so nobody reads the green suite as proof
  about them.
"""

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
API_SOURCE_ROOT = REPO_ROOT / "apps/api/src"
ROUTES_ROOT = API_SOURCE_ROOT / "grafy_api/v1/routes"
APPLICATION_ROOT = REPO_ROOT / "libs/core/src/grafy_core/application"

CAPABILITY_LITERAL = re.compile(r"WorkspaceCapability\.([A-Z][A-Z_]*)\b")
CHECK_CALLS = frozenset(
    {"authorize", "_authorize", "authorize_workspace", "require", "grants"}
)
# Checks that bind a capability to a workspace named in a tuple of requirements, so no
# single-workspace route declaration can satisfy them. `copy_project` asks for
# `view_project` on `CopyExactHeadRequest.source_workspace_id`
# (`grafy_api/project_contracts.py:383`) and `create_project` on the path Workspace, and
# `require_workspace_capability` only ever binds the path `workspace_id`.
MULTI_WORKSPACE_CHECKS = frozenset({"_authorize_pair"})
KNOWN_MULTI_WORKSPACE_SITES = frozenset({"CollaborationService.copy_project"})
ROUTE_DECORATORS = frozenset(
    {"get", "post", "put", "delete", "patch", "websocket", "api_route"}
)
CAPABILITY_DEPENDENCY = "require_workspace_capability"
BROWSER_ACTOR_DEPENDENCIES = frozenset({"browser_actor", "websocket_browser_actor"})
# The edges that were wrong before W11 plus the room's, named so a resolver that quietly
# stops matching anything fails here rather than passing vacuously.
ANCHOR_EDGES = {
    "checkpoint_project": {"CollaborationService.checkpoint"},
    "create_project": {"CollaborationService.create_project"},
    "restore_project_checkpoint": {"CollaborationService.restore_checkpoint"},
    "join_project_room": {"CollaborationService.get_head"},
}

FunctionNode = ast.AsyncFunctionDef | ast.FunctionDef


def _functions(tree: ast.Module) -> list[FunctionNode]:
    return [
        node
        for node in tree.body
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
    ]


def _methods(module_class: ast.ClassDef) -> list[FunctionNode]:
    return [
        node
        for node in module_class.body
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
    ]


def _callee_name(node: ast.Call) -> str | None:
    callee = node.func
    if isinstance(callee, ast.Attribute):
        return callee.attr
    if isinstance(callee, ast.Name):
        return callee.id
    return None


def _checked_capabilities(function: FunctionNode) -> set[str]:
    """Capabilities named at a call that checks the caller for them."""

    capabilities: set[str] = set()
    for node in ast.walk(function):
        if isinstance(node, ast.Call) and _callee_name(node) in CHECK_CALLS:
            for argument in list(node.args) + [kw.value for kw in node.keywords]:
                capabilities.update(CAPABILITY_LITERAL.findall(ast.unparse(argument)))
    return capabilities


def _service_requirements() -> dict[str, set[str]]:
    """`Class.method` to the capabilities that method asks the caller to hold."""

    requirements: dict[str, set[str]] = {}
    for path in sorted(APPLICATION_ROOT.glob("*.py")):
        for module_class in (
            n for n in ast.parse(path.read_text()).body if isinstance(n, ast.ClassDef)
        ):
            for method in _methods(module_class):
                capabilities = _checked_capabilities(method)
                if capabilities:
                    requirements[f"{module_class.name}.{method.name}"] = capabilities
    return requirements


def _multi_workspace_sites() -> set[str]:
    """Service methods that authorize a capability against a workspace they choose."""

    sites: set[str] = set()
    for path in sorted(APPLICATION_ROOT.glob("*.py")):
        for module_class in (
            n for n in ast.parse(path.read_text()).body if isinstance(n, ast.ClassDef)
        ):
            for method in _methods(module_class):
                for node in ast.walk(method):
                    if (
                        isinstance(node, ast.Call)
                        and _callee_name(node) in MULTI_WORKSPACE_CHECKS
                        and CAPABILITY_LITERAL.findall(ast.unparse(node))
                    ):
                        sites.add(f"{module_class.name}.{method.name}")
    return sites


def _dependency_classes() -> dict[str, str]:
    """`XDependency` annotation aliases to the service class each one resolves to."""

    aliases: dict[str, str] = {}
    for path in sorted(API_SOURCE_ROOT.rglob("*.py")):
        for statement in ast.parse(path.read_text()).body:
            if isinstance(statement, ast.AnnAssign):
                targets = [statement.target]
            elif isinstance(statement, ast.Assign):
                targets = list(statement.targets)
            else:
                continue
            if statement.value is None:
                continue
            text = ast.unparse(statement.value)
            for target in targets:
                name = getattr(target, "id", None)
                if not (name and name.endswith("Dependency")):
                    continue
                services = set(re.findall(r"\b([A-Z][A-Za-z0-9_]*Service)\b", text))
                if len(services) == 1:
                    aliases[name] = services.pop()
    return aliases


def _parameters(function: FunctionNode) -> list[ast.arg]:
    return [*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs]


def _route_requirements(
    function: FunctionNode,
    helpers: dict[str, FunctionNode],
    dependencies: dict[str, str],
) -> tuple[set[str], dict[str, str], bool, bool]:
    """Capability declarations, service parameters, and how the route gets its actor."""

    capabilities: set[str] = set()
    services: dict[str, str] = {}
    admits_token = False
    browser_only = False
    for argument in _parameters(function):
        if argument.annotation is None:
            continue
        text = ast.unparse(argument.annotation)
        if CAPABILITY_DEPENDENCY in text:
            admits_token = True
            capabilities.update(CAPABILITY_LITERAL.findall(text))
        if any(name in text for name in BROWSER_ACTOR_DEPENDENCIES):
            browser_only = True
        alias = text.split("[")[0].strip()
        if alias in dependencies:
            services[argument.arg] = dependencies[alias]

    # A route may authorize through a helper in its own module, as the Project room does.
    resolved = {function.name}
    pending = [function]
    while pending:
        current = pending.pop()
        for node in ast.walk(current):
            if not isinstance(node, ast.Call):
                continue
            name = _callee_name(node)
            if name in helpers and name not in resolved:
                resolved.add(name)
                pending.append(helpers[name])
            capabilities.update(_checked_capabilities(node))
    return capabilities, services, admits_token, browser_only


def _routes() -> list[tuple[str, FunctionNode, ast.Module]]:
    routes = []
    for path in sorted(ROUTES_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text())
        for function in _functions(tree):
            if any(
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and decorator.func.attr in ROUTE_DECORATORS
                for decorator in function.decorator_list
            ):
                routes.append((str(path.relative_to(REPO_ROOT)), function, tree))
    return routes


def _service_calls(function: FunctionNode, services: dict[str, str]) -> set[str]:
    calls = set()
    for node in ast.walk(function):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in services
        ):
            calls.add(f"{services[node.func.value.id]}.{node.func.attr}")
    return calls


def test_service_authorizations_are_declared_by_the_routes_above_them() -> None:
    requirements = _service_requirements()
    assert requirements, "no service-layer authorization left to check"
    dependencies = _dependency_classes()

    mismatches: list[str] = []
    unclassified: list[str] = []
    edges: dict[str, set[str]] = {}
    for path, route, tree in _routes():
        helpers = {function.name: function for function in _functions(tree)}
        declared, services, admits_token, browser_only = _route_requirements(
            route, helpers, dependencies
        )
        wanted = {
            call: requirements[call]
            for call in _service_calls(route, services)
            if requirements.get(call)
        }
        if not wanted:
            continue
        edges[route.name] = set(wanted)
        if not admits_token and not browser_only:
            unclassified.append(
                f"{path}::{route.name} reaches an authorizing service but declares no "
                f"{CAPABILITY_DEPENDENCY} and resolves no browser actor, so this file "
                "cannot tell whether a scoped token can reach it"
            )
            continue
        required = {capability for caps in wanted.values() for capability in caps}
        if not admits_token:
            continue
        if not required <= declared:
            mismatches.append(
                f"{path}::{route.name} calls a service that authorizes "
                f"{sorted(required - declared)}, which the route does not require; it "
                f"declares {sorted(declared)} and a token scoped to exactly that would "
                "pass the route and be re-checked against the role alone"
            )

    assert unclassified == []
    assert mismatches == []
    for route_name, expected in ANCHOR_EDGES.items():
        assert expected <= edges.get(route_name, set()), (
            f"{route_name} no longer resolves through {sorted(expected)}; the capability "
            f"rule sees only {sorted(edges.get(route_name, set()))} and has stopped "
            "checking what it was written to check"
        )


def test_multi_workspace_authorizations_stay_limited_to_the_reviewed_sites() -> None:
    """A capability checked against a workspace the route did not name cannot be covered.

    The copy route checks VIEW_PROJECT for the token's Workspace; its service also
    checks the source Workspace. A PAT is bound to one Workspace, while browser
    credentials are authorized against both Workspaces by the service. Any new
    multi-Workspace authorization requires a separate review.
    """

    assert _multi_workspace_sites() == KNOWN_MULTI_WORKSPACE_SITES
