"""Evidence coverage checks for the compliance analyst agent."""

from pydantic import BaseModel, Field

from costopt.models.domain import ContractClause, ContractRecord


class EvidenceCoverage(BaseModel):
    complete: bool
    required_clause_types: list[str] = Field(default_factory=list)
    missing_clause_types: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    evidence_by_determination: dict[str, list[str]] = Field(default_factory=dict)
    contradictions: list[str] = Field(default_factory=list)


def inspect_contract_evidence(
    contract: ContractRecord,
    clauses: list[ContractClause],
) -> EvidenceCoverage:
    """Verify that every contract flag used by policy has corresponding clause evidence."""
    evidence_types = {
        "offshore_permitted": "offshore_delivery",
        "data_residency_restriction": "data_residency",
        "customer_approval_required": "customer_approval",
    }
    required = list(evidence_types.values())
    clauses_by_type = {
        clause_type: [clause for clause in clauses if clause.clause_type == clause_type]
        for clause_type in required
    }
    missing = [clause_type for clause_type in required if not clauses_by_type[clause_type]]
    contradictions = _find_contradictions(contract, clauses_by_type)
    return EvidenceCoverage(
        complete=not missing and not contradictions,
        required_clause_types=required,
        missing_clause_types=missing,
        evidence_ids=[clause.clause_id for clause in clauses],
        evidence_by_determination={
            determination: [clause.clause_id for clause in clauses_by_type[clause_type]]
            for determination, clause_type in evidence_types.items()
        },
        contradictions=contradictions,
    )


def _find_contradictions(
    contract: ContractRecord,
    clauses_by_type: dict[str, list[ContractClause]],
) -> list[str]:
    contradictions: list[str] = []
    offshore_text = _combined_text(clauses_by_type["offshore_delivery"])
    approval_text = _combined_text(clauses_by_type["customer_approval"])
    residency_text = _combined_text(clauses_by_type["data_residency"])

    offshore_denied = "not permitted" in offshore_text or "prohibit" in offshore_text
    offshore_allowed = "permitted" in offshore_text and not offshore_denied
    if offshore_text and (
        (contract.offshore_permitted and not offshore_allowed)
        or (not contract.offshore_permitted and not offshore_denied)
    ):
        contradictions.append("offshore_permitted conflicts with offshore_delivery evidence")

    approval_not_required = (
        "no additional customer approval" in approval_text or "not required" in approval_text
    )
    approval_required = "required" in approval_text and not approval_not_required
    if approval_text and (
        (contract.customer_approval_required and not approval_required)
        or (not contract.customer_approval_required and not approval_not_required)
    ):
        contradictions.append(
            "customer_approval_required conflicts with customer_approval evidence"
        )

    residency_absent = "no special data residency restriction" in residency_text
    recorded_restriction = (contract.data_residency_restriction or "").lower()
    residency_supported = bool(recorded_restriction) and recorded_restriction in residency_text
    if residency_text and (
        (bool(recorded_restriction) and not residency_supported)
        or (not recorded_restriction and not residency_absent)
    ):
        contradictions.append(
            "data_residency_restriction conflicts with data_residency evidence"
        )
    return contradictions


def _combined_text(clauses: list[ContractClause]) -> str:
    return " ".join(clause.clause_text.lower() for clause in clauses)
