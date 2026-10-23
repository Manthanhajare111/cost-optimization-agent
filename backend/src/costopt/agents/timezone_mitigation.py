"""Workforce readiness and timezone evidence component."""

from collections import Counter

from costopt.agents.base import AgentExecution
from costopt.agents.component import build_component_execution
from costopt.models.domain import AgentFinding, ScenarioContext
from costopt.observability.logging import get_logger


logger = get_logger(__name__)


class TimezoneMitigationAgent:
    def analyze(self, context: ScenarioContext) -> tuple[AgentFinding, AgentExecution]:
        logger.info(
            "Timezone and mitigation agent started",
            extra={
                "event": "timezone_mitigation_agent_started",
                "scenario_id": context.scenario_id,
            },
        )
        availability = Counter((resource.availability or "unknown").casefold() for resource in context.resources)
        active_count = availability.get("active", 0)
        timezone_overlap = context.assumptions.get("timezone_overlap_hours")
        utilization = context.assumptions.get("utilization_pct")
        gaps: list[str] = []
        if timezone_overlap is None:
            gaps.append("Timezone-overlap hours are not present in the scenario data.")
        if utilization is None:
            gaps.append("Fieldglass utilization percentages are not present in the scenario data.")
        finding = AgentFinding(
            status="limited" if gaps else "ready",
            summary=(
                f"Assessed {len(context.resources)} resources across "
                f"{len({resource.skill for resource in context.resources})} required skills."
            ),
            metrics={
                "resource_count": len(context.resources),
                "unique_skill_count": len({resource.skill for resource in context.resources}),
                "active_resource_count": active_count,
                "timezone_overlap_hours": timezone_overlap,
                "utilization_pct": utilization,
            },
            data_gaps=gaps,
            recommendations=(
                ["Load Fieldglass assignment, utilization, and working-hours data for feasibility scoring."]
                if gaps
                else ["Apply the verified overlap and utilization measures as optimization constraints."]
            ),
        )
        execution = build_component_execution(
            "timezone_mitigation", finding, "workforce_readiness_checker"
        )
        logger.info(
            "Timezone and mitigation agent completed",
            extra={
                "event": "timezone_mitigation_agent_completed",
                "scenario_id": context.scenario_id,
                "data_gap_count": len(gaps),
            },
        )
        return finding, execution
