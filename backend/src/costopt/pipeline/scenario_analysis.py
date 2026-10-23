from costopt.agents.compliance import assess_contracts
from costopt.agents.optimization import optimize_workforce
from costopt.models.domain import (
    ScenarioAnalysisRequest,
    ScenarioAnalysisResult,
    ScenarioListItem,
    ScenarioContext,
)
from costopt.pipeline.orchestrator import run_scenario
from costopt.storage.repositories import list_scenarios, load_scenario_context
from costopt.observability.logging import get_logger


logger = get_logger(__name__)


def analyze_scenario(request: ScenarioAnalysisRequest) -> ScenarioAnalysisResult:
    return run_scenario(request).recommendation


def preview_scenario(request: ScenarioAnalysisRequest, context_override: ScenarioContext | None = None) -> ScenarioAnalysisResult:
    """Calculate a live deterministic preview without invoking an LLM or persisting a run."""
    context = context_override or load_scenario_context(
        scenario_name=request.scenario_name,
        scenario_id=request.scenario_id,
        target_location_id=request.target_location_id,
    )
    target_location = next(
        location
        for location in context.locations
        if location.location_id == context.target_location_id
    )
    compliance = assess_contracts(
        context.contracts,
        context.clauses,
        target_is_offshore=target_location.is_offshore,
    )
    return optimize_workforce(context, compliance)


def list_scenario_previews() -> list[ScenarioListItem]:
    """Return catalogue metadata with costs recalculated from current source data."""
    logger.info(
        "Scenario catalogue preview started",
        extra={"event": "scenario_catalogue_preview_started"},
    )
    previews: list[ScenarioListItem] = []
    for definition in list_scenarios():
        result = preview_scenario(ScenarioAnalysisRequest(scenario_id=definition.scenario_id))
        previews.append(
            definition.model_copy(
                update={
                    "scenario_name": result.scenario_name,
                    "target_location_id": result.target_location_id,
                    "baseline_cost": result.costs.baseline_cost,
                    "future_cost": result.costs.future_cost,
                    "monthly_savings": result.costs.monthly_savings,
                    "annual_savings": result.costs.annual_savings,
                }
            )
        )
    logger.info(
        "Scenario catalogue preview completed",
        extra={
            "event": "scenario_catalogue_preview_completed",
            "scenario_count": len(previews),
        },
    )
    return previews
