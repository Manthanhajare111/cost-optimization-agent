"""Local evidence retriever with a future HANA Vector boundary."""

from collections import Counter

from costopt.agents.base import AgentExecution
from costopt.agents.component import build_component_execution
from costopt.models.domain import AgentFinding, ScenarioContext
from costopt.observability.logging import get_logger


logger = get_logger(__name__)
REQUIRED_CONTRACT_EVIDENCE = {
    "offshore_delivery",
    "data_residency",
    "customer_approval",
}


class RetrieverAgent:
    def retrieve(self, context: ScenarioContext) -> tuple[AgentFinding, AgentExecution]:
        logger.info(
            "Retriever agent started",
            extra={"event": "retriever_agent_started", "scenario_id": context.scenario_id},
        )
        clause_counts = Counter(clause.clause_type for clause in context.clauses)
        present_types = set(clause_counts)
        missing_types = sorted(REQUIRED_CONTRACT_EVIDENCE - present_types)
        citation_ids = [clause.clause_id for clause in context.clauses]
        finding = AgentFinding(
            status="limited" if missing_types else "ready",
            summary=(
                f"Retrieved {len(context.clauses)} structured clauses across "
                f"{len(context.contracts)} supplier contract(s) from the local evidence store."
            ),
            metrics={
                "retrieval_backend": "local_structured_evidence",
                "contract_count": len(context.contracts),
                "clause_count": len(context.clauses),
                "required_evidence_coverage_pct": round(
                    100 * len(REQUIRED_CONTRACT_EVIDENCE & present_types)
                    / len(REQUIRED_CONTRACT_EVIDENCE),
                    2,
                ),
            },
            data_gaps=[f"Missing contract evidence type: {item}" for item in missing_types],
            recommendations=(
                ["Load the missing clause types before treating compliance as complete."]
                if missing_types
                else ["Pass retrieved evidence to the Contract Agent."]
            ),
        )
        execution = build_component_execution(
            "retriever", finding, "local_contract_evidence_retriever", citation_ids
        )
        logger.info(
            "Retriever agent completed",
            extra={
                "event": "retriever_agent_completed",
                "scenario_id": context.scenario_id,
                "clause_count": len(context.clauses),
                "missing_evidence_type_count": len(missing_types),
            },
        )
        return finding, execution
