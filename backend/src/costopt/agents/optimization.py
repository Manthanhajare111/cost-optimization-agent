from decimal import Decimal, ROUND_HALF_UP

from ortools.sat.python import cp_model

from costopt.agents.compliance import ComplianceAssessment
from costopt.config import settings
from costopt.models.domain import (
    CostSummary,
    RateCard,
    Resource,
    ResourceDecision,
    ScenarioAnalysisResult,
    ScenarioContext,
    SupplierComplianceSummary,
)
from costopt.observability.logging import get_logger


BASE_CONFIDENCE = 0.90
APPROVAL_CONFIDENCE_PENALTY = 0.02
RESIDENCY_CONFIDENCE_PENALTY = 0.01
logger = get_logger(__name__)


def optimize_workforce(
    scenario_context: ScenarioContext,
    compliance: ComplianceAssessment,
) -> ScenarioAnalysisResult:
    """Calculate the right-shoring option, treating compliance as a hard constraint."""
    logger.info(
        "Workforce optimization started",
        extra={
            "event": "workforce_optimization_started",
            "scenario_id": scenario_context.scenario_id,
            "resource_count": len(scenario_context.resources),
            "target_location_id": scenario_context.target_location_id,
        },
    )
    resources = scenario_context.resources
    rate_cards = scenario_context.rate_cards
    squad = scenario_context.squad
    billing_units_per_month = scenario_context.billing_units_per_month
    target_location_id = scenario_context.target_location_id
    current_location_id = scenario_context.current_location_id

    baseline_total = _calculate_period_cost(
        [resource.current_rate for resource in resources], billing_units_per_month
    )
    decisions: list[ResourceDecision] = []
    data_quality_issues: set[str] = set()
    future_rates: list[float] = []
    prepared: dict[str, tuple[str, str, RateCard | None]] = {}
    candidate_rates: dict[str, tuple[float, float]] = {}

    for resource in resources:
        action, reason = _decide_action(resource, compliance, target_location_id)
        target_rate_card: RateCard | None = None
        if action == "move":
            target_rate_card = _find_rate_card(
                rate_cards, resource.supplier_id, target_location_id, resource.role
            )
            if target_rate_card is None:
                action = "retain"
                reason = "No target rate card is available, so this role cannot be evaluated safely."
                data_quality_issues.add(
                    f"Missing rate card for supplier={resource.supplier_id}, "
                    f"location={target_location_id}, role={resource.role}."
                )
                logger.warning(
                    "Target rate card is missing; resource retained",
                    extra={
                        "event": "target_rate_card_missing",
                        "scenario_id": scenario_context.scenario_id,
                        "supplier_id": resource.supplier_id,
                        "role": resource.role,
                        "target_location_id": target_location_id,
                    },
                )
            elif target_rate_card.currency.upper() != scenario_context.currency:
                action = "retain"
                reason = "Target rate-card currency does not match the scenario currency."
                data_quality_issues.add(
                    f"Currency mismatch for rate_card={target_rate_card.rate_card_id}."
                )
            elif target_rate_card.bill_rate >= resource.current_rate:
                action = "retain"
                reason = (
                    "Target rate is not lower than the current rate, so moving this role "
                    "would not create savings."
                )
            else:
                candidate_rates[resource.resource_id] = (
                    resource.current_rate,
                    target_rate_card.bill_rate,
                )
        prepared[resource.resource_id] = (action, reason, target_rate_card)

    selected_resource_ids = _select_cost_optimal_moves(candidate_rates)

    for resource in resources:
        action, reason, target_rate_card = prepared[resource.resource_id]
        projected_rate = resource.current_rate
        projected_location_id: str | None = None
        if action == "move" and resource.resource_id in selected_resource_ids:
            projected_location_id = target_location_id
            projected_rate = target_rate_card.bill_rate if target_rate_card else resource.current_rate
            reason = "OR-Tools selected this eligible role in the minimum-cost allocation."
        elif action == "move":
            action = "retain"
            reason = "OR-Tools retained this eligible role in the minimum-cost allocation."

        future_rates.append(projected_rate)
        decisions.append(
            ResourceDecision(
                resource_id=resource.resource_id,
                supplier_id=resource.supplier_id,
                role=resource.role,
                skill=resource.skill,
                action=action,
                reason=reason,
                current_location_id=resource.current_location_id,
                target_location_id=projected_location_id,
                current_rate=resource.current_rate,
                projected_rate=projected_rate,
            )
        )

    future_total = _calculate_period_cost(future_rates, billing_units_per_month)
    monthly_savings = _round_currency(baseline_total - future_total)
    annual_savings = _round_currency(monthly_savings * 12)
    confidence_score = _compute_confidence(
        compliance.result.data_residency_restriction,
        compliance.result.customer_approval_required,
        len(data_quality_issues),
    )
    retained_count = sum(decision.action == "retain" for decision in decisions)
    moved_count = sum(decision.action == "move" for decision in decisions)

    result = ScenarioAnalysisResult(
        scenario_id=scenario_context.scenario_id,
        scenario_name=scenario_context.scenario_name,
        squad_id=squad.squad_id,
        squad_name=squad.name,
        current_location_id=current_location_id,
        current_location_ids=scenario_context.current_location_ids,
        target_location_id=target_location_id,
        retained_count=retained_count,
        moved_count=moved_count,
        recommendation=_build_recommendation(moved_count, retained_count, squad.name, compliance),
        rationale=_build_rationale(current_location_id, target_location_id, compliance),
        confidence_score=confidence_score,
        compliance=compliance.result,
        supplier_compliance={
            supplier_id: SupplierComplianceSummary(
                supplier_id=item.supplier_id,
                contract_id=item.contract_id,
                assessment=item.outcome,
                movement_permitted=item.movement_permitted,
                evidence_complete=item.evidence_complete,
                missing_evidence=item.missing_evidence,
                evidence_conflicts=item.evidence_conflicts,
                result=item.result,
            )
            for supplier_id, item in compliance.supplier_assessments.items()
        },
        costs=CostSummary(
            currency=scenario_context.currency,
            billing_units_per_month=billing_units_per_month,
            baseline_cost=baseline_total,
            future_cost=future_total,
            monthly_savings=monthly_savings,
            annual_savings=annual_savings,
        ),
        resource_decisions=decisions,
        data_quality_issues=sorted(data_quality_issues),
    )
    logger.info(
        "Workforce optimization completed",
        extra={
            "event": "workforce_optimization_completed",
            "scenario_id": result.scenario_id,
            "moved_count": result.moved_count,
            "retained_count": result.retained_count,
            "annual_savings": result.costs.annual_savings,
            "currency": result.costs.currency,
            "data_quality_issue_count": len(result.data_quality_issues),
        },
    )
    return result


def _select_cost_optimal_moves(
    candidate_rates: dict[str, tuple[float, float]],
) -> set[str]:
    """Use CP-SAT to maximize verified run-rate savings for eligible resources."""
    if not candidate_rates:
        return set()
    model = cp_model.CpModel()
    move_variables = {
        resource_id: model.new_bool_var(f"move_{index}")
        for index, resource_id in enumerate(sorted(candidate_rates))
    }
    savings_minor_units = {
        resource_id: int(round((current_rate - target_rate) * 100))
        for resource_id, (current_rate, target_rate) in candidate_rates.items()
    }
    model.maximize(
        sum(
            savings_minor_units[resource_id] * move_variables[resource_id]
            for resource_id in move_variables
        )
    )
    solver = cp_model.CpSolver()
    status = solver.solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise RuntimeError("OR-Tools could not produce a feasible workforce allocation.")
    selected = {
        resource_id
        for resource_id, variable in move_variables.items()
        if solver.value(variable) == 1
    }
    logger.info(
        "OR-Tools workforce allocation completed",
        extra={
            "event": "ortools_workforce_allocation_completed",
            "candidate_count": len(candidate_rates),
            "selected_count": len(selected),
            "solver_status": solver.status_name(status),
        },
    )
    return selected


def _decide_action(
    resource: Resource,
    compliance: ComplianceAssessment,
    target_location_id: str,
) -> tuple[str, str]:
    if resource.current_location_id == target_location_id:
        return "retain", "Resource is already in the requested target location."
    if not compliance.movement_permitted_for(resource.supplier_id):
        return "retain", "Verified contract evidence does not currently authorize this move."
    if resource.availability and resource.availability.lower() != "active":
        return "retain", f"Resource availability is '{resource.availability}', not active."
    if resource.role.casefold() in settings.retain_roles:
        return "retain", f"{resource.role} roles remain onshore for leadership and design continuity."
    supplier_assessment = compliance.supplier_assessments.get(resource.supplier_id)
    if (
        resource.pii_access
        and supplier_assessment
        and supplier_assessment.result.data_residency_restriction
    ):
        return "retain", "PII-handling work stays in the current location due to residency constraints."
    return "move", "Role is eligible for optimized shoring based on the seeded MVP rules."


def _find_rate_card(
    rate_cards: list[RateCard], supplier_id: str, location_id: str, role: str
) -> RateCard | None:
    for rate_card in rate_cards:
        if (
            rate_card.supplier_id == supplier_id
            and rate_card.location_id == location_id
            and rate_card.role == role
        ):
            return rate_card
    return None


def _build_recommendation(
    moved_count: int,
    retained_count: int,
    squad_name: str,
    compliance: ComplianceAssessment,
) -> str:
    if not compliance.movement_permitted:
        return f"Do not move {squad_name} until verified contract evidence authorizes the move."
    if moved_count == 0:
        return (
            f"Retain all {retained_count} roles for {squad_name}; the evaluated move does not "
            "produce a positive savings opportunity."
        )
    approval_note = (
        " after written customer approval"
        if compliance.outcome == "allowed_with_approval"
        else ""
    )
    return (
        f"Retain {retained_count} constrained roles in the current location and move "
        f"{moved_count} eligible roles for {squad_name}{approval_note}."
    )


def _build_rationale(
    current_location_id: str, target_location_id: str, compliance: ComplianceAssessment
) -> str:
    if not compliance.movement_permitted:
        return (
            "Savings are not actionable because verified contract evidence does not "
            "authorize movement."
        )
    return (
        f"Keep leadership, architecture, and PII-handling work in {current_location_id} while "
        f"moving eligible engineering work to {target_location_id}."
    )


def _compute_confidence(
    data_residency_restriction: str | None,
    customer_approval_required: bool,
    data_quality_issue_count: int,
) -> float:
    confidence = BASE_CONFIDENCE
    if customer_approval_required:
        confidence -= APPROVAL_CONFIDENCE_PENALTY
    if data_residency_restriction:
        confidence -= RESIDENCY_CONFIDENCE_PENALTY
    confidence -= min(data_quality_issue_count * 0.02, 0.20)
    return round(max(confidence, 0.0), 2)


def _round_currency(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _calculate_period_cost(rates: list[float], billing_units: float) -> float:
    total_rate = sum((Decimal(str(rate)) for rate in rates), start=Decimal("0"))
    value = total_rate * Decimal(str(billing_units))
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
