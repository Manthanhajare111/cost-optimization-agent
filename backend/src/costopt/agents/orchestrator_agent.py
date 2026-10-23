"""Recommendation orchestrator agent that summarizes verified worker-agent outputs."""

from costopt.agents.base import AgentExecution, StructuredCostOptAgent
from costopt.config import settings
from costopt.models.domain import AgentNarrative, AgentToolTrace, ScenarioAnalysisResult


class RecommendationOrchestratorAgent:
    def __init__(self) -> None:
        self._runtime = StructuredCostOptAgent(settings.get_agent_llm_profile("reporting"))

    def compose(
        self,
        recommendation: ScenarioAnalysisResult,
        compliance_narrative: AgentNarrative,
        optimization_narrative: AgentNarrative,
        supporting_narratives: list[AgentNarrative] | None = None,
    ) -> AgentExecution:
        supporting = supporting_narratives or []
        citation_ids = [citation.clause_id for citation in recommendation.compliance.citations]
        fallback = AgentNarrative(
            summary=recommendation.recommendation,
            key_considerations=[
                compliance_narrative.summary,
                optimization_narrative.summary,
                *[narrative.summary for narrative in supporting],
                "Savings are estimates only and require human approval before execution.",
            ],
            citation_ids=citation_ids,
            risks=[
                *compliance_narrative.risks,
                *optimization_narrative.risks,
                *[risk for narrative in supporting for risk in narrative.risks],
            ],
            next_actions=[
                *compliance_narrative.next_actions,
                *optimization_narrative.next_actions,
                *[action for narrative in supporting for action in narrative.next_actions],
            ],
        )
        return self._runtime.explain(
            facts={
                "recommendation": recommendation.model_dump(),
                "compliance_narrative": compliance_narrative.model_dump(),
                "optimization_narrative": optimization_narrative.model_dump(),
                "supporting_narratives": [item.model_dump() for item in supporting],
            },
            fallback=fallback,
            allowed_citation_ids=set(citation_ids),
            tool_traces=[
                AgentToolTrace(
                    tool_name="verified_output_synthesizer",
                    status="completed",
                    summary="Combined all validated specialist-agent outputs.",
                    evidence_ids=citation_ids,
                )
            ],
        )
