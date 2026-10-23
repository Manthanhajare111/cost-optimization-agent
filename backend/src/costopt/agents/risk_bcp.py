"""Risk and business-continuity evidence coverage component."""

from costopt.agents.base import AgentExecution
from costopt.agents.component import build_component_execution
from costopt.models.domain import AgentFinding, ScenarioContext
from costopt.observability.logging import get_logger


logger = get_logger(__name__)
RISK_CONTROLS = {
    "bcp": ("bcp", "business continuity", "disaster recovery"),
    "sla": ("sla", "service level", "availability"),
    "certification": ("soc2", "soc 2", "iso 27001", "certification"),
    "risk_penalty": ("penalty", "service credit", "risk penalty"),
}


class RiskBCPAgent:
    def analyze(self, context: ScenarioContext) -> tuple[AgentFinding, AgentExecution]:
        logger.info(
            "Risk and BCP agent started",
            extra={"event": "risk_bcp_agent_started", "scenario_id": context.scenario_id},
        )
        matched: dict[str, list[str]] = {control: [] for control in RISK_CONTROLS}
        for clause in context.clauses:
            haystack = f"{clause.clause_type} {clause.clause_text}".casefold()
            for control, keywords in RISK_CONTROLS.items():
                if any(keyword in haystack for keyword in keywords):
                    matched[control].append(clause.clause_id)
        missing = [control for control, evidence in matched.items() if not evidence]
        evidence_ids = sorted({item for evidence in matched.values() for item in evidence})
        finding = AgentFinding(
            status="limited" if missing else "ready",
            summary=(
                f"Found evidence for {len(RISK_CONTROLS) - len(missing)} of "
                f"{len(RISK_CONTROLS)} supplier risk and continuity controls."
            ),
            metrics={
                "controls_checked": len(RISK_CONTROLS),
                "controls_with_evidence": len(RISK_CONTROLS) - len(missing),
                "risk_evidence_coverage_pct": round(
                    100 * (len(RISK_CONTROLS) - len(missing)) / len(RISK_CONTROLS), 2
                ),
            },
            data_gaps=[f"No verified {control.replace('_', ' ')} evidence." for control in missing],
            recommendations=(
                ["Connect Ariba SPM risk, SLA, certification, and BCP evidence before execution."]
                if missing
                else ["Carry verified risk controls into optimization constraints."]
            ),
        )
        execution = build_component_execution(
            "risk_bcp", finding, "risk_bcp_evidence_checker", evidence_ids
        )
        logger.info(
            "Risk and BCP agent completed",
            extra={
                "event": "risk_bcp_agent_completed",
                "scenario_id": context.scenario_id,
                "controls_with_evidence": len(RISK_CONTROLS) - len(missing),
            },
        )
        return finding, execution
