"""Local human-approval gate with a future SAP Build adapter boundary."""

from costopt.agents.base import AgentExecution
from costopt.agents.component import build_component_execution
from costopt.agents.compliance import ComplianceAssessment
from costopt.models.domain import AgentFinding, ScenarioAnalysisResult
from costopt.observability.logging import get_logger


logger = get_logger(__name__)


class ApprovalAgent:
    def assess(
        self,
        recommendation: ScenarioAnalysisResult,
        compliance: ComplianceAssessment,
    ) -> tuple[AgentFinding, AgentExecution, bool, list[str]]:
        logger.info(
            "Approval agent started",
            extra={"event": "approval_agent_started", "scenario_id": recommendation.scenario_id},
        )
        reasons: list[str] = []
        if recommendation.moved_count > 0:
            reasons.append("Material workforce movement requires explicit human approval.")
        if compliance.result.customer_approval_required:
            reasons.append("Written customer approval is required by the supplier contract.")
        if not compliance.evidence_complete:
            reasons.append(
                "Required contract evidence is missing: " + ", ".join(compliance.missing_evidence)
            )
        if compliance.evidence_conflicts:
            reasons.append("Contract evidence conflicts: " + "; ".join(compliance.evidence_conflicts))
        reasons.extend(recommendation.data_quality_issues)
        reasons = list(dict.fromkeys(reasons))
        requires_review = bool(reasons)
        finding = AgentFinding(
            status="approval_required" if requires_review else "not_required",
            summary=(
                "A local approval package is required before execution."
                if requires_review
                else "No executable movement was recommended, so no approval request is required."
            ),
            metrics={
                "approval_backend": "local_sqlite",
                "material_move_count": recommendation.moved_count,
                "reason_count": len(reasons),
                "sap_build_connected": False,
            },
            data_gaps=["SAP Build Process Automation is not connected."],
            recommendations=(reasons if reasons else ["Retain the decision in the audit trail."]),
        )
        execution = build_component_execution("approval", finding, "material_decision_gate")
        logger.info(
            "Approval agent completed",
            extra={
                "event": "approval_agent_completed",
                "scenario_id": recommendation.scenario_id,
                "requires_human_review": requires_review,
            },
        )
        return finding, execution, requires_review, reasons
