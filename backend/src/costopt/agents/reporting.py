"""Reporting Agent backed by the verified recommendation synthesizer."""

from costopt.agents.base import AgentExecution
from costopt.agents.orchestrator_agent import RecommendationOrchestratorAgent
from costopt.models.domain import AgentNarrative, ScenarioAnalysisResult
from costopt.observability.logging import get_logger


logger = get_logger(__name__)


class ReportingAgent:
    def __init__(self) -> None:
        self._delegate = RecommendationOrchestratorAgent()

    def compose(
        self,
        recommendation: ScenarioAnalysisResult,
        compliance_narrative: AgentNarrative,
        optimization_narrative: AgentNarrative,
        supporting_narratives: list[AgentNarrative] | None = None,
    ) -> AgentExecution:
        logger.info(
            "Reporting agent started",
            extra={"event": "reporting_agent_started", "scenario_id": recommendation.scenario_id},
        )
        execution = self._delegate.compose(
            recommendation,
            compliance_narrative,
            optimization_narrative,
            supporting_narratives=supporting_narratives,
        )
        logger.info(
            "Reporting agent completed",
            extra={"event": "reporting_agent_completed", "scenario_id": recommendation.scenario_id},
        )
        return execution
