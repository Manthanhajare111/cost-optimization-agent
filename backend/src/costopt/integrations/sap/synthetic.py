"""Deterministic SAP-shaped fixtures derived from CostOpt's canonical synthetic data."""

from __future__ import annotations

import csv
import json
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any

from costopt.config import settings
from costopt.integrations.sap.ingestion import ingest_sap_samples
from costopt.integrations.sap.models import SapImportSummary
from costopt.observability.logging import get_logger


logger = get_logger(__name__)
_SUPPORTED_FOLDERS = {
    "fieldglass/worker",
    "fieldglass/business_unit",
    "ariba/purchase_orders",
    "ariba/contract_workspace",
}
_FIRST_NAMES = (
    "Aarav",
    "Aisha",
    "Amelia",
    "Daniel",
    "Elena",
    "Felix",
    "Ishaan",
    "Leila",
    "Maya",
    "Noah",
    "Priya",
    "Rafael",
)
_LAST_NAMES = (
    "Bauer",
    "Costa",
    "Gupta",
    "Iyer",
    "Khan",
    "Martin",
    "Mehta",
    "Nowak",
    "Patel",
    "Schmidt",
    "Silva",
    "Wilson",
)
_CITY_BY_COUNTRY = {
    "Australia": "Sydney",
    "Brazil": "Sao Paulo",
    "Canada": "Toronto",
    "Czech Republic": "Prague",
    "Egypt": "Cairo",
    "Germany": "Frankfurt",
    "Hungary": "Budapest",
    "India": "Bengaluru",
    "Malaysia": "Kuala Lumpur",
    "Mexico": "Monterrey",
    "Philippines": "Manila",
    "Poland": "Krakow",
    "Portugal": "Lisbon",
    "Romania": "Bucharest",
    "Singapore": "Singapore",
    "South Africa": "Cape Town",
    "Spain": "Madrid",
    "United Arab Emirates": "Dubai",
    "United Kingdom": "London",
    "United States": "New York",
}


def ingest_synthetic_sap_data(source: str = "all") -> SapImportSummary:
    """Generate and ingest SAP-shaped demo payloads without retaining generated files."""
    requested_source = source.casefold().strip()
    if requested_source not in {"all", "fieldglass", "ariba"}:
        raise ValueError("source must be one of: all, fieldglass, ariba")

    inventory = _trusted_inventory(requested_source)
    documents = _build_documents(settings.synthetic_data_dir / "tables")
    allowed_folders = {row["relative_folder"] for row in inventory}
    selected_documents = [item for item in documents if item[0] in allowed_folders]

    logger.info(
        "Synthetic SAP fixture generation started",
        extra={
            "event": "sap_synthetic_fixture_generation_started",
            "requested_source": requested_source,
            "document_count": len(selected_documents),
        },
    )
    settings.runtime_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="costopt-sap-synthetic-",
        dir=settings.runtime_dir,
    ) as temporary_directory:
        root = Path(temporary_directory)
        _write_inventory(root / "api_inventory.csv", inventory)
        for folder, filename, payload in selected_documents:
            path = root / folder / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        result = ingest_sap_samples(
            source=requested_source,
            samples_dir=root,
            data_origin="synthetic_fixture",
        )

    logger.info(
        "Synthetic SAP fixture generation completed",
        extra={
            "event": "sap_synthetic_fixture_generation_completed",
            "requested_source": requested_source,
            "document_count": len(selected_documents),
            "staged_record_counts": result.staged_record_counts,
        },
    )
    return result


def _trusted_inventory(requested_source: str) -> list[dict[str, str]]:
    inventory_path = settings.sap_source_samples_dir / "api_inventory.csv"
    with inventory_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return [
        row
        for row in rows
        if row["relative_folder"] in _SUPPORTED_FOLDERS
        and (
            requested_source == "all"
            or row["source_system"].casefold() == requested_source
        )
    ]


def _write_inventory(path: Path, rows: list[dict[str, str]]) -> None:
    if not rows:
        raise ValueError("No trusted SAP inventory rows are available for synthetic fixtures.")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _build_documents(tables_dir: Path) -> list[tuple[str, str, Any]]:
    resources = _load_table(tables_dir, "resources")
    locations = _load_table(tables_dir, "locations")
    suppliers = _load_table(tables_dir, "suppliers")
    purchase_orders = _load_table(tables_dir, "purchase_orders")
    contracts = _load_table(tables_dir, "contracts")

    location_by_id = {row["location_id"]: row for row in locations}
    supplier_by_id = {row["supplier_id"]: row for row in suppliers}
    supplier_sequence = {
        row["supplier_id"]: index for index, row in enumerate(suppliers, start=1)
    }

    documents: list[tuple[str, str, Any]] = []
    for index, resource in enumerate(resources, start=1):
        location = location_by_id[resource["current_location_id"]]
        resource_id = str(resource["resource_id"])
        documents.append(
            (
                "fieldglass/worker",
                f"response.synthetic.{resource_id}.sample.json",
                {
                    "firstName": _FIRST_NAMES[(index - 1) % len(_FIRST_NAMES)],
                    "lastName": _LAST_NAMES[(index * 5 - 1) % len(_LAST_NAMES)],
                    "email": f"{resource_id}@workers.costopt.example.invalid",
                    "city": _CITY_BY_COUNTRY.get(str(location["country"]), "Delivery Centre"),
                    "stateProvince": str(location["region"]),
                    "country": location["country"],
                    "postalCode": f"{10000 + index:05d}",
                    "username": f"SYN-FG-{resource_id.upper()}",
                    "role": resource["role"],
                    "workerCustomFields": {
                        "costoptResourceId": resource_id,
                        "supplierId": resource["supplier_id"],
                        "squadId": resource["squad_id"],
                        "currentLocationId": resource["current_location_id"],
                        "skill": resource["skill"],
                        "currentRate": resource["current_rate"],
                        "piiAccess": resource["pii_access"],
                        "availability": resource["availability"],
                    },
                },
            )
        )

    business_units = [
        {
            "Code": "SYN-COSTOPT-GLOBAL",
            "Name": "CostOpt Global Delivery",
            "Parent Business Unit": None,
            "Legal Entity": "CostOpt Synthetic Enterprise",
            "Resource Coordinator Required Flag": "Yes",
            "Distributor Required Flag": "No",
        }
    ]
    for location in locations:
        business_units.append(
            {
                "Code": f"SYN-{str(location['location_id']).upper()}",
                "Name": f"{location['country']} Delivery Centre",
                "Parent Business Unit": "SYN-COSTOPT-GLOBAL",
                "Legal Entity": f"CostOpt {location['country']} Synthetic",
                "Resource Coordinator Required Flag": "Yes",
                "Distributor Required Flag": "Yes" if location["is_offshore"] else "No",
            }
        )
    documents.append(
        (
            "fieldglass/business_unit",
            "response.synthetic.sample.json",
            {
                "headers": {
                    "Type": "Business Unit Upload",
                    "Transaction": "Synthetic",
                    "Comments": "Derived from CostOpt synthetic locations",
                },
                "data": business_units,
            },
        )
    )

    ariba_orders = []
    spend_by_supplier: defaultdict[str, float] = defaultdict(float)
    for index, order in enumerate(purchase_orders, start=1):
        supplier = supplier_by_id[order["supplier_id"]]
        supplier_number = supplier_sequence[order["supplier_id"]]
        spend_by_supplier[order["supplier_id"]] += float(order["amount"])
        ariba_orders.append(
            {
                "documentNumber": f"SYN-ARIBA-{str(order['po_id']).upper()}",
                "supplierName": supplier["name"],
                "supplierANID": f"AN-SYN-{supplier_number:08d}",
                "vendorId": order["supplier_id"],
                "buyerANID": "AN-SYN-COSTOPT-BUYER",
                "customerName": "CostOpt Synthetic Enterprise",
                "poAmount": {
                    "amount": order["amount"],
                    "currencyCode": order["currency"],
                },
                "status": ("CONFIRMED", "CHANGED", "NEW")[index % 3],
                "documentStatus": "CLOSED" if index % 10 == 0 else "OPEN",
                "orderDate": order["order_date"],
                "payloadId": f"SYN-PAYLOAD-PO-{index:04d}",
                "businessUnit": order["business_unit"],
                "categoryId": order["category_id"],
            }
        )
    documents.append(
        (
            "ariba/purchase_orders",
            "response.synthetic.sample.json",
            {
                "content": ariba_orders,
                "count": len(ariba_orders),
                "limit": len(ariba_orders),
                "offset": 0,
                "firstPage": True,
                "lastPage": True,
            },
        )
    )

    workspaces = []
    for index, contract in enumerate(contracts, start=1):
        supplier = supplier_by_id[contract["supplier_id"]]
        supplier_number = supplier_sequence[contract["supplier_id"]]
        is_active = index % 5 != 0
        restriction = contract["data_residency_restriction"] or "No additional restriction recorded."
        workspaces.append(
            {
                "contractId": f"SYN-ARIBA-{str(contract['contract_id']).upper()}",
                "title": f"{supplier['name']} - {contract['contract_type']}",
                "description": f"Synthetic contract workspace. {restriction}",
                "contractStatus": "Published" if is_active else "Draft",
                "effectiveDate": "2026-01-01T00:00:00Z",
                "expirationDate": "2027-12-31T23:59:59Z",
                "contractAmount": {
                    "amount": round(spend_by_supplier[contract["supplier_id"]], 2),
                    "currency": "EUR",
                },
                "version": 1 + (index % 3),
                "owner": {"uniqueName": f"synthetic.contract.owner.{supplier_number:02d}"},
                "active": is_active,
                "lastModified": contract["created_at"],
                "supplierId": contract["supplier_id"],
                "offshorePermitted": contract["offshore_permitted"],
                "customerApprovalRequired": contract["customer_approval_required"],
            }
        )
    documents.append(
        (
            "ariba/contract_workspace",
            "response.synthetic.sample.json",
            {"value": workspaces, "count": len(workspaces), "start": 0},
        )
    )
    return documents


def _load_table(tables_dir: Path, table_name: str) -> list[dict[str, Any]]:
    path = tables_dir / f"{table_name}.json"
    if not path.is_file():
        raise FileNotFoundError(f"Synthetic source table not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"Synthetic source table must contain a JSON array: {path}")
    return payload
