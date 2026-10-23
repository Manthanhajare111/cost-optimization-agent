from costopt.models.domain import (
    AgentRunResult,
    ScenarioAnalysisRequest,
    ScenarioInputSnapshot,
)
from costopt.pipeline.workforce_graph import run_workforce_graph
from costopt.observability.logging import get_logger


logger = get_logger(__name__)


def run_scenario(request: ScenarioAnalysisRequest) -> AgentRunResult:
    """Run the compiled LangGraph workflow for a single workforce scenario."""
    logger.info(
        "Scenario orchestration started",
        extra={
            "event": "scenario_orchestration_started",
            "scenario_id": request.scenario_id,
            "scenario_name": request.scenario_name,
        },
    )
    graph_state = run_workforce_graph(request)
    context = graph_state["scenario_context"]
    result = AgentRunResult(
        recommendation=graph_state["recommendation"],
        stages=graph_state["stages"],
        requires_human_review=graph_state.get("requires_human_review", False),
        review_reasons=graph_state.get("review_reasons", []),
        input_snapshot=ScenarioInputSnapshot(
            scenario_id=context.scenario_id,
            scenario_name=context.scenario_name,
            requested_target_location_id=request.target_location_id,
            current_location_id=context.current_location_id,
            current_location_ids=context.current_location_ids,
            target_location_id=context.target_location_id,
            billing_units_per_month=context.billing_units_per_month,
            squad=context.squad,
            resources=context.resources,
            rate_cards=context.rate_cards,
            contract=context.contracts[0] if len(context.contracts) == 1 else None,
            contracts=context.contracts,
            clauses=context.clauses,
            assumptions=context.assumptions,
        ),
    )
    logger.info(
        "Scenario orchestration completed",
        extra={
            "event": "scenario_orchestration_completed",
            "scenario_id": result.recommendation.scenario_id,
            "moved_count": result.recommendation.moved_count,
        },
    )
    return result
