"""Ten-agent LangGraph workflow for the local workforce recommendation path."""

from functools import lru_cache
from typing import Literal, TypedDict, cast

from langgraph.graph import END, START, StateGraph
from langchain_core.tracers.langchain import LangChainTracer
from langsmith import Client, tracing_context

from costopt.agents.approval import ApprovalAgent
from costopt.agents.base import AgentExecution
from costopt.agents.compliance import ComplianceAssessment
from costopt.agents.contract_agent import ContractAgent
from costopt.agents.financial import FinancialWorkingCapitalAgent
from costopt.agents.optimization_agent import OptimizationAgent
from costopt.agents.planner import PlannerAgent
from costopt.agents.reporting import ReportingAgent
from costopt.agents.retriever import RetrieverAgent
from costopt.agents.risk_bcp import RiskBCPAgent
from costopt.agents.tail_spend import TailSpendAgent
from costopt.agents.timezone_mitigation import TimezoneMitigationAgent
from costopt.config import AgentName, AgentLLMProfile, settings
from costopt.models.domain import (
    AgentFinding,
    AgentLLMMetadata,
    AgentStage,
    ScenarioAnalysisRequest,
    ScenarioAnalysisResult,
    ScenarioContext,
)
from costopt.storage.repositories import load_scenario_context
from costopt.observability.logging import get_logger


logger = get_logger(__name__)


class WorkforceGraphState(TypedDict, total=False):
    request: ScenarioAnalysisRequest
    context_override: ScenarioContext
    scenario_context: ScenarioContext
    compliance: ComplianceAssessment
    recommendation: ScenarioAnalysisResult
    executions: dict[str, AgentExecution]
    findings: dict[str, AgentFinding]
    stages: list[AgentStage]
    requires_human_review: bool
    review_reasons: list[str]


def run_workforce_graph(
    request: ScenarioAnalysisRequest, context_override: ScenarioContext | None = None
) -> WorkforceGraphState:
    """Run all ten target roles with deterministic, auditable components."""
    logger.info(
        "Workforce graph started",
        extra={
            "event": "workforce_graph_started",
            "scenario_id": request.scenario_id,
            "scenario_name": request.scenario_name,
        },
    )
    initial_state: WorkforceGraphState = {"request": request}
    if context_override is not None:
        initial_state["context_override"] = context_override
    callbacks = []
    if settings.langsmith_tracing_enabled:
        if settings.langsmith_api_key is None or not settings.langsmith_api_key.get_secret_value():
            raise ValueError("LangSmith tracing is enabled but LANGSMITH_API_KEY is not configured.")
        client = Client(
            api_key=settings.langsmith_api_key.get_secret_value(),
            api_url=settings.langsmith_endpoint,
            hide_inputs=True,
            hide_outputs=True,
            hide_metadata=True,
        )
        callbacks.append(LangChainTracer(project_name=settings.langsmith_project, client=client))
    # The dedicated callback above is the only tracer this graph passes to
    # LangChain.  Do not disable the tracing context here: LangChain marks an
    # explicitly supplied tracer as disabled when `enabled=False`, preventing
    # it from sending even the masked node/timing events to LangSmith.
    # Ambient LANGSMITH_TRACING remains unsupported for this application.
    with tracing_context(enabled=None):
        state = cast(
            WorkforceGraphState,
            get_workforce_graph().invoke(
                initial_state,
                config={"callbacks": callbacks, "run_name": "costopt_workforce_analysis"},
            ),
        )
    logger.info(
        "Workforce graph completed",
        extra={
            "event": "workforce_graph_completed",
            "scenario_id": state["recommendation"].scenario_id,
            "requires_human_review": state.get("requires_human_review", False),
            "stage_count": len(state.get("stages", [])),
        },
    )
    return state


@lru_cache(maxsize=1)
def get_workforce_graph():
    """Compile the graph once; runtime configuration is read by individual nodes."""
    workflow = StateGraph(WorkforceGraphState)
    workflow.add_node("load_context", _load_context)
    workflow.add_node("planner", _plan)
    workflow.add_node("retriever", _retrieve)
    workflow.add_node("contract", _assess_compliance)
    workflow.add_node("tail_spend", _assess_tail_spend)
    workflow.add_node("risk_bcp", _assess_risk_bcp)
    workflow.add_node("timezone_mitigation", _assess_timezone_mitigation)
    workflow.add_node("optimization", _optimize)
    workflow.add_node("blocked_optimization", _build_blocked_recommendation)
    workflow.add_node("financial_working_capital", _assess_financials)
    workflow.add_node("reporting", _finalize_recommendation)
    workflow.add_node("approval", _prepare_human_review)
    workflow.add_edge(START, "load_context")
    workflow.add_edge("load_context", "planner")
    workflow.add_edge("planner", "retriever")
    workflow.add_edge("retriever", "contract")
    workflow.add_edge("contract", "tail_spend")
    workflow.add_edge("tail_spend", "risk_bcp")
    workflow.add_edge("risk_bcp", "timezone_mitigation")
    workflow.add_conditional_edges(
        "timezone_mitigation",
        _route_after_compliance,
        {
            "blocked": "blocked_optimization",
            "optimize": "optimization",
        },
    )
    workflow.add_edge("optimization", "financial_working_capital")
    workflow.add_edge("blocked_optimization", "financial_working_capital")
    workflow.add_edge("financial_working_capital", "reporting")
    workflow.add_edge("reporting", "approval")
    workflow.add_edge("approval", END)
    return workflow.compile()


def _load_context(state: WorkforceGraphState) -> WorkforceGraphState:
    request = state["request"]
    return {
        "scenario_context": state.get("context_override") or load_scenario_context(
            scenario_name=request.scenario_name,
            scenario_id=request.scenario_id,
            target_location_id=request.target_location_id,
        ),
        "executions": {},
        "findings": {},
        "stages": [],
    }


def _plan(state: WorkforceGraphState) -> WorkforceGraphState:
    finding, execution = PlannerAgent().plan(state["request"], state["scenario_context"])
    return _component_update(state, "planner", finding, execution)


def _retrieve(state: WorkforceGraphState) -> WorkforceGraphState:
    finding, execution = RetrieverAgent().retrieve(state["scenario_context"])
    return _component_update(state, "retriever", finding, execution)


def _assess_compliance(state: WorkforceGraphState) -> WorkforceGraphState:
    context = state["scenario_context"]
    target_location = next(
        location
        for location in context.locations
        if location.location_id == context.target_location_id
    )
    compliance, execution = ContractAgent().analyze(
        context.contracts,
        context.clauses,
        target_is_offshore=target_location.is_offshore,
    )
    finding = AgentFinding(
        status=(
            "blocked"
            if compliance.outcome == "blocked"
            else "limited"
            if not compliance.evidence_complete
            else "ready"
        ),
        summary=compliance.result.summary,
        metrics={
            "supplier_count": len(compliance.supplier_assessments),
            "compliance_outcome": compliance.outcome,
            "evidence_complete": compliance.evidence_complete,
        },
        data_gaps=[*compliance.missing_evidence, *compliance.evidence_conflicts],
        recommendations=execution.narrative.next_actions,
    )
    component = _component_update(state, "contract", finding, execution, compliance.outcome)
    return {
        "compliance": compliance,
        **component,
    }


def _assess_tail_spend(state: WorkforceGraphState) -> WorkforceGraphState:
    finding, execution = TailSpendAgent().analyze(state["scenario_context"])
    return _component_update(state, "tail_spend", finding, execution)


def _assess_risk_bcp(state: WorkforceGraphState) -> WorkforceGraphState:
    finding, execution = RiskBCPAgent().analyze(state["scenario_context"])
    return _component_update(state, "risk_bcp", finding, execution)


def _assess_timezone_mitigation(state: WorkforceGraphState) -> WorkforceGraphState:
    finding, execution = TimezoneMitigationAgent().analyze(state["scenario_context"])
    return _component_update(state, "timezone_mitigation", finding, execution)


def _route_after_compliance(state: WorkforceGraphState) -> Literal["blocked", "optimize"]:
    if not state["compliance"].movement_permitted:
        return "blocked"
    return "optimize"


def _optimize(state: WorkforceGraphState) -> WorkforceGraphState:
    recommendation, execution = OptimizationAgent().analyze(
        state["scenario_context"],
        state["compliance"],
    )
    finding = _optimization_finding(state, recommendation, execution)
    component = _component_update(
        state,
        "optimization",
        finding,
        execution,
        f"{recommendation.moved_count} eligible roles selected by OR-Tools",
    )
    return {
        "recommendation": recommendation,
        **component,
    }


def _build_blocked_recommendation(state: WorkforceGraphState) -> WorkforceGraphState:
    """Build a zero-move recommendation without entering the normal optimization path."""
    recommendation, execution = OptimizationAgent().analyze(
        state["scenario_context"],
        state["compliance"],
    )
    finding = _optimization_finding(state, recommendation, execution)
    component = _component_update(
        state,
        "optimization",
        finding,
        execution,
        "optimization skipped because contract evidence blocks the target delivery model",
    )
    return {
        "recommendation": recommendation,
        **component,
    }


def _optimization_finding(
    state: WorkforceGraphState,
    recommendation: ScenarioAnalysisResult,
    execution: AgentExecution,
) -> AgentFinding:
    return AgentFinding(
        status="blocked" if not state["compliance"].movement_permitted else "ready",
        summary=execution.narrative.summary,
        metrics={
            "engine": "ortools_cp_sat",
            "moved_count": recommendation.moved_count,
            "retained_count": recommendation.retained_count,
            "annual_savings": recommendation.costs.annual_savings,
            "currency": recommendation.costs.currency,
        },
        data_gaps=recommendation.data_quality_issues,
        recommendations=execution.narrative.next_actions,
    )


def _assess_financials(state: WorkforceGraphState) -> WorkforceGraphState:
    finding, execution = FinancialWorkingCapitalAgent().analyze(
        state["scenario_context"], state["recommendation"]
    )
    return _component_update(state, "financial_working_capital", finding, execution)


def _finalize_recommendation(state: WorkforceGraphState) -> WorkforceGraphState:
    supporting_names = (
        "planner",
        "retriever",
        "tail_spend",
        "risk_bcp",
        "timezone_mitigation",
        "financial_working_capital",
    )
    execution = ReportingAgent().compose(
        state["recommendation"],
        state["executions"]["contract"].narrative,
        state["executions"]["optimization"].narrative,
        [state["executions"][name].narrative for name in supporting_names],
    )
    finding = AgentFinding(
        status="ready",
        summary=execution.narrative.summary,
        metrics={
            "specialist_outputs_combined": 8,
            "citation_count": len(execution.narrative.citation_ids),
            "risk_count": len(execution.narrative.risks),
        },
        recommendations=execution.narrative.next_actions,
    )
    return _component_update(
        state, "reporting", finding, execution, "recommendation_ready"
    )


def _prepare_human_review(state: WorkforceGraphState) -> WorkforceGraphState:
    finding, execution, requires_review, reasons = ApprovalAgent().assess(
        state["recommendation"], state["compliance"]
    )
    component = _component_update(state, "approval", finding, execution)
    return {
        "requires_human_review": requires_review,
        "review_reasons": reasons,
        **component,
    }


def _component_update(
    state: WorkforceGraphState,
    agent: AgentName,
    finding: AgentFinding,
    execution: AgentExecution,
    outcome: str | None = None,
) -> WorkforceGraphState:
    return {
        "findings": {**state.get("findings", {}), agent: finding},
        "executions": {**state.get("executions", {}), agent: execution},
        "stages": [
            *state.get("stages", []),
            AgentStage(
                name=agent,
                status="completed",
                outcome=outcome or finding.status,
                llm=_llm_metadata(agent),
                narrative=execution.narrative,
                used_fallback=execution.used_fallback,
                tool_traces=execution.tool_traces,
                finding=finding,
            ),
        ],
    }


def _llm_metadata(agent: AgentName) -> AgentLLMMetadata:
    profile: AgentLLMProfile = settings.get_agent_llm_profile(agent)
    return AgentLLMMetadata(
        enabled=profile.enabled,
        provider=profile.provider,
        model=profile.model,
        prompt_key=profile.prompt_key,
    )
