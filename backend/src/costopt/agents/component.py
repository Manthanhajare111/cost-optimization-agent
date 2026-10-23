"""Shared helpers for deterministic specialist-agent components."""

from costopt.agents.base import AgentExecution
from costopt.config import AgentName
from costopt.models.domain import AgentFinding, AgentNarrative, AgentToolTrace


def build_component_execution(
    agent: AgentName,
    finding: AgentFinding,
    tool_name: str,
    evidence_ids: list[str] | None = None,
) -> AgentExecution:
    """Expose a verified finding through the common agent execution contract."""
    citations = evidence_ids or []
    narrative = AgentNarrative(
        summary=finding.summary,
        key_considerations=[
            f"{key.replace('_', ' ').title()}: {value}"
            for key, value in finding.metrics.items()
        ],
        citation_ids=citations,
        risks=[f"Data gap: {gap}" for gap in finding.data_gaps],
        next_actions=finding.recommendations,
    )
    return AgentExecution(
        narrative=narrative,
        used_fallback=False,
        tool_traces=[
            AgentToolTrace(
                tool_name=tool_name,
                status="completed",
                summary=finding.summary,
                evidence_ids=citations,
            )
        ],
    )
