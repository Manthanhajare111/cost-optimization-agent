import json

import pytest

from costopt.llm.decision_brief import GeminiDecisionBriefClient, build_deterministic_brief
from costopt.models.domain import ScenarioAnalysisRequest
from costopt.pipeline.scenario_analysis import analyze_scenario
from costopt.storage.recommendation_store import save_recommendation


def test_deterministic_brief_uses_verified_analysis(isolated_db):
    record = save_recommendation(analyze_scenario(ScenarioAnalysisRequest(scenario_name="germany-philippines")))

    brief = build_deterministic_brief(record)

    assert brief.provider == "deterministic_fallback"
    assert brief.used_fallback is True
    assert brief.compliance_assessment == "allowed_with_approval"
    assert brief.citations == record.compliance.citations
    assert "estimat" in brief.executive_summary.lower()


class _FakeModels:
    def __init__(self, content: str):
        self._content = content

    def generate_content(self, **_kwargs):
        return type("Response", (), {"text": self._content})()


class _FakeGemini:
    def __init__(self, content: str):
        self.models = _FakeModels(content)


def test_gemini_client_validates_structured_response_and_citations(isolated_db):
    record = save_recommendation(analyze_scenario(ScenarioAnalysisRequest(scenario_name="germany-philippines")))
    payload = {
        "executive_summary": "Estimated savings justify a controlled move.",
        "recommended_action": "Seek written approval before moving eligible roles.",
        "compliance_assessment": "allowed_with_approval",
        "key_considerations": ["Customer approval is required."],
        "citation_ids": [record.compliance.citations[0].clause_id],
    }
    client = GeminiDecisionBriefClient(
        api_key="test-key",
        model="test-model",
        timeout_seconds=1,
        client=_FakeGemini(json.dumps(payload)),
    )

    brief = client.explain(record)

    assert brief.provider == "llm"
    assert brief.used_fallback is False
    assert brief.citations == [record.compliance.citations[0]]
    assert brief.recommended_action == record.recommendation


def test_llm_brief_cannot_override_verified_compliance(isolated_db):
    record = save_recommendation(analyze_scenario(ScenarioAnalysisRequest(scenario_name="germany-philippines")))
    payload = {
        "executive_summary": "Proceed immediately.",
        "recommended_action": "Move all roles without approval.",
        "compliance_assessment": "allowed",
        "key_considerations": [],
        "citation_ids": [record.compliance.citations[0].clause_id],
    }
    client = GeminiDecisionBriefClient(
        api_key="test-key",
        model="test-model",
        timeout_seconds=1,
        client=_FakeGemini(json.dumps(payload)),
    )

    with pytest.raises(ValueError, match="conflicts with verified analysis"):
        client.explain(record)
