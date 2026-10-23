import json
import re
from pathlib import Path

from costopt.config import settings
from costopt.models.domain import (
    ContractScenarioSeed,
    GoldenExpectation,
    ReferenceData,
    WorkforceScenarioSeed,
)


SCENARIO_ALIASES = {
    "germany-philippines": "germany-to-philippines-right-shoring",
    "germany-to-philippines": "germany-to-philippines-right-shoring",
    "germany-philippines-right-shoring": "germany-to-philippines-right-shoring",
}


def _load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Seed file not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _slugify(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return SCENARIO_ALIASES.get(normalized, normalized)


def _scenario_prefix(scenario_name: str) -> str:
    prefix = _slugify(scenario_name)
    if prefix != scenario_name:
        return prefix
    return SCENARIO_ALIASES.get(scenario_name, prefix)


def load_reference_data() -> ReferenceData:
    path = settings.synthetic_data_dir / "workforce" / "reference-data.template.json"
    return ReferenceData.model_validate(_load_json(path))


def load_workforce_scenario(scenario_name: str) -> WorkforceScenarioSeed:
    prefix = _scenario_prefix(scenario_name)
    path = settings.synthetic_data_dir / "workforce" / f"{prefix}-squad.template.json"
    return WorkforceScenarioSeed.model_validate(_load_json(path))


def load_contract_constraints(scenario_name: str) -> ContractScenarioSeed:
    prefix = _scenario_prefix(scenario_name)
    path = settings.synthetic_data_dir / "workforce" / f"{prefix}-contract.template.json"
    payload = _load_json(path)

    document_name = payload.get("contract", {}).get("document_name")
    if document_name:
        payload["document_text"] = load_contract_document(document_name)

    return ContractScenarioSeed.model_validate(payload)


def load_golden_expectation(scenario_name: str) -> GoldenExpectation:
    prefix = _scenario_prefix(scenario_name)
    path = settings.synthetic_data_dir / "golden" / f"{prefix}.expected.json"
    return GoldenExpectation.model_validate(_load_json(path))


def load_contract_document(document_name: str) -> str:
    path = settings.document_dir / document_name
    if not path.exists():
        raise FileNotFoundError(f"Contract document not found: {path}")
    return path.read_text(encoding="utf-8")
