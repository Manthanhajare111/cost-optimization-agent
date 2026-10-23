"""Planner agent for the supported workforce workflow."""

from costopt.agents.base import AgentExecution
from costopt.agents.catalog import AGENT_DEFINITIONS
from costopt.agents.component import build_component_execution
from costopt.models.domain import AgentFinding, ScenarioAnalysisRequest, ScenarioContext
from costopt.observability.logging import get_logger


logger = get_logger(__name__)


class PlannerAgent:
    def plan(
        self, request: ScenarioAnalysisRequest, context: ScenarioContext
    ) -> tuple[AgentFinding, AgentExecution]:
        logger.info(
            "Planner agent started",
            extra={"event": "planner_agent_started", "scenario_id": context.scenario_id},
        )
        agent_names = [definition.name for definition in AGENT_DEFINITIONS
                       if definition.name not in {"data_cleaning", "data_validation"}]
        finding = AgentFinding(
            status="ready",
            summary=(
                f"Validated workforce scenario {context.scenario_id} and prepared a "
                f"{len(agent_names)}-agent execution plan."
            ),
            metrics={
                "workflow": "workforce_right_shoring",
                "planned_agent_count": len(agent_names),
                "requested_target": request.target_location_id or context.target_location_id,
            },
            recommendations=["Execute specialists in the governed workforce sequence."],
        )
        execution = build_component_execution("planner", finding, "deterministic_workflow_planner")
        logger.info(
            "Planner agent completed",
            extra={
                "event": "planner_agent_completed",
                "scenario_id": context.scenario_id,
                "planned_agent_count": len(agent_names),
            },
        )
        return finding, execution
