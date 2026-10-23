"""Optimization analyst agent node with deterministic savings calculation as its tool."""

from costopt.agents.base import AgentExecution, StructuredCostOptAgent
from costopt.agents.compliance import ComplianceAssessment
from costopt.agents.optimization import optimize_workforce
from costopt.config import settings
from costopt.models.domain import (
    AgentNarrative,
    AgentToolTrace,
    ScenarioAnalysisResult,
    ScenarioContext,
)
from costopt.observability.logging import get_logger


logger = get_logger(__name__)


class OptimizationAnalystAgent:
    def __init__(self) -> None:
        self._runtime = StructuredCostOptAgent(settings.get_agent_llm_profile("optimization"))

    def analyze(
        self,
        scenario_context: ScenarioContext,
        compliance: ComplianceAssessment,
    ) -> tuple[ScenarioAnalysisResult, AgentExecution]:
        logger.info(
            "Optimization agent started",
            extra={
                "event": "optimization_agent_started",
                "scenario_id": scenario_context.scenario_id,
            },
        )
        recommendation = optimize_workforce(scenario_context, compliance)
        citation_ids = [citation.clause_id for citation in recommendation.compliance.citations]
        fallback = AgentNarrative(
            summary=recommendation.rationale,
            key_considerations=[
                f"Estimated annual savings: {recommendation.costs.currency} "
                f"{recommendation.costs.annual_savings:,.0f}.",
                "Savings are estimates based on the seeded rate cards and require human approval.",
            ],
            citation_ids=citation_ids,
            risks=(
                ["Customer approval is required before executing this recommendation."]
                if compliance.result.customer_approval_required
                else []
            ),
            next_actions=["Validate assumptions with delivery leadership before execution."],
        )
        execution = self._runtime.explain(
            facts={
                "compliance_outcome": compliance.outcome,
                "recommendation": recommendation.model_dump(),
            },
            fallback=fallback,
            allowed_citation_ids=set(citation_ids),
            tool_traces=[
                AgentToolTrace(
                    tool_name="ortools_workforce_optimizer",
                    status="completed",
                    summary=(
                        f"Calculated {recommendation.moved_count} eligible moves and estimated "
                        f"annual savings of {recommendation.costs.currency} "
                        f"{recommendation.costs.annual_savings:,.0f}."
                    ),
                    evidence_ids=citation_ids,
                )
            ],
        )
        logger.info(
            "Optimization agent completed",
            extra={
                "event": "optimization_agent_completed",
                "scenario_id": scenario_context.scenario_id,
                "moved_count": recommendation.moved_count,
            },
        )
        return recommendation, execution
