import csv
import json

from scripts.normalize_sap_source_samples import API_DEFINITIONS, SAMPLES_ROOT


def test_sap_api_inventory_and_folder_contract_are_complete():
    with (SAMPLES_ROOT / "api_inventory.csv").open(encoding="utf-8", newline="") as handle:
        inventory = list(csv.DictReader(handle))

    assert len(inventory) == len(API_DEFINITIONS) == 32
    assert {(row["source_system"], row["ppt_name"]) for row in inventory} == {
        (definition.source_system, definition.ppt_name) for definition in API_DEFINITIONS
    }
    for definition in API_DEFINITIONS:
        api_dir = SAMPLES_ROOT / definition.folder
        assert api_dir.is_dir()
        assert (api_dir / "request.json").is_file()
        assert (api_dir / "notes.md").is_file()
        assert list(api_dir.glob("openapi.*"))


def test_sap_request_metadata_is_structured_and_contains_no_secrets():
    forbidden_headers = {"authorization", "apikey", "api-key", "x-api-key", "cookie"}
    for definition in API_DEFINITIONS:
        request_path = SAMPLES_ROOT / definition.folder / "request.json"
        request = json.loads(request_path.read_text(encoding="utf-8"))

        assert request["method"] in {"GET", "POST"}
        assert isinstance(request["endpoint"], str)
        assert "?" not in request["endpoint"]
        assert isinstance(request["query_parameters"], dict)
        assert not forbidden_headers.intersection(key.casefold() for key in request["headers"])


def test_all_sap_json_samples_are_valid_and_representative_in_size():
    sample_paths = list(SAMPLES_ROOT.rglob("*.sample.json"))
    assert sample_paths
    for path in sample_paths:
        json.loads(path.read_text(encoding="utf-8"))
        assert path.stat().st_size < 750_000

    planning = json.loads(
        (SAMPLES_ROOT / "ariba/planning_collaboration/response.sample.json").read_text(
            encoding="utf-8"
        )
    )
    work_orders = json.loads(
        (SAMPLES_ROOT / "fieldglass/work_order/response.unverified.sample.json").read_text(
            encoding="utf-8"
        )
    )
    business_units = json.loads(
        (SAMPLES_ROOT / "fieldglass/business_unit/response.sample.json").read_text(
            encoding="utf-8"
        )
    )

    assert len(planning["content"]) <= 2
    assert len(work_orders) <= 10
    assert len(business_units["data"]) <= 10


def test_failed_and_misfiled_responses_are_not_labelled_as_successful_samples():
    pending_folders = {
        "fieldglass/activity_audit",
        "fieldglass/timesheet",
        "fieldglass/expense_sheet",
        "fieldglass/job_posting",
        "fieldglass/work_order",
        "fieldglass/rate_card",
        "fieldglass/sow",
        "fieldglass/supplier",
        "ariba/catalog_content",
        "ariba/supplier_data",
        "ariba/transaction_monitoring",
    }
    for folder in pending_folders:
        assert not (SAMPLES_ROOT / folder / "response.sample.json").exists()
