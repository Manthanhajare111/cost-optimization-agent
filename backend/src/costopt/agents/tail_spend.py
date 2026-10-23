"""Supplier concentration and rate-card coverage component."""

from collections import Counter

from costopt.agents.base import AgentExecution
from costopt.agents.component import build_component_execution
from costopt.models.domain import AgentFinding, ScenarioContext
from costopt.observability.logging import get_logger


logger = get_logger(__name__)


class TailSpendAgent:
    def analyze(self, context: ScenarioContext) -> tuple[AgentFinding, AgentExecution]:
        logger.info(
            "Tail-spend agent started",
            extra={"event": "tail_spend_agent_started", "scenario_id": context.scenario_id},
        )
        supplier_counts = Counter(resource.supplier_id for resource in context.resources)
        required_pairs = {(resource.supplier_id, resource.role) for resource in context.resources}
        covered_pairs = {
            (rate.supplier_id, rate.role)
            for rate in context.rate_cards
            if rate.location_id == context.target_location_id
        }
        dominant_count = max(supplier_counts.values(), default=0)
        concentration = round(100 * dominant_count / len(context.resources), 2)
        coverage = round(100 * len(required_pairs & covered_pairs) / len(required_pairs), 2)
        gaps: list[str] = []
        if len(supplier_counts) < 2:
            gaps.append("A single supplier is present, so consolidation alternatives cannot be compared.")
        missing_pairs = sorted(required_pairs - covered_pairs)
        if missing_pairs:
            gaps.append(
                "Target rate cards are missing for: "
                + ", ".join(f"{supplier}/{role}" for supplier, role in missing_pairs)
            )
        finding = AgentFinding(
            status="limited" if gaps else "ready",
            summary=(
                f"Measured supplier concentration and target rate-card coverage for "
                f"{len(context.resources)} workforce records."
            ),
            metrics={
                "supplier_count": len(supplier_counts),
                "dominant_supplier_share_pct": concentration,
                "target_rate_card_coverage_pct": coverage,
            },
            data_gaps=gaps,
            recommendations=[
                "Use procurement spend and qualified alternate-supplier data for a full consolidation analysis."
            ],
        )
        execution = build_component_execution(
            "tail_spend", finding, "supplier_concentration_analyzer"
        )
        logger.info(
            "Tail-spend agent completed",
            extra={
                "event": "tail_spend_agent_completed",
                "scenario_id": context.scenario_id,
                "supplier_count": len(supplier_counts),
                "coverage_pct": coverage,
            },
        )
        return finding, execution
