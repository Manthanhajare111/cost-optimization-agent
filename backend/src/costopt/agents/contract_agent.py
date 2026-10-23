"""Target-architecture Contract Agent backed by the proven compliance policy."""

from costopt.agents.base import AgentExecution
from costopt.agents.compliance import ComplianceAssessment
from costopt.agents.compliance_analyst import ComplianceAnalystAgent
from costopt.models.domain import ContractClause, ContractRecord
from costopt.observability.logging import get_logger


logger = get_logger(__name__)


class ContractAgent:
    def __init__(self) -> None:
        self._delegate = ComplianceAnalystAgent()

    def analyze(
        self,
        contracts: ContractRecord | list[ContractRecord],
        clauses: list[ContractClause],
        target_is_offshore: bool = True,
    ) -> tuple[ComplianceAssessment, AgentExecution]:
        logger.info("Contract agent started", extra={"event": "contract_agent_started"})
        result = self._delegate.analyze(contracts, clauses, target_is_offshore)
        logger.info(
            "Contract agent completed",
            extra={"event": "contract_agent_completed", "outcome": result[0].outcome},
        )
        return result
