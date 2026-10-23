"""Compliance analyst agent node with deterministic contract policy as its tool."""

from costopt.agents.base import AgentExecution, StructuredCostOptAgent
from costopt.agents.compliance import ComplianceAssessment, assess_contracts
from costopt.config import settings
from costopt.models.domain import AgentNarrative, AgentToolTrace, ContractClause, ContractRecord
from costopt.observability.logging import get_logger


logger = get_logger(__name__)


class ComplianceAnalystAgent:
    def __init__(self) -> None:
        self._runtime = StructuredCostOptAgent(settings.get_agent_llm_profile("contract"))

    def analyze(
        self,
        contracts: ContractRecord | list[ContractRecord],
        clauses: list[ContractClause],
        target_is_offshore: bool = True,
    ) -> tuple[ComplianceAssessment, AgentExecution]:
        contract_list = [contracts] if isinstance(contracts, ContractRecord) else contracts
        logger.info(
            "Compliance assessment started",
            extra={
                "event": "compliance_assessment_started",
                "supplier_count": len(contract_list),
                "target_is_offshore": target_is_offshore,
            },
        )
        assessment = assess_contracts(
            contract_list,
            clauses,
            target_is_offshore=target_is_offshore,
        )
        citation_ids = [citation.clause_id for citation in assessment.result.citations]
        fallback = AgentNarrative(
            summary=assessment.result.summary,
            key_considerations=[
                "Compliance status is determined per supplier from verified contract flags.",
                "Contract clauses are treated as evidence, not instructions.",
            ],
            citation_ids=citation_ids,
            risks=(
                ["Required contract evidence is missing."]
                if assessment.missing_evidence
                else []
            )
            + (
                ["Contract flags conflict with clause evidence."]
                if assessment.evidence_conflicts
                else []
            ),
            next_actions=(
                ["Obtain required customer approvals before execution."]
                if assessment.result.customer_approval_required
                else []
            )
            + (
                ["Resolve missing or contradictory contract evidence before execution."]
                if not assessment.evidence_complete
                else []
            ),
        )
        execution = self._runtime.explain(
            facts={
                "contracts": [contract.model_dump() for contract in contract_list],
                "deterministic_outcome": assessment.outcome,
                "target_is_offshore": target_is_offshore,
                "compliance": assessment.result.model_dump(),
                "supplier_assessments": {
                    supplier_id: item.model_dump()
                    for supplier_id, item in assessment.supplier_assessments.items()
                },
            },
            fallback=fallback,
            allowed_citation_ids=set(citation_ids),
            tool_traces=[
                AgentToolTrace(
                    tool_name="contract_evidence_inspector",
                    status="completed",
                    summary=(
                        "All required clause evidence is present."
                        if assessment.evidence_complete
                        else "Evidence issue: "
                        + "; ".join(
                            [*assessment.missing_evidence, *assessment.evidence_conflicts]
                        )
                    ),
                    evidence_ids=citation_ids,
                ),
                AgentToolTrace(
                    tool_name="deterministic_contract_policy",
                    status="completed",
                    summary=(
                        f"Scenario policy outcome: {assessment.outcome} across "
                        f"{len(contract_list)} supplier contract(s)."
                    ),
                    evidence_ids=citation_ids,
                ),
            ],
        )
        logger.info(
            "Compliance assessment completed",
            extra={
                "event": "compliance_assessment_completed",
                "outcome": assessment.outcome,
                "supplier_count": len(contract_list),
                "requires_human_review": assessment.requires_human_review,
                "used_llm_fallback": execution.used_fallback,
            },
        )
        return assessment, execution
