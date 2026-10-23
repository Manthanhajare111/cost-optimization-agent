from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
TABLES_DIR = ROOT_DIR / "data" / "synthetic" / "tables"
DOCUMENTS_DIR = ROOT_DIR / "data" / "synthetic" / "documents"
MANIFEST_PATH = ROOT_DIR / "data" / "synthetic" / "dataset-manifest.json"
README_PATH = TABLES_DIR / "README.md"
GENERATED_AT = "2026-08-28T00:00:00Z"
BILLING_UNITS_PER_MONTH = 10.14


@dataclass(frozen=True)
class SupplierSpec:
    supplier_id: str
    name: str
    region: str
    capability: str


@dataclass(frozen=True)
class LocationSpec:
    location_id: str
    country: str
    region: str
    cost_index: float
    is_offshore: bool


@dataclass(frozen=True)
class SquadSpec:
    squad_id: str
    name: str
    business_unit: str


SUPPLIER_SPECS = [
    SupplierSpec("sup-acme-global", "Acme Global Delivery", "EMEA/APAC", "Payments, platform engineering, managed delivery"),
    SupplierSpec("sup-bluewave-tech", "BlueWave Technology Services", "Europe", "QA, support engineering, enterprise modernization"),
    SupplierSpec("sup-northbridge-digital", "NorthBridge Digital", "Global", "Cloud transformation, API engineering, SRE"),
    SupplierSpec("sup-eastgate-solutions", "EastGate Solutions", "APAC", "Application development, testing, support"),
    SupplierSpec("sup-redwood-advisory", "Redwood Advisory", "Americas", "Architecture, consulting, delivery management"),
    SupplierSpec("sup-orbit-systems", "Orbit Systems", "Global", "Managed services, DevOps, automation"),
    SupplierSpec("sup-vertex-consulting", "Vertex Consulting", "Europe", "Data engineering, analytics, modernization"),
    SupplierSpec("sup-sunline-digital", "Sunline Digital", "APAC", "Support, migration, product engineering"),
    SupplierSpec("sup-clearpath-it", "ClearPath IT", "Americas", "Testing, product delivery, governance"),
    SupplierSpec("sup-aurora-works", "Aurora Works", "Global", "Payments, core banking, agile pods"),
    SupplierSpec("sup-polaris-labs", "Polaris Labs", "Europe", "Security engineering, compliance-heavy workloads"),
    SupplierSpec("sup-horizon-ops", "Horizon Ops", "Global", "Run support, service desk, monitoring"),
    SupplierSpec("sup-mapleleaf-digital", "MapleLeaf Digital", "Americas", "Frontend, mobile, CX engineering"),
    SupplierSpec("sup-riverstone-tech", "Riverstone Tech", "Europe", "ERP extensions, integration engineering"),
    SupplierSpec("sup-nimbus-partners", "Nimbus Partners", "Global", "Cloud platforms, shared services"),
    SupplierSpec("sup-zenbyte-services", "ZenByte Services", "APAC", "Quality automation, support engineering"),
    SupplierSpec("sup-silveroak-global", "SilverOak Global", "EMEA", "Program delivery, transformation squads"),
    SupplierSpec("sup-bridgepoint-logic", "BridgePoint Logic", "Americas", "Data migration, reporting, middleware"),
    SupplierSpec("sup-cedarwave-tech", "CedarWave Tech", "Global", "Platform operations, SRE, support"),
    SupplierSpec("sup-tristar-solutions", "TriStar Solutions", "APAC", "Procurement tech, shared development pods"),
]

LOCATION_SPECS = [
    LocationSpec("loc-germany", "Germany", "EMEA", 1.00, False),
    LocationSpec("loc-india", "India", "APAC", 0.58, True),
    LocationSpec("loc-poland", "Poland", "EMEA", 0.74, False),
    LocationSpec("loc-romania", "Romania", "EMEA", 0.69, False),
    LocationSpec("loc-portugal", "Portugal", "EMEA", 0.76, False),
    LocationSpec("loc-uk", "United Kingdom", "EMEA", 0.98, False),
    LocationSpec("loc-usa", "United States", "Americas", 1.08, False),
    LocationSpec("loc-canada", "Canada", "Americas", 0.95, False),
    LocationSpec("loc-mexico", "Mexico", "Americas", 0.63, True),
    LocationSpec("loc-brazil", "Brazil", "Americas", 0.66, True),
    LocationSpec("loc-south-africa", "South Africa", "EMEA", 0.61, True),
    LocationSpec("loc-egypt", "Egypt", "EMEA", 0.57, True),
    LocationSpec("loc-uae", "United Arab Emirates", "EMEA", 0.88, False),
    LocationSpec("loc-singapore", "Singapore", "APAC", 0.93, False),
    LocationSpec("loc-vietnam", "Vietnam", "APAC", 0.49, True),
    LocationSpec("loc-philippines", "Philippines", "APAC", 0.52, True),
    LocationSpec("loc-malaysia", "Malaysia", "APAC", 0.55, True),
    LocationSpec("loc-australia", "Australia", "APAC", 1.02, False),
    LocationSpec("loc-ireland", "Ireland", "EMEA", 0.96, False),
    LocationSpec("loc-netherlands", "Netherlands", "EMEA", 0.97, False),
]

SQUAD_SPECS = [
    SquadSpec("squad-payments-platform", "Payments Platform Squad", "Digital Banking"),
    SquadSpec("squad-core-banking-qa", "Core Banking QA Squad", "Retail Banking"),
    SquadSpec("squad-global-support", "Global Support Pod", "Service Operations"),
    SquadSpec("squad-mobile-app", "Mobile App Squad", "Channels"),
    SquadSpec("squad-data-foundation", "Data Foundation Squad", "Enterprise Data"),
    SquadSpec("squad-card-services", "Card Services Squad", "Cards"),
    SquadSpec("squad-risk-analytics", "Risk Analytics Squad", "Risk"),
    SquadSpec("squad-fraud-monitoring", "Fraud Monitoring Pod", "Security"),
    SquadSpec("squad-loans-origination", "Loans Origination Squad", "Lending"),
    SquadSpec("squad-kafka-platform", "Kafka Platform Squad", "Infrastructure"),
    SquadSpec("squad-qa-automation", "QA Automation Guild", "Engineering Excellence"),
    SquadSpec("squad-reg-reporting", "Regulatory Reporting Team", "Finance"),
    SquadSpec("squad-api-gateway", "API Gateway Squad", "Architecture"),
    SquadSpec("squad-observability", "Observability Pod", "Infrastructure"),
    SquadSpec("squad-customer-360", "Customer 360 Team", "CRM"),
    SquadSpec("squad-integration-hub", "Integration Hub Squad", "Middleware"),
    SquadSpec("squad-cloud-migration", "Cloud Migration Factory", "Transformation"),
    SquadSpec("squad-procurement-ops", "Procurement Ops Squad", "Corporate Functions"),
    SquadSpec("squad-treasury-tech", "Treasury Tech Squad", "Treasury"),
    SquadSpec("squad-identity-platform", "Identity Platform Squad", "Security"),
]

CATEGORY_SPECS = [
    ("cat-it-services", "IT Services", "IT-001"),
    ("cat-consulting", "Consulting", "CS-014"),
    ("cat-cloud-hosting", "Cloud Hosting", "CL-220"),
    ("cat-managed-support", "Managed Support", "MS-032"),
    ("cat-software-testing", "Software Testing", "QA-118"),
    ("cat-product-design", "Product Design", "PD-048"),
    ("cat-cybersecurity", "Cybersecurity", "CY-071"),
    ("cat-data-platforms", "Data Platforms", "DP-205"),
    ("cat-integration-services", "Integration Services", "IS-113"),
    ("cat-mobile-engineering", "Mobile Engineering", "ME-064"),
    ("cat-bpm-services", "BPM Services", "BP-152"),
    ("cat-erp-services", "ERP Services", "ER-147"),
    ("cat-observability-tools", "Observability Tools", "OB-091"),
    ("cat-service-desk", "Service Desk", "SD-033"),
    ("cat-analytics-advisory", "Analytics Advisory", "AA-177"),
    ("cat-network-operations", "Network Operations", "NO-120"),
    ("cat-shared-delivery", "Shared Delivery", "SH-089"),
    ("cat-supplier-transition", "Supplier Transition", "ST-145"),
    ("cat-devops-services", "DevOps Services", "DV-097"),
    ("cat-reporting-services", "Reporting Services", "RP-188"),
]


def main() -> None:
    TABLES_DIR.mkdir(parents=True, exist_ok=True)
    DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)

    suppliers = build_suppliers()
    locations = build_locations()
    squads = build_squads()
    categories = build_categories()
    users = build_users()
    resources = build_resources(locations)
    rate_cards = build_rate_cards(locations)
    contracts = build_contracts()
    contract_clauses = build_contract_clauses(contracts)
    write_contract_documents(contracts, contract_clauses)
    optimization_scenarios = build_optimization_scenarios()
    recommendations = build_recommendations(optimization_scenarios, contracts)
    recommendation_evidence = build_recommendation_evidence(recommendations, contract_clauses)
    purchase_orders = build_purchase_orders()
    procurement_contracts = build_procurement_contracts()
    invoices = build_invoices(purchase_orders, procurement_contracts)
    procurement_recommendations = build_procurement_recommendations()
    audit_log = build_audit_log(
        users=users,
        contracts=contracts,
        recommendations=recommendations,
        optimization_scenarios=optimization_scenarios,
        purchase_orders=purchase_orders,
        procurement_recommendations=procurement_recommendations,
    )

    table_payloads = {
        "suppliers": suppliers,
        "locations": locations,
        "squads": squads,
        "resources": resources,
        "rate_cards": rate_cards,
        "contracts": contracts,
        "contract_clauses": contract_clauses,
        "optimization_scenarios": optimization_scenarios,
        "recommendations": recommendations,
        "recommendation_evidence": recommendation_evidence,
        "categories": categories,
        "purchase_orders": purchase_orders,
        "procurement_contracts": procurement_contracts,
        "invoices": invoices,
        "procurement_recommendations": procurement_recommendations,
        "users": users,
        "audit_log": audit_log,
    }

    for table_name, rows in table_payloads.items():
        write_json(TABLES_DIR / f"{table_name}.json", rows)

    write_manifest(table_payloads)
    write_readme(table_payloads)
    print(json.dumps({name: len(rows) for name, rows in table_payloads.items()}, indent=2))


def build_suppliers() -> list[dict]:
    rows = []
    for index, supplier in enumerate(SUPPLIER_SPECS, start=1):
        rows.append(
            {
                "supplier_id": supplier.supplier_id,
                "name": supplier.name,
                "region": supplier.region,
                "capability": supplier.capability,
                "created_at": timestamp(index),
            }
        )
    return rows


def build_locations() -> list[dict]:
    return [
        {
            "location_id": location.location_id,
            "country": location.country,
            "region": location.region,
            "cost_index": location.cost_index,
            "is_offshore": location.is_offshore,
        }
        for location in LOCATION_SPECS
    ]


def build_squads() -> list[dict]:
    return [
        {
            "squad_id": squad.squad_id,
            "name": squad.name,
            "business_unit": squad.business_unit,
        }
        for squad in SQUAD_SPECS
    ]


def build_categories() -> list[dict]:
    return [
        {
            "category_id": category_id,
            "name": name,
            "commodity_code": code,
        }
        for category_id, name, code in CATEGORY_SPECS
    ]


def build_users() -> list[dict]:
    roles = ["admin", "analyst", "procurement_manager", "legal_reviewer", "readonly"]
    rows = []
    for index in range(20):
        rows.append(
            {
                "user_id": f"user-{index + 1:03d}",
                "email": f"user{index + 1:02d}@costopt.local",
                "role": roles[index % len(roles)],
            }
        )
    return rows


def build_resources(locations: list[dict]) -> list[dict]:
    onshore_locations = [
        "loc-germany",
        "loc-poland",
        "loc-uk",
        "loc-usa",
        "loc-canada",
        "loc-portugal",
        "loc-ireland",
        "loc-netherlands",
        "loc-singapore",
        "loc-australia",
    ]
    location_index = {row["location_id"]: row["cost_index"] for row in locations}
    rows: list[dict] = []
    counter = 1

    payments_resources = [
        ("Architect", "Platform architecture", 1200),
        ("Architect", "Solution design", 1200),
        ("Delivery Lead", "Agile delivery", 1050),
        ("Developer", "Java payments", 900),
        ("Developer", "Java payments", 900),
        ("Developer", "Java payments", 900),
        ("Developer", "Java payments", 900),
        ("Developer", "API engineering", 900),
        ("Developer", "API engineering", 900),
        ("Developer", "UI engineering", 880),
        ("Developer", "UI engineering", 880),
        ("Developer", "Automation testing", 860),
        ("Developer", "Automation testing", 860),
        ("Developer", "Support engineering", 840),
        ("Developer", "Support engineering", 840),
    ]

    for role, skill, current_rate in payments_resources:
        rows.append(
            {
                "resource_id": f"res-{counter:03d}",
                "supplier_id": "sup-acme-global",
                "squad_id": "squad-payments-platform",
                "current_location_id": "loc-germany",
                "role": role,
                "skill": skill,
                "current_rate": current_rate,
                "pii_access": role == "Developer" and skill == "Java payments" and counter in {4, 5},
                "availability": "active",
            }
        )
        counter += 1

    role_templates = [
        ("Architect", "Solution architecture", 1120, "active"),
        ("Delivery Lead", "Delivery management", 980, "active"),
        ("Developer", "Feature engineering", 760, "active"),
        ("QA Engineer", "Quality engineering", 690, "planned"),
        ("Support Engineer", "Run support", 640, "active"),
    ]

    for squad_index, squad in enumerate(SQUAD_SPECS[1:], start=2):
        supplier = SUPPLIER_SPECS[(squad_index - 1) % len(SUPPLIER_SPECS)]
        current_location_id = onshore_locations[(squad_index - 2) % len(onshore_locations)]
        location_factor = location_index[current_location_id]
        for role_index, (role, skill, base_rate, availability) in enumerate(role_templates, start=1):
            rows.append(
                {
                    "resource_id": f"res-{counter:03d}",
                    "supplier_id": supplier.supplier_id,
                    "squad_id": squad.squad_id,
                    "current_location_id": current_location_id,
                    "role": role,
                    "skill": f"{skill} {squad_index}-{role_index}",
                    "current_rate": round(base_rate * location_factor, 2),
                    "pii_access": False,
                    "availability": availability,
                }
            )
            counter += 1

    return rows


def build_rate_cards(locations: list[dict]) -> list[dict]:
    rate_locations = [
        "loc-germany",
        "loc-india",
        "loc-poland",
        "loc-philippines",
        "loc-vietnam",
    ]
    location_index = {row["location_id"]: row["cost_index"] for row in locations}
    role_bases = {
        "Architect": 1200,
        "Delivery Lead": 1050,
        "Developer": 900,
        "QA Engineer": 700,
        "Support Engineer": 620,
    }

    rows = []
    counter = 1
    for supplier_index, supplier in enumerate(SUPPLIER_SPECS, start=1):
        supplier_modifier = 1 + ((supplier_index % 5) - 2) * 0.03
        for location_id in rate_locations:
            for role, base_rate in role_bases.items():
                bill_rate = round(base_rate * location_index[location_id] * supplier_modifier, 2)
                if supplier.supplier_id == "sup-acme-global":
                    overrides = {
                        ("loc-germany", "Architect"): 1200.0,
                        ("loc-germany", "Delivery Lead"): 1050.0,
                        ("loc-germany", "Developer"): 900.0,
                        ("loc-india", "Architect"): 760.0,
                        ("loc-india", "Delivery Lead"): 680.0,
                        ("loc-india", "Developer"): 397.0,
                    }
                    bill_rate = overrides.get((location_id, role), bill_rate)
                rows.append(
                    {
                        "rate_card_id": f"rc-{counter:03d}",
                        "supplier_id": supplier.supplier_id,
                        "location_id": location_id,
                        "role": role,
                        "bill_rate": bill_rate,
                        "currency": "EUR",
                    }
                )
                counter += 1
    return rows


def build_contracts() -> list[dict]:
    contract_types = ["SOW", "MSA", "Rate Card", "Service Agreement"]
    rows = []
    for index, supplier in enumerate(SUPPLIER_SPECS, start=1):
        rows.append(
            {
                "contract_id": f"ctr-{index:03d}",
                "supplier_id": supplier.supplier_id,
                "document_uri": f"data/synthetic/documents/contract-sow-{index:02d}.txt",
                "contract_type": contract_types[(index - 1) % len(contract_types)],
                "offshore_permitted": index not in {5, 10, 15, 20},
                "data_residency_restriction": contract_residency(index),
                "customer_approval_required": index == 1 or index % 2 == 0,
                "created_at": timestamp(index),
            }
        )
    return rows


def build_contract_clauses(contracts: list[dict]) -> list[dict]:
    rows = []
    counter = 1
    for contract in contracts:
        offshore_text = (
            "Offshore delivery is permitted for software engineering services under this agreement."
            if contract["offshore_permitted"]
            else "Offshore delivery is not permitted without a formal contract amendment."
        )
        residency_text = contract["data_residency_restriction"] or "No special data residency restriction applies beyond standard policy."
        approval_text = (
            "Written customer approval is required before shifting delivery activity to a new geography."
            if contract["customer_approval_required"]
            else "No additional customer approval is required for location changes within approved supplier sites."
        )

        clauses = [
            ("offshore_delivery", offshore_text),
            ("data_residency", residency_text),
            ("customer_approval", approval_text),
        ]

        for clause_type, clause_text in clauses:
            rows.append(
                {
                    "clause_id": f"clause-{counter:03d}",
                    "contract_id": contract["contract_id"],
                    "clause_type": clause_type,
                    "clause_text": clause_text,
                    "embedding": None,
                }
            )
            counter += 1
    return rows


def write_contract_documents(contracts: list[dict], clauses: list[dict]) -> None:
    clause_map: dict[str, list[dict]] = {}
    for clause in clauses:
        clause_map.setdefault(clause["contract_id"], []).append(clause)

    for contract in contracts:
        doc_path = ROOT_DIR / contract["document_uri"]
        doc_path.parent.mkdir(parents=True, exist_ok=True)
        contract_clauses = clause_map[contract["contract_id"]]
        content = [
            f"Synthetic Contract Document for {contract['contract_id']}",
            "",
            f"Supplier: {contract['supplier_id']}",
            f"Contract Type: {contract['contract_type']}",
            "",
        ]
        for clause in contract_clauses:
            content.append(f"{clause['clause_type']}: {clause['clause_text']}")
        doc_path.write_text("\n".join(content) + "\n", encoding="utf-8")


def build_optimization_scenarios() -> list[dict]:
    target_locations = ["loc-india", "loc-poland", "loc-philippines", "loc-vietnam", "loc-romania"]
    rows = []
    for index, squad in enumerate(SQUAD_SPECS, start=1):
        if index == 1:
            baseline_cost = 142061.4
            future_cost = 93490.8
            monthly_savings = 48570.6
        else:
            baseline_cost = round(86500 + (index * 4825), 2)
            future_cost = round(baseline_cost * (0.67 + (index % 4) * 0.04), 2)
            monthly_savings = round(baseline_cost - future_cost, 2)

        rows.append(
            {
                "scenario_id": f"scn-{index:03d}",
                "squad_id": squad.squad_id,
                "target_location_id": target_locations[(index - 1) % len(target_locations)],
                "baseline_cost": baseline_cost,
                "future_cost": future_cost,
                "monthly_savings": monthly_savings,
                "annual_savings": round(monthly_savings * 12, 2),
                "assumptions": {
                    "currency": "EUR",
                    "billing_units_per_month": BILLING_UNITS_PER_MONTH,
                    "human_approval_required": True,
                    "seeded_on": GENERATED_AT[:10],
                    "scenario_name": "Germany to India right-shoring" if index == 1 else f"{squad.name} to {target_locations[(index - 1) % len(target_locations)]} scenario",
                    "current_location_id": "loc-germany" if index == 1 else infer_current_location_for_squad(index),
                },
                "created_at": timestamp(index),
            }
        )
    return rows


def build_recommendations(optimization_scenarios: list[dict], contracts: list[dict]) -> list[dict]:
    rows = []
    for index, scenario in enumerate(optimization_scenarios, start=1):
        contract = contracts[index - 1]
        if index == 1:
            confidence = 0.87
        else:
            confidence = round(0.78 + (index % 6) * 0.02, 2)
            if contract["customer_approval_required"]:
                confidence = round(confidence - 0.02, 2)
            if contract["data_residency_restriction"]:
                confidence = round(confidence - 0.01, 2)

        compliance_bits = [
            "Offshore permitted." if contract["offshore_permitted"] else "Offshore restricted.",
            contract["data_residency_restriction"] or "No special residency restriction.",
            "Customer approval required." if contract["customer_approval_required"] else "No extra customer approval required.",
        ]
        rows.append(
            {
                "recommendation_id": f"rec-{index:03d}",
                "scenario_id": scenario["scenario_id"],
                "confidence_score": max(min(confidence, 0.95), 0.62),
                "compliance_summary": " ".join(compliance_bits),
                "risk_assessment": recommendation_risk(contract, scenario),
                "rationale": recommendation_rationale(index, scenario),
                "created_at": timestamp(index),
            }
        )
    return rows


def build_recommendation_evidence(recommendations: list[dict], clauses: list[dict]) -> list[dict]:
    clause_groups: dict[str, list[dict]] = {}
    for clause in clauses:
        contract_index = int(clause["contract_id"].split("-")[1])
        clause_groups.setdefault(f"rec-{contract_index:03d}", []).append(clause)

    rows = []
    counter = 1
    for recommendation in recommendations:
        for clause in clause_groups[recommendation["recommendation_id"]]:
            rows.append(
                {
                    "evidence_id": f"evd-{counter:03d}",
                    "recommendation_id": recommendation["recommendation_id"],
                    "clause_id": clause["clause_id"],
                }
            )
            counter += 1
    return rows


def build_purchase_orders() -> list[dict]:
    rows = []
    counter = 1
    business_units = [squad.business_unit for squad in SQUAD_SPECS]
    for category_index, (category_id, _, _) in enumerate(CATEGORY_SPECS, start=1):
        for offset in range(3):
            supplier = SUPPLIER_SPECS[(category_index + offset - 1) % len(SUPPLIER_SPECS)]
            rows.append(
                {
                    "po_id": f"po-{counter:03d}",
                    "supplier_id": supplier.supplier_id,
                    "category_id": category_id,
                    "business_unit": business_units[(counter - 1) % len(business_units)],
                    "amount": round(12000 + (counter * 1850), 2),
                    "currency": "EUR",
                    "order_date": order_date(counter),
                }
            )
            counter += 1
    return rows


def build_procurement_contracts() -> list[dict]:
    rows = []
    for index, (category_id, _, _) in enumerate(CATEGORY_SPECS, start=1):
        supplier = SUPPLIER_SPECS[index - 1]
        rows.append(
            {
                "procurement_contract_id": f"pct-{index:03d}",
                "supplier_id": supplier.supplier_id,
                "category_id": category_id,
                "negotiated_rate": round(420 + (index * 18.5), 2),
                "currency": "EUR",
                "is_preferred_supplier": index % 3 != 0,
                "start_date": "2026-01-01",
                "end_date": "2027-12-31",
            }
        )
    return rows


def build_invoices(purchase_orders: list[dict], procurement_contracts: list[dict]) -> list[dict]:
    contract_map = {
        contract["supplier_id"]: contract["procurement_contract_id"]
        for contract in procurement_contracts
    }
    rows = []
    for index, purchase_order in enumerate(purchase_orders[:40], start=1):
        variance = 1 + ((index % 5) - 2) * 0.035
        po_link = purchase_order["po_id"] if index % 6 != 0 else None
        contract_link = contract_map.get(purchase_order["supplier_id"]) if index % 7 != 0 else None
        rows.append(
            {
                "invoice_id": f"inv-{index:03d}",
                "supplier_id": purchase_order["supplier_id"],
                "po_id": po_link,
                "procurement_contract_id": contract_link,
                "invoiced_amount": round(purchase_order["amount"] * variance, 2),
                "currency": "EUR",
                "invoice_date": order_date(index + 10),
            }
        )
    return rows


def build_procurement_recommendations() -> list[dict]:
    use_cases = [
        "TAIL_SPEND",
        "INVOICE_VARIANCE",
        "DUPLICATE_SERVICE",
        "RATE_BENCHMARK",
        "SUPPLIER_CONSOLIDATION",
    ]
    rows = []
    for index in range(20):
        use_case = use_cases[index % len(use_cases)]
        rows.append(
            {
                "proc_recommendation_id": f"prec-{index + 1:03d}",
                "use_case": use_case,
                "estimated_savings": round(85000 + (index * 14500), 2),
                "currency": "EUR",
                "confidence_score": round(0.79 + ((index % 5) * 0.03), 2),
                "rationale": procurement_rationale(use_case),
                "risk_assessment": procurement_risk(use_case),
                "created_at": timestamp(index + 1),
            }
        )
    return rows


def build_audit_log(
    users: list[dict],
    contracts: list[dict],
    recommendations: list[dict],
    optimization_scenarios: list[dict],
    purchase_orders: list[dict],
    procurement_recommendations: list[dict],
) -> list[dict]:
    entities = (
        [("contracts", row["contract_id"]) for row in contracts]
        + [("recommendations", row["recommendation_id"]) for row in recommendations]
        + [("optimization_scenarios", row["scenario_id"]) for row in optimization_scenarios]
        + [("purchase_orders", row["po_id"]) for row in purchase_orders[:10]]
        + [("procurement_recommendations", row["proc_recommendation_id"]) for row in procurement_recommendations[:10]]
    )
    actions = ["CREATE", "READ", "UPDATE", "EXPORT"]
    rows = []
    for index, (entity_type, entity_id) in enumerate(entities[:60], start=1):
        user_id = None if index % 7 == 0 else users[(index - 1) % len(users)]["user_id"]
        rows.append(
            {
                "audit_id": f"adt-{index:03d}",
                "user_id": user_id,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "action": actions[(index - 1) % len(actions)],
                "details": {
                    "source": "synthetic-seed",
                    "batch": "initial-full-dataset",
                    "sequence": index,
                },
                "ip_address": f"10.10.0.{(index % 50) + 10}",
                "created_at": timestamp(index),
            }
        )
    return rows


def write_manifest(table_payloads: dict[str, list[dict]]) -> None:
    manifest = {
        "generated_at": GENERATED_AT,
        "generator": "scripts/generate_full_synthetic_dataset.py",
        "table_counts": {name: len(rows) for name, rows in table_payloads.items()},
        "minimum_rows_per_table": min(len(rows) for rows in table_payloads.values()),
        "document_count": len(list(DOCUMENTS_DIR.glob("contract-sow-*.txt"))),
        "notes": [
            "All table files are deterministic and safe to regenerate.",
            "The workforce and procurement datasets share the same supplier master data.",
            "The Germany to India scenario is preserved in the dedicated workforce templates and reflected in scenario outputs.",
        ],
    }
    write_json(MANIFEST_PATH, manifest)


def write_readme(table_payloads: dict[str, list[dict]]) -> None:
    counts = "\n".join(
        f"- `{table_name}`: {len(rows)} rows"
        for table_name, rows in sorted(table_payloads.items())
    )
    content = (
        "# Synthetic Table Seeds\n\n"
        "Generated on 2026-08-28 by `scripts/generate_full_synthetic_dataset.py`.\n\n"
        "Each JSON file in this folder maps to one schema table and contains at least 20 rows.\n\n"
        "## Row Counts\n\n"
        f"{counts}\n"
    )
    README_PATH.write_text(content, encoding="utf-8")


def recommendation_risk(contract: dict, scenario: dict) -> str:
    if not contract["offshore_permitted"]:
        return "High compliance risk due to offshore restriction; recommendation should default to retain."
    if contract["customer_approval_required"]:
        return "Medium compliance risk pending formal customer approval."
    if scenario["monthly_savings"] < 20000:
        return "Low delivery risk but modest value upside."
    return "Low delivery risk with credible savings potential."


def recommendation_rationale(index: int, scenario: dict) -> str:
    if index == 1:
        return "Keep leadership, architecture, and PII-handling work in Germany while moving eligible engineering work to India."
    if scenario["monthly_savings"] >= 30000:
        return "Shift routine engineering work to the target delivery hub while retaining leadership and high-context roles."
    return "Retain critical coordination roles onshore and right-shore standard delivery work where the cost delta is attractive."


def procurement_rationale(use_case: str) -> str:
    mapping = {
        "TAIL_SPEND": "Consolidate fragmented low-value spend under preferred suppliers to improve leverage and governance.",
        "INVOICE_VARIANCE": "Flag invoice amounts that exceed expected contract or purchase-order ranges before payment.",
        "DUPLICATE_SERVICE": "Collapse overlapping service buys into enterprise-wide agreements for better pricing.",
        "RATE_BENCHMARK": "Use benchmark comparisons to prioritize overpriced supplier contracts for renegotiation.",
        "SUPPLIER_CONSOLIDATION": "Concentrate spend with stronger strategic suppliers to reduce fragmentation and improve rates.",
    }
    return mapping[use_case]


def procurement_risk(use_case: str) -> str:
    mapping = {
        "TAIL_SPEND": "Low commercial risk with moderate change-management effort.",
        "INVOICE_VARIANCE": "Low compliance risk and high financial-control value.",
        "DUPLICATE_SERVICE": "Medium coordination risk across business units.",
        "RATE_BENCHMARK": "Medium supplier-relationship risk during renegotiation.",
        "SUPPLIER_CONSOLIDATION": "Medium transition risk due to supplier offboarding and knowledge transfer.",
    }
    return mapping[use_case]


def contract_residency(index: int) -> str | None:
    if index in {1, 4, 8, 12, 16, 20}:
        return "EU PII must remain in approved EU-hosted workflows."
    if index in {3, 7, 11, 15, 19}:
        return "Customer data classified as confidential must remain within designated regional delivery centers."
    return None


def timestamp(index: int) -> str:
    day = ((index - 1) % 28) + 1
    hour = 8 + ((index - 1) % 10)
    return f"2026-06-{day:02d}T{hour:02d}:00:00Z"


def order_date(index: int) -> str:
    month = 1 + ((index - 1) // 20)
    day = ((index - 1) % 20) + 1
    return f"2026-{month:02d}-{day:02d}"


def infer_current_location_for_squad(index: int) -> str:
    onshore_locations = [
        "loc-germany",
        "loc-poland",
        "loc-uk",
        "loc-usa",
        "loc-canada",
        "loc-portugal",
        "loc-ireland",
        "loc-netherlands",
        "loc-singapore",
        "loc-australia",
    ]
    return onshore_locations[(index - 2) % len(onshore_locations)]


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
