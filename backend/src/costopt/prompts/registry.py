from pathlib import Path


PROMPT_DIRECTORY = Path(__file__).resolve().parent
PROMPT_FILES = {
    "data_validation_review_v1": "data_validation_review_v1.md",
    "compliance_evidence_review_v1": "compliance_analyst_v1.md",
    "optimization_explanation_v1": "optimization_analyst_v1.md",
    "orchestrator_decision_brief_v1": "recommendation_orchestrator_v1.md",
}


def load_system_prompt(prompt_key: str) -> str:
    try:
        filename = PROMPT_FILES[prompt_key]
    except KeyError as exc:
        raise ValueError(f"Unknown CostOpt prompt key: {prompt_key}") from exc
    return (PROMPT_DIRECTORY / filename).read_text(encoding="utf-8").strip()
