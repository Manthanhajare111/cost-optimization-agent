"""Canonical CostOpt agent catalogue aligned with the target architecture."""

from costopt.models.domain import AgentDefinition


AGENT_DEFINITIONS: tuple[AgentDefinition, ...] = (
    AgentDefinition(name="data_cleaning", display_name="Data Cleaning Agent",
                    responsibility="Validate uploaded workforce data, propose corrections, and require recorded approval before use.",
                    implementation_level="component"),
    AgentDefinition(name="data_validation", display_name="Data validation",
                    responsibility="Validate the workforce workbook and supporting documents, report missing information per SOW, and block incomplete recommendations.",
                    implementation_level="expanded"),
    AgentDefinition(
        name="planner",
        display_name="Planner Agent",
        responsibility="Build and validate the specialist execution plan for a scenario.",
        implementation_level="component",
    ),
    AgentDefinition(
        name="retriever",
        display_name="Retriever Agent",
        responsibility="Retrieve bounded contract evidence from the configured evidence store.",
        implementation_level="component",
    ),
    AgentDefinition(
        name="contract",
        display_name="Contract Agent",
        responsibility="Evaluate contractual movement, residency, and approval constraints.",
        implementation_level="expanded",
    ),
    AgentDefinition(
        name="tail_spend",
        display_name="Tail-Spend Agent",
        responsibility="Measure supplier concentration and target rate-card coverage.",
        implementation_level="component",
    ),
    AgentDefinition(
        name="risk_bcp",
        display_name="Risk and BCP Agent",
        responsibility="Check available supplier-risk, SLA, certification, and continuity evidence.",
        implementation_level="component",
    ),
    AgentDefinition(
        name="timezone_mitigation",
        display_name="Timezone and Mitigation Agent",
        responsibility="Check workforce skill, availability, utilization, and timezone evidence.",
        implementation_level="component",
    ),
    AgentDefinition(
        name="financial_working_capital",
        display_name="Financial and Working Capital Agent",
        responsibility="Quantify run-rate savings and report transition/payback data coverage.",
        implementation_level="component",
    ),
    AgentDefinition(
        name="optimization",
        display_name="Optimization Agent",
        responsibility="Select the lowest-cost compliant workforce allocation.",
        implementation_level="expanded",
    ),
    AgentDefinition(
        name="reporting",
        display_name="Reporting Agent",
        responsibility="Synthesize verified findings, citations, alternatives, and risks.",
        implementation_level="expanded",
    ),
    AgentDefinition(
        name="approval",
        display_name="Approval Agent",
        responsibility="Apply the material-decision gate and prepare the local approval package.",
        implementation_level="component",
    ),
)


def list_agent_definitions() -> list[AgentDefinition]:
    return [definition.model_copy(deep=True) for definition in AGENT_DEFINITIONS]
