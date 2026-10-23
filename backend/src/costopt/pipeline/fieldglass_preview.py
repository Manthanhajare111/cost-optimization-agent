"""Read-only, team-scoped Fieldglass-shaped previews from local demo data.

These endpoints are not a live SAP Fieldglass connection. Only workers are
used as a canonical workforce input; other entities are reference previews.
"""

from __future__ import annotations

from costopt.storage.repositories import load_scenario_context
from costopt.storage.sqlite import get_connection


ENTITIES = (
    {"name": "workers", "endpoint": "/api/v1/workforce/fieldglass/entities/workers", "enabled": True,
     "extraction_mode": "incremental", "delta_field": "lastModifiedDate", "page_size": 500},
    {"name": "timesheets", "endpoint": "/api/v1/workforce/fieldglass/entities/timesheets", "enabled": True,
     "extraction_mode": "incremental", "delta_field": "approvedDate", "page_size": 500},
    {"name": "work_orders", "endpoint": "/api/v1/workforce/fieldglass/entities/work_orders", "enabled": True,
     "extraction_mode": "full", "delta_field": None, "page_size": 500},
    {"name": "sow", "endpoint": "/api/v1/workforce/fieldglass/entities/sow", "enabled": True,
     "extraction_mode": "full", "delta_field": None, "page_size": 500},
    {"name": "invoices", "endpoint": "/api/v1/workforce/fieldglass/entities/invoices", "enabled": True,
     "extraction_mode": "full", "delta_field": None, "page_size": 500},
    {"name": "suppliers", "endpoint": "/api/v1/workforce/fieldglass/entities/suppliers", "enabled": True,
     "extraction_mode": "full", "delta_field": None, "page_size": 500},
    {"name": "job_postings", "endpoint": "/api/v1/workforce/fieldglass/entities/job_postings", "enabled": True,
     "extraction_mode": "full", "delta_field": None, "page_size": 500},
)
ENTITY_BY_NAME = {item["name"]: item for item in ENTITIES}
COLUMNS = {
    "workers": ["resource_id", "role", "skill", "supplier_id", "current_location_id", "availability", "current_rate_eur"],
    "timesheets": ["timesheet_id", "resource_id", "approved_date", "hours", "status"],
    "work_orders": ["work_order_id", "resource_id", "supplier_id", "role", "status"],
    "sow": ["contract_id", "supplier_id", "contract_type", "offshore_permitted", "customer_approval_required"],
    "invoices": ["invoice_id", "supplier_id", "po_id", "invoiced_amount", "currency", "invoice_date"],
    "suppliers": ["supplier_id", "name", "region", "capability"],
    "job_postings": ["job_posting_id", "role", "supplier_id", "status"],
}
ORIGINS = {
    "workers": "CostOpt local workforce table",
    "timesheets": "Synthetic demo timesheets derived from seeded team resources",
    "work_orders": "Synthetic demo work orders derived from seeded team resources",
    "sow": "CostOpt local contract table (SOW-type records only)",
    "invoices": "CostOpt local procurement invoice table (supplier-linked reference)",
    "suppliers": "CostOpt local supplier table",
    "job_postings": "Synthetic demo job postings derived from seeded team roles",
}


def entity_catalogue() -> dict[str, object]:
    return {"source": "local_mock", "live_connected": False, "entities": list(ENTITIES)}


def entity_preview(entity: str, scenario_id: str) -> dict[str, object]:
    if entity not in ENTITY_BY_NAME:
        raise ValueError("Unknown Fieldglass preview entity.")
    context = load_scenario_context(scenario_id=scenario_id)
    supplier_ids = sorted({resource.supplier_id for resource in context.resources})
    rows: list[dict[str, object]] = []
    if entity == "workers":
        rows = [{
            "resource_id": resource.resource_id, "role": resource.role, "skill": resource.skill,
            "supplier_id": resource.supplier_id, "current_location_id": resource.current_location_id,
            "availability": resource.availability or "active", "current_rate_eur": resource.current_rate,
        } for resource in context.resources]
    elif entity == "timesheets":
        rows = [{
            "timesheet_id": f"ts-demo-{index:03d}", "resource_id": resource.resource_id,
            "approved_date": "2026-09-30", "hours": 40, "status": "approved",
        } for index, resource in enumerate(context.resources[:5], start=1)]
    elif entity == "work_orders":
        rows = [{
            "work_order_id": f"wo-demo-{index:03d}", "resource_id": resource.resource_id,
            "supplier_id": resource.supplier_id, "role": resource.role, "status": "active",
        } for index, resource in enumerate(context.resources[:5], start=1)]
    elif entity == "job_postings":
        role_resources = {resource.role: resource for resource in context.resources}
        rows = [{
            "job_posting_id": f"jp-demo-{index:03d}", "role": role,
            "supplier_id": resource.supplier_id, "status": "illustrative demand",
        } for index, (role, resource) in enumerate(sorted(role_resources.items())[:5], start=1)]
    elif entity == "sow":
        rows = [{
            "contract_id": contract.contract_id, "supplier_id": contract.supplier_id,
            "contract_type": contract.contract_type, "offshore_permitted": contract.offshore_permitted,
            "customer_approval_required": contract.customer_approval_required,
        } for contract in context.contracts if "sow" in contract.contract_type.casefold()]
    elif entity in {"invoices", "suppliers"} and supplier_ids:
        markers = ",".join("?" for _ in supplier_ids)
        with get_connection() as connection:
            if entity == "invoices":
                result = connection.execute(
                    f"SELECT invoice_id, supplier_id, po_id, invoiced_amount, currency, invoice_date "
                    f"FROM invoices WHERE supplier_id IN ({markers}) ORDER BY invoice_id LIMIT 100",
                    supplier_ids,
                ).fetchall()
            else:
                result = connection.execute(
                    f"SELECT supplier_id, name, region, capability FROM suppliers "
                    f"WHERE supplier_id IN ({markers}) ORDER BY supplier_id",
                    supplier_ids,
                ).fetchall()
        rows = [dict(row) for row in result]
    return {
        **ENTITY_BY_NAME[entity], "source": "local_mock", "live_connected": False,
        "extraction_active": False, "origin": ORIGINS[entity],
        "scenario_id": scenario_id, "columns": COLUMNS[entity], "rows": rows,
        "row_count": len(rows), "status": ("synthetic_demo" if entity in {"timesheets", "work_orders", "job_postings"}
                                         else "local_mock" if rows else "not_available"),
        "analysis_role": ("Canonical workforce input for the selected demo team."
                          if entity == "workers" else
                          "Reference preview only; this entity is not applied to the optimization calculation."),
    }
