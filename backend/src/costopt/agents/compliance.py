from typing import Literal

from pydantic import BaseModel, Field

from costopt.models.domain import Citation, ComplianceResult, ContractClause, ContractRecord
from costopt.tools.compliance_evidence import inspect_contract_evidence


ComplianceOutcome = Literal["allowed", "allowed_with_approval", "blocked"]


class SupplierComplianceAssessment(BaseModel):
    supplier_id: str
    contract_id: str
    outcome: ComplianceOutcome
    result: ComplianceResult
    evidence_complete: bool = True
    missing_evidence: list[str] = Field(default_factory=list)
    evidence_conflicts: list[str] = Field(default_factory=list)
    requires_human_review: bool = False

    @property
    def movement_permitted(self) -> bool:
        return self.outcome != "blocked" and self.evidence_complete and not self.evidence_conflicts


class ComplianceAssessment(BaseModel):
    outcome: ComplianceOutcome
    result: ComplianceResult
    supplier_assessments: dict[str, SupplierComplianceAssessment] = Field(default_factory=dict)
    evidence_complete: bool = True
    missing_evidence: list[str] = Field(default_factory=list)
    evidence_conflicts: list[str] = Field(default_factory=list)
    requires_human_review: bool = False

    @property
    def movement_permitted(self) -> bool:
        return any(item.movement_permitted for item in self.supplier_assessments.values())

    def movement_permitted_for(self, supplier_id: str) -> bool:
        supplier = self.supplier_assessments.get(supplier_id)
        return bool(supplier and supplier.movement_permitted)


def assess_contracts(
    contracts: list[ContractRecord],
    clauses: list[ContractClause],
    target_is_offshore: bool = True,
) -> ComplianceAssessment:
    """Evaluate all supplier contracts and create one scenario-level assessment."""
    if not contracts:
        raise ValueError("At least one supplier contract is required for compliance assessment.")
    supplier_ids = [contract.supplier_id for contract in contracts]
    if len(supplier_ids) != len(set(supplier_ids)):
        raise ValueError("Only one active contract may be assessed per supplier.")

    supplier_assessments: dict[str, SupplierComplianceAssessment] = {}
    for contract in contracts:
        contract_clauses = [
            clause
            for clause in clauses
            if clause.contract_id == contract.contract_id
            or (len(contracts) == 1 and clause.contract_id is None)
        ]
        supplier_assessments[contract.supplier_id] = _assess_supplier_contract(
            contract,
            contract_clauses,
            target_is_offshore,
        )

    missing_evidence = [
        f"{supplier_id}:{item}"
        for supplier_id, assessment in supplier_assessments.items()
        for item in assessment.missing_evidence
    ]
    evidence_conflicts = [
        f"{supplier_id}:{item}"
        for supplier_id, assessment in supplier_assessments.items()
        for item in assessment.evidence_conflicts
    ]
    permitted_count = sum(
        assessment.movement_permitted for assessment in supplier_assessments.values()
    )
    requires_human_review = any(
        assessment.requires_human_review for assessment in supplier_assessments.values()
    ) or permitted_count != len(supplier_assessments)
    if permitted_count == 0:
        outcome: ComplianceOutcome = "blocked"
    elif requires_human_review:
        outcome = "allowed_with_approval"
    else:
        outcome = "allowed"

    restrictions = sorted(
        {
            assessment.result.data_residency_restriction
            for assessment in supplier_assessments.values()
            if assessment.result.data_residency_restriction
        }
    )
    return ComplianceAssessment(
        outcome=outcome,
        result=ComplianceResult(
            assessment=outcome,
            offshore_permitted=permitted_count == len(supplier_assessments),
            data_residency_restriction="; ".join(restrictions) or None,
            customer_approval_required=any(
                assessment.result.customer_approval_required
                for assessment in supplier_assessments.values()
            ),
            summary=" ".join(
                f"{supplier_id}: {assessment.result.summary}"
                for supplier_id, assessment in supplier_assessments.items()
            ),
            citations=[
                citation
                for assessment in supplier_assessments.values()
                for citation in assessment.result.citations
            ],
        ),
        supplier_assessments=supplier_assessments,
        evidence_complete=not missing_evidence and not evidence_conflicts,
        missing_evidence=missing_evidence,
        evidence_conflicts=evidence_conflicts,
        requires_human_review=requires_human_review,
    )


def _assess_supplier_contract(
    contract: ContractRecord,
    clauses: list[ContractClause],
    target_is_offshore: bool,
) -> SupplierComplianceAssessment:
    if target_is_offshore and not contract.offshore_permitted:
        outcome: ComplianceOutcome = "blocked"
    elif contract.customer_approval_required:
        outcome = "allowed_with_approval"
    else:
        outcome = "allowed"

    residency_note = contract.data_residency_restriction or "No residency restriction recorded."
    approval_note = (
        "Written customer approval is required."
        if contract.customer_approval_required
        else "No additional customer approval is required."
    )
    if not target_is_offshore:
        offshore_note = "The target is not classified as offshore; offshore permission is not a blocker."
    else:
        offshore_note = (
            "Offshore delivery is permitted."
            if contract.offshore_permitted
            else "Offshore delivery is not permitted."
        )
    coverage = inspect_contract_evidence(contract, clauses)
    missing_evidence = coverage.missing_clause_types
    evidence_conflicts = coverage.contradictions
    if not target_is_offshore:
        missing_evidence = [item for item in missing_evidence if item != "offshore_delivery"]
        evidence_conflicts = [
            item for item in evidence_conflicts if not item.startswith("offshore_permitted")
        ]
    evidence_complete = not missing_evidence and not evidence_conflicts
    determination_by_clause_type = {
        "offshore_delivery": "offshore_permitted",
        "data_residency": "data_residency_restriction",
        "customer_approval": "customer_approval_required",
    }
    return SupplierComplianceAssessment(
        supplier_id=contract.supplier_id,
        contract_id=contract.contract_id,
        outcome=outcome,
        result=ComplianceResult(
            assessment=outcome,
            offshore_permitted=contract.offshore_permitted,
            data_residency_restriction=contract.data_residency_restriction,
            customer_approval_required=contract.customer_approval_required,
            summary=f"{offshore_note} {residency_note} {approval_note}",
            citations=[
                Citation(
                    clause_id=clause.clause_id,
                    clause_type=clause.clause_type,
                    quote=clause.clause_text,
                    determination=determination_by_clause_type.get(clause.clause_type),
                )
                for clause in clauses
                if clause.clause_type in determination_by_clause_type
            ],
        ),
        evidence_complete=evidence_complete,
        missing_evidence=missing_evidence,
        evidence_conflicts=evidence_conflicts,
        requires_human_review=(
            contract.customer_approval_required
            or not evidence_complete
        ),
    )
