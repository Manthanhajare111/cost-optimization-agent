from fastapi.testclient import TestClient

from costopt.api.app import create_app
from costopt.storage.sqlite import get_connection


def test_api_endpoints_are_sqlite_backed(isolated_db):
    client = TestClient(create_app())

    squads_response = client.get("/api/v1/squads")
    assert squads_response.status_code == 200
    assert len(squads_response.json()) == 20

    scenarios_response = client.get("/api/v1/scenarios")
    assert scenarios_response.status_code == 200
    assert len(scenarios_response.json()) == 20
    assert scenarios_response.json()[0]["scenario_name"] == "Germany to Philippines right-shoring"

    contracts_response = client.get("/api/v1/contracts")
    assert contracts_response.status_code == 200
    assert len(contracts_response.json()) == 20

    locations_response = client.get("/api/v1/locations")
    assert locations_response.status_code == 200
    assert len(locations_response.json()) == 21
    assert any(location["country"] == "Ukraine" for location in locations_response.json())

    agents_response = client.get("/api/v1/agents")
    assert agents_response.status_code == 200
    assert len(agents_response.json()) == 12
    assert any(agent["name"] == "data_cleaning" for agent in agents_response.json())
    assert any(agent["name"] == "data_validation" for agent in agents_response.json())
    assert agents_response.json()[0]["name"] == "data_cleaning"

    catalogue_response = client.get("/api/v1/data-governance/source-catalogue")
    assert catalogue_response.status_code == 200
    catalogue = catalogue_response.json()
    assert catalogue["catalogue_version"] == "2026-09-25"
    assert catalogue["data_boundary"] == "synthetic canonical data plus sanitised SAP samples; no live SAP connectivity"
    assert any(entity["name"] == "resource" for entity in catalogue["entities"])
    assert any(gap["gap_id"] == "G-001" for gap in catalogue["open_gaps"])

    mock_sap_response = client.get("/api/v1/integrations/sap/mock/suppliers?limit=2")
    assert mock_sap_response.status_code == 200
    assert mock_sap_response.json()["live_sap_connected"] is False
    assert len(mock_sap_response.json()["items"]) == 2

    analyze_response = client.post(
        "/api/v1/scenarios/analyze",
        json={"scenario_name": "germany-philippines"},
    )
    assert analyze_response.status_code == 200
    recommendation_id = analyze_response.json()["recommendation_id"]
    assert analyze_response.json()["costs"]["annual_savings"] == scenarios_response.json()[0][
        "annual_savings"
    ]

    with get_connection() as connection:
        assert connection.execute(
            "SELECT COUNT(*) AS count FROM agent_run_audits"
        ).fetchone()["count"] == 1

    backlog_response = client.get("/api/v1/recommendations")
    assert backlog_response.status_code == 200
    assert len(backlog_response.json()) == 1

    detail_response = client.get(f"/api/v1/recommendations/{recommendation_id}")
    assert detail_response.status_code == 200
    assert detail_response.json()["scenario_id"] == "scn-001"

    explain_response = client.post(f"/api/v1/recommendations/{recommendation_id}/explain")
    assert explain_response.status_code == 200
    assert explain_response.json()["provider"] == "deterministic_fallback"
    assert explain_response.json()["used_fallback"] is True


def test_agent_run_returns_auditable_stages(isolated_db):
    client = TestClient(create_app())

    response = client.post("/api/v1/scenarios/run", json={"scenario_name": "germany-philippines"})

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"]
    assert body["recommendation_id"]
    assert "input_snapshot" not in body
    assert body["recommendation"]["moved_count"] == 10
    assert set(body["recommendation"]["supplier_compliance"]) == {"sup-acme-global"}
    assert [stage["name"] for stage in body["stages"]] == [
        "planner",
        "retriever",
        "contract",
        "tail_spend",
        "risk_bcp",
        "timezone_mitigation",
        "optimization",
        "financial_working_capital",
        "reporting",
        "approval",
    ]
    contract_stage = next(stage for stage in body["stages"] if stage["name"] == "contract")
    assert contract_stage["llm"] == {
        "enabled": False,
        "provider": "deterministic",
        "model": "",
        "prompt_key": "compliance_evidence_review_v1",
    }
    assert contract_stage["used_fallback"] is True
    assert "Offshore delivery" in contract_stage["narrative"]["summary"]
    optimization_stage = next(
        stage for stage in body["stages"] if stage["name"] == "optimization"
    )
    assert optimization_stage["finding"]["metrics"]["engine"] == "ortools_cp_sat"
    assert body["requires_human_review"] is True

    audit_response = client.get(f"/api/v1/agent-runs/{body['run_id']}")
    assert audit_response.status_code == 200
    assert audit_response.json()["run_id"] == body["run_id"]
    assert audit_response.json()["recommendation_id"] == body["recommendation_id"]


def test_agent_run_requires_material_change_approval_without_contract_requirement(isolated_db):
    with get_connection() as connection:
        connection.execute(
            "UPDATE contracts SET customer_approval_required = 0 WHERE supplier_id = 'sup-acme-global'"
        )
        connection.execute(
            "UPDATE contract_clauses SET clause_text = "
            "'No additional customer approval is required for approved supplier sites.' "
            "WHERE contract_id = 'ctr-001' AND clause_type = 'customer_approval'"
        )

    client = TestClient(create_app())
    response = client.post("/api/v1/scenarios/run", json={"scenario_name": "germany-philippines"})

    assert response.status_code == 200
    contract_stage = next(
        stage for stage in response.json()["stages"] if stage["name"] == "contract"
    )
    assert contract_stage["outcome"] == "allowed"
    assert response.json()["recommendation"]["moved_count"] == 10
    assert response.json()["requires_human_review"] is True
    assert "Material workforce movement" in response.json()["review_reasons"][0]


def test_agent_run_requires_customer_approval_when_contract_demands_it(isolated_db):
    client = TestClient(create_app())

    response = client.post("/api/v1/scenarios/run", json={"scenario_name": "germany-philippines"})

    assert response.status_code == 200
    contract_stage = next(
        stage for stage in response.json()["stages"] if stage["name"] == "contract"
    )
    assert contract_stage["outcome"] == "allowed_with_approval"
    assert "written customer approval" in response.json()["recommendation"]["recommendation"]


def test_agent_run_blocks_moves_when_offshore_delivery_is_prohibited(isolated_db):
    with get_connection() as connection:
        connection.execute(
            "UPDATE contracts SET offshore_permitted = 0 WHERE supplier_id = 'sup-acme-global'"
        )

    client = TestClient(create_app())
    response = client.post("/api/v1/scenarios/run", json={"scenario_name": "germany-philippines"})

    assert response.status_code == 200
    recommendation = response.json()["recommendation"]
    contract_stage = next(
        stage for stage in response.json()["stages"] if stage["name"] == "contract"
    )
    assert contract_stage["outcome"] == "blocked"
    assert recommendation["moved_count"] == 0
    assert recommendation["costs"]["monthly_savings"] == 0
    assert all(decision["action"] == "retain" for decision in recommendation["resource_decisions"])


def test_api_runs_any_valid_seeded_scenario(isolated_db):
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/scenarios/run",
        json={"scenario_name": "Core Banking QA Squad to loc-poland scenario"},
    )

    assert response.status_code == 200
    assert response.json()["recommendation"]["scenario_id"] == "scn-002"


def test_api_accepts_scenario_id_and_country_target(isolated_db):
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/scenarios/run",
        json={"scenario_id": "scn-001", "target_location_id": "Philippines"},
    )

    assert response.status_code == 200
    assert response.json()["recommendation"]["target_location_id"] == "loc-philippines"
