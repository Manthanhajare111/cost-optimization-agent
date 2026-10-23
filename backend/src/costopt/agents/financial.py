"""Financial and working-capital analysis component."""

from costopt.agents.base import AgentExecution
from costopt.agents.component import build_component_execution
from costopt.models.domain import AgentFinding, ScenarioAnalysisResult, ScenarioContext
from costopt.observability.logging import get_logger


logger = get_logger(__name__)


class FinancialWorkingCapitalAgent:
    def analyze(
        self, context: ScenarioContext, recommendation: ScenarioAnalysisResult
    ) -> tuple[AgentFinding, AgentExecution]:
        logger.info(
            "Financial and working-capital agent started",
            extra={
                "event": "financial_working_capital_agent_started",
                "scenario_id": context.scenario_id,
            },
        )
        annual_baseline = round(recommendation.costs.baseline_cost * 12, 2)
        savings_pct = (
            round(100 * recommendation.costs.annual_savings / annual_baseline, 2)
            if annual_baseline
            else 0.0
        )
        transition_cost = _optional_number(context.assumptions.get("transition_cost"))
        working_capital_impact = _optional_number(
            context.assumptions.get("working_capital_impact")
        )
        payback_months = (
            round(transition_cost / recommendation.costs.monthly_savings, 2)
            if transition_cost is not None and recommendation.costs.monthly_savings > 0
            else None
        )
        gaps: list[str] = []
        if transition_cost is None:
            gaps.append("Transition and onboarding cost is not supplied.")
        if working_capital_impact is None:
            gaps.append("Working-capital impact is not supplied.")
        finding = AgentFinding(
            status="limited" if gaps else "ready",
            summary=(
                f"Estimated annual run-rate savings of {recommendation.costs.currency} "
                f"{recommendation.costs.annual_savings:,.2f} ({savings_pct:.2f}% of baseline)."
            ),
            metrics={
                "currency": recommendation.costs.currency,
                "annual_baseline_cost": annual_baseline,
                "annual_run_rate_savings": recommendation.costs.annual_savings,
                "run_rate_savings_pct": savings_pct,
                "transition_cost": transition_cost,
                "working_capital_impact": working_capital_impact,
                "payback_months": payback_months,
            },
            data_gaps=gaps,
            recommendations=(
                ["Provide transition and payment-term assumptions before approving the business case."]
                if gaps
                else ["Include the verified payback and working-capital impact in the approval pack."]
            ),
        )
        execution = build_component_execution(
            "financial_working_capital", finding, "financial_impact_calculator"
        )
        logger.info(
            "Financial and working-capital agent completed",
            extra={
                "event": "financial_working_capital_agent_completed",
                "scenario_id": context.scenario_id,
                "annual_savings": recommendation.costs.annual_savings,
                "data_gap_count": len(gaps),
            },
        )
        return finding, execution


def _optional_number(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
