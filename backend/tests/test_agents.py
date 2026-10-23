import json

from costopt.agents.base import StructuredCostOptAgent
from costopt.agents.compliance_analyst import ComplianceAnalystAgent
from costopt.agents.optimization_analyst import OptimizationAnalystAgent
from costopt.agents.orchestrator_agent import RecommendationOrchestratorAgent
from costopt.config import AgentLLMProfile, settings
from costopt.models.domain import AgentNarrative
from costopt.prompts.registry import load_system_prompt
from costopt.storage.repositories import load_scenario_context


def test_compliance_agent_uses_deterministic_policy_and_fallback(isolated_db):
    context = load_scenario_context("germany-india")

    assessment, execution = ComplianceAnalystAgent().analyze(
        context.contracts,
        context.clauses,
    )

    assert assessment.outcome == "allowed_with_approval"
    assert execution.used_fallback is True
    assert execution.narrative.citation_ids


def test_optimization_and_orchestrator_agents_use_verified_outputs(isolated_db):
    context = load_scenario_context("germany-india")
    compliance, compliance_execution = ComplianceAnalystAgent().analyze(
        context.contracts,
        context.clauses,
    )
    recommendation, optimization_execution = OptimizationAnalystAgent().analyze(
        context,
        compliance,
    )

    execution = RecommendationOrchestratorAgent().compose(
        recommendation,
        compliance_execution.narrative,
        optimization_execution.narrative,
    )

    assert recommendation.costs.annual_savings > 0
    assert execution.used_fallback is True
    assert "Savings are estimates" in execution.narrative.key_considerations[-1]


def test_structured_agent_sends_its_system_prompt_and_validates_json(monkeypatch):
    profile = AgentLLMProfile(
        agent="contract",
        enabled=True,
        provider="gemini",
        model="test-model",
        temperature=0,
        max_tokens=100,
        prompt_key="compliance_evidence_review_v1",
    )
    class FakeModels:
        def generate_content(self, **kwargs):
            assert load_system_prompt(profile.prompt_key) in kwargs["contents"]
            return type("Response", (), {"text": json.dumps({
                "summary": "Verified compliance summary.",
                "key_considerations": ["Use supplied evidence."],
                "citation_ids": ["clause-1"],
                "risks": ["Approval is still required."],
                "next_actions": ["Obtain approval."],
            })})()

    class FakeClient:
        models = FakeModels()

    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    agent = StructuredCostOptAgent(profile, client=FakeClient())

    execution = agent.explain(
        facts={"contract": "verified"},
        fallback=AgentNarrative(summary="fallback"),
        allowed_citation_ids={"clause-1"},
    )

    assert execution.used_fallback is False
    assert execution.narrative.summary == "Verified compliance summary."
