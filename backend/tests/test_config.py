from costopt.config import Settings
from costopt.prompts.registry import load_system_prompt


def test_agent_llm_profiles_are_addressable_and_disabled_by_default():
    settings = Settings(_env_file=None)

    profiles = settings.agent_llm_profiles

    assert set(profiles) == {
        "planner",
        "retriever",
        "contract",
        "tail_spend",
        "risk_bcp",
        "timezone_mitigation",
        "financial_working_capital",
        "optimization",
        "reporting",
        "approval",
    }
    assert all(profile.enabled is False for profile in profiles.values())
    assert profiles["contract"].prompt_key == "compliance_evidence_review_v1"


def test_agent_llm_profile_requires_global_and_agent_enablement():
    settings = Settings(
        _env_file=None,
        agent_llm_enabled=True,
        compliance_agent_llm_enabled=True,
        compliance_agent_llm_model="configured-model",
    )

    profile = settings.get_agent_llm_profile("contract")

    assert profile.enabled is True
    assert profile.model == "configured-model"
    assert "Do not invent clauses" in load_system_prompt(profile.prompt_key)
