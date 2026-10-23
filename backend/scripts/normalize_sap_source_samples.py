"""Normalize, sanitize, and catalogue manually captured SAP API samples."""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SAMPLES_ROOT = Path(__file__).resolve().parents[1] / "data" / "source_samples" / "sap"


@dataclass(frozen=True)
class ApiDefinition:
    source_system: str
    folder: str
    ppt_name: str
    default_method: str = "GET"


API_DEFINITIONS = [
    ApiDefinition("Fieldglass", "fieldglass/job_posting", "Job Posting API"),
    ApiDefinition("Fieldglass", "fieldglass/worker", "Worker API"),
    ApiDefinition("Fieldglass", "fieldglass/work_order", "Work Order API"),
    ApiDefinition("Fieldglass", "fieldglass/rate_card", "Rate Card/Rate Grid API"),
    ApiDefinition("Fieldglass", "fieldglass/supplier", "Supplier API"),
    ApiDefinition("Fieldglass", "fieldglass/sow", "SOW API"),
    ApiDefinition("Fieldglass", "fieldglass/timesheet", "Timesheet API"),
    ApiDefinition("Fieldglass", "fieldglass/expense_sheet", "Expense Sheet API"),
    ApiDefinition("Fieldglass", "fieldglass/site", "Site API"),
    ApiDefinition("Fieldglass", "fieldglass/business_unit", "Business Unit API"),
    ApiDefinition("Fieldglass", "fieldglass/site_business_unit", "Site/Business Unit API"),
    ApiDefinition("Fieldglass", "fieldglass/activity_audit", "Activity/Audit API"),
    ApiDefinition("Fieldglass", "fieldglass/analytics_odata", "Analytics OData API"),
    ApiDefinition("Ariba", "ariba/supplier_data", "Supplier Data API"),
    ApiDefinition("Ariba", "ariba/purchase_orders", "Purchase Orders API"),
    ApiDefinition("Ariba", "ariba/contract_workspace", "Contract Workspace API"),
    ApiDefinition("Ariba", "ariba/sourcing_project", "Sourcing Project API"),
    ApiDefinition("Ariba", "ariba/supplier_risk", "Supplier Risk API"),
    ApiDefinition("Ariba", "ariba/event_management", "Event Management API"),
    ApiDefinition("Ariba", "ariba/catalog_content", "Catalog Content API"),
    ApiDefinition("Ariba", "ariba/operational_reporting", "Operational Reporting API"),
    ApiDefinition("Ariba", "ariba/analytical_reporting", "Analytical Reporting API"),
    ApiDefinition("Ariba", "ariba/supplier_invite", "Supplier Invite API", "POST"),
    ApiDefinition("Ariba", "ariba/supplier_profile", "Supplier Profile API"),
    ApiDefinition("Ariba", "ariba/master_data_retrieval", "Master Data Retrieval API"),
    ApiDefinition("Ariba", "ariba/internal_catalog_shop", "Internal Catalog Shop API"),
    ApiDefinition("Ariba", "ariba/order_change_request", "Order Change Request API"),
    ApiDefinition("Ariba", "ariba/ship_notice", "Ship Notice API"),
    ApiDefinition("Ariba", "ariba/proof_of_service", "Proof of Service API"),
    ApiDefinition("Ariba", "ariba/planning_collaboration", "Planning Collaboration API"),
    ApiDefinition("Ariba", "ariba/risk_exposure", "Risk Exposure API"),
    ApiDefinition("Ariba", "ariba/transaction_monitoring", "Transaction Monitoring API"),
]


ERROR_NOTES = {
    "fieldglass/activity_audit": "Captured response is 403 Forbidden; successful payload pending.",
    "fieldglass/timesheet": "Captured HTML reports failed authentication; successful JSON pending.",
    "fieldglass/expense_sheet": "Captured response reports an unavailable SAP proxy.",
    "fieldglass/job_posting": "Captured response reports an unconfigured sandbox procedure.",
    "fieldglass/work_order": (
        "Captured payload contains plant/equipment maintenance orders rather than "
        "Fieldglass workforce assignments; classification pending."
    ),
    "fieldglass/rate_card": "Captured response reports an unavailable SAP proxy.",
    "fieldglass/sow": "Captured response reports an unavailable SAP proxy.",
    "fieldglass/supplier": "Captured payload belonged to Ariba Supplier Data and was reclassified.",
    "ariba/catalog_content": "Captured response reports an unavailable SAP proxy.",
    "ariba/supplier_data": (
        "Captured payload contains schema placeholder values rather than a business record."
    ),
    "ariba/transaction_monitoring": "Captured response is HTTP 400; request now uses one filter.",
}


def main() -> None:
    SAMPLES_ROOT.mkdir(parents=True, exist_ok=True)
    for definition in API_DEFINITIONS:
        _scaffold_api(definition)
    sanitized_files, trimmed_records = _sanitize_samples()
    _write_inventory()
    print(
        f"Normalized {len(API_DEFINITIONS)} APIs; sanitized {sanitized_files} sample files; "
        f"removed {trimmed_records} excess records from the representative fixture."
    )


def _scaffold_api(definition: ApiDefinition) -> None:
    api_dir = SAMPLES_ROOT / definition.folder
    api_dir.mkdir(parents=True, exist_ok=True)
    request_path = api_dir / "request.json"
    if not request_path.exists():
        request_path.write_text(
            json.dumps(
                {
                    "method": definition.default_method,
                    "endpoint": "",
                    "query_parameters": {},
                    "headers": {"Accept": "application/json"},
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    if not any(api_dir.glob("openapi.*")):
        (api_dir / "openapi.pending.md").write_text(
            "The SAP OpenAPI/Swagger specification has not yet been captured. Replace this "
            "marker with `openapi.json` or `openapi.yaml` when an approved specification "
            "is available.\n",
            encoding="utf-8",
        )

    response_status = _response_status(api_dir)
    extra_note = ERROR_NOTES.get(definition.folder, "")
    write_warning = (
        "\n- Safety: This is a write API. Do not execute it without explicit authorization."
        if definition.default_method != "GET"
        else ""
    )
    (api_dir / "notes.md").write_text(
        f"# {definition.ppt_name}\n\n"
        f"- Source system: {definition.source_system}\n"
        f"- Official SAP API name: Not yet verified\n"
        f"- API version: Not captured\n"
        f"- Documentation URL: Not captured\n"
        f"- OpenAPI specification: Pending\n"
        f"- Response status: {response_status}\n"
        f"- Collection note: {extra_note or 'No collection error recorded.'}"
        f"{write_warning}\n\n"
        "Never store credentials, authorization headers, cookies, tenant secrets, or "
        "production PII in this folder.\n",
        encoding="utf-8",
    )


def _response_status(api_dir: Path) -> str:
    if (api_dir / "response.sample.json").exists():
        return "Sample captured"
    if any(api_dir.glob("response.error.*")):
        return "Error captured; successful response pending"
    if any(api_dir.glob("response.misfiled.*")):
        return "Misfiled response preserved; correct response pending"
    if any(api_dir.glob("response.unverified.*")):
        return "Unverified response preserved; correct response pending"
    if any(api_dir.glob("response.schema.*")):
        return "Schema example preserved; business response pending"
    return "Not captured"


def _sanitize_samples() -> tuple[int, int]:
    replacements: dict[tuple[str, str], str] = {}
    sanitized_files = 0
    trimmed_records = 0
    for path in sorted(SAMPLES_ROOT.rglob("*.sample.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload, removed = _trim_representative_payload(path, payload)
        trimmed_records += removed
        sanitized = _sanitize_value(payload, replacements)
        path.write_text(
            json.dumps(sanitized, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        sanitized_files += 1
    return sanitized_files, trimmed_records


def _trim_representative_payload(path: Path, payload: Any) -> tuple[Any, int]:
    """Keep source shapes intact while avoiding large bulk exports in versioned fixtures."""
    relative = path.relative_to(SAMPLES_ROOT).as_posix()
    if relative == "ariba/planning_collaboration/response.sample.json":
        content = payload.get("content") if isinstance(payload, dict) else None
        if isinstance(content, list) and len(content) > 2:
            removed = len(content) - 2
            payload["content"] = content[:2]
            return payload, removed
    if relative == "fieldglass/business_unit/response.sample.json":
        data = payload.get("data") if isinstance(payload, dict) else None
        if isinstance(data, list) and len(data) > 10:
            removed = len(data) - 10
            payload["data"] = data[:10]
            return payload, removed
    if relative == "fieldglass/work_order/response.sample.json":
        if isinstance(payload, list) and len(payload) > 10:
            removed = len(payload) - 10
            return payload[:10], removed
    if relative == "ariba/purchase_orders/response.sample.json":
        content = payload.get("content") if isinstance(payload, dict) else None
        if isinstance(content, list):
            unique: list[Any] = []
            seen: set[tuple[object, object]] = set()
            for item in content:
                if not isinstance(item, dict):
                    unique.append(item)
                    continue
                identity = (item.get("documentNumber"), item.get("payloadId"))
                if identity in seen:
                    continue
                seen.add(identity)
                unique.append(item)
            payload["content"] = unique[:10]
            return payload, len(content) - len(payload["content"])
    return payload, 0


def _sanitize_value(
    value: Any,
    replacements: dict[tuple[str, str], str],
    key: str = "",
) -> Any:
    if isinstance(value, dict):
        return {
            item_key: _sanitize_value(item_value, replacements, item_key)
            for item_key, item_value in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_value(item, replacements, key) for item in value]
    if not isinstance(value, str) or not value:
        return value

    category = _sensitive_category(key)
    if category is None:
        return value
    replacement_key = (category, value)
    if replacement_key not in replacements:
        index = 1 + sum(item_category == category for item_category, _ in replacements)
        replacements[replacement_key] = _replacement(category, index)
    return replacements[replacement_key]


def _sensitive_category(key: str) -> str | None:
    normalized = re.sub(r"[^a-z0-9]", "", key.casefold())
    if "email" in normalized:
        return "email"
    if any(token in normalized for token in ("phone", "mobile", "fax")):
        return "phone"
    if normalized in {
        "firstname",
        "lastname",
        "fullname",
        "contactname",
        "workername",
        "contactperson",
    }:
        return "name"
    if any(token in normalized for token in ("street", "addressline")):
        return "address"
    if normalized in {"postalcode", "postcode", "zipcode"}:
        return "postal_code"
    return None


def _replacement(category: str, index: int) -> str:
    if category == "email":
        return f"synthetic.email.{index:03d}@example.invalid"
    if category == "phone":
        return f"+100000{index:05d}"
    if category == "address":
        return f"Synthetic Address {index:03d}"
    if category == "postal_code":
        return f"{index:05d}"
    return f"Synthetic Name {index:03d}"


def _write_inventory() -> None:
    inventory_path = SAMPLES_ROOT / "api_inventory.csv"
    with inventory_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "source_system",
                "api_key",
                "relative_folder",
                "ppt_name",
                "official_api_name",
                "version",
                "method",
                "endpoint",
                "documentation_url",
                "http_status",
                "capture_status",
                "pagination",
                "data_classification",
                "notes",
            ],
        )
        writer.writeheader()
        for definition in API_DEFINITIONS:
            api_dir = SAMPLES_ROOT / definition.folder
            request = json.loads((api_dir / "request.json").read_text(encoding="utf-8"))
            writer.writerow(
                {
                    "source_system": definition.source_system,
                    "api_key": Path(definition.folder).name,
                    "relative_folder": definition.folder,
                    "ppt_name": definition.ppt_name,
                    "official_api_name": "NOT_VERIFIED",
                    "version": "NOT_CAPTURED",
                    "method": request.get("method", definition.default_method),
                    "endpoint": request.get("endpoint", ""),
                    "documentation_url": "NOT_CAPTURED",
                    "http_status": _known_http_status(definition.folder),
                    "capture_status": _response_status(api_dir),
                    "pagination": _pagination_status(api_dir),
                    "data_classification": "sanitized_sap_sample",
                    "notes": ERROR_NOTES.get(definition.folder, ""),
                }
            )


def _pagination_status(api_dir: Path) -> str:
    response_path = api_dir / "response.sample.json"
    if not response_path.exists():
        return "NOT_CAPTURED"
    payload = json.loads(response_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return "NOT_PRESENT_IN_SAMPLE"
    pagination_keys = {
        "count",
        "start",
        "content",
        "firstPage",
        "lastPage",
        "limit",
        "offset",
        "nextPage",
    }
    return (
        "PRESENT_IN_SAMPLE"
        if pagination_keys.intersection(payload)
        else "NOT_PRESENT_IN_SAMPLE"
    )


def _known_http_status(folder: str) -> str:
    return {
        "fieldglass/activity_audit": "403",
        "ariba/transaction_monitoring": "400",
    }.get(folder, "NOT_CAPTURED")


if __name__ == "__main__":
    main()
