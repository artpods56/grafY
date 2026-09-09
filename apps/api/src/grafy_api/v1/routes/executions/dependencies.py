from typing import Annotated

from fastapi import Depends, Request

from grafy_api.app_state import get_resources

from grafy_api.execution.manager import RunExecutionManager
from grafy_api.execution.admission import ExecutionAdmissionLimiter
from grafy_api.execution.run_graph import RunGraph
from grafy_api.execution.history import ExecutionHistoryService
from grafy_api.execution.materializations import MaterializationService
from grafy_api.v1.routes.executions.services import RunResultPresenter


def run_graph_service(request: Request) -> RunGraph:
    return get_resources(request.app).workbench.run_graph


RunGraphDependency = Annotated[RunGraph, Depends(run_graph_service)]


def execution_admission_limiter(request: Request) -> ExecutionAdmissionLimiter:
    return get_resources(request.app).workbench.execution_admission


ExecutionAdmissionLimiterDependency = Annotated[
    ExecutionAdmissionLimiter,
    Depends(execution_admission_limiter),
]


def run_execution_manager(request: Request) -> RunExecutionManager:
    return get_resources(request.app).workbench.execution_manager


RunExecutionManagerDependency = Annotated[
    RunExecutionManager,
    Depends(run_execution_manager),
]


def execution_history_service(request: Request) -> ExecutionHistoryService:
    return get_resources(request.app).workbench.execution_history


ExecutionHistoryDependency = Annotated[
    ExecutionHistoryService,
    Depends(execution_history_service),
]


def materialization_service(request: Request) -> MaterializationService:
    return get_resources(request.app).workbench.materializations


MaterializationDependency = Annotated[
    MaterializationService,
    Depends(materialization_service),
]


def run_result_presenter(request: Request) -> RunResultPresenter:
    return get_resources(request.app).workbench.presenter


RunResultPresenterDependency = Annotated[
    RunResultPresenter,
    Depends(run_result_presenter),
]


__all__ = [
    "ExecutionHistoryDependency",
    "ExecutionAdmissionLimiterDependency",
    "MaterializationDependency",
    "RunExecutionManagerDependency",
    "RunGraphDependency",
    "RunResultPresenterDependency",
    "execution_history_service",
    "execution_admission_limiter",
    "materialization_service",
    "run_execution_manager",
    "run_graph_service",
    "run_result_presenter",
]
