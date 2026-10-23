from fastapi.testclient import TestClient

from costopt.api.app import create_app


def test_api_active_endpoints(isolated_db):
    client = TestClient(create_app())

    # Health check
    health_response = client.get("/health")
    assert health_response.status_code == 200
    assert health_response.json()["status"] == "ok"

    # Scenarios reference
    scenarios_response = client.get("/api/v1/scenarios")
    assert scenarios_response.status_code == 200
    assert len(scenarios_response.json()) > 0
    assert "right-shoring" in scenarios_response.json()[0]["scenario_name"]

    # Locations reference
    locations_response = client.get("/api/v1/locations")
    assert locations_response.status_code == 200
    assert len(locations_response.json()) > 0
    assert any(location["country"] == "Philippines" for location in locations_response.json())

    # Workforce team context
    context_response = client.get("/api/v1/workforce/context/scn-001")
    assert context_response.status_code == 200
    assert context_response.json()["scenario_id"] == "scn-001"

    # Analyses list
    analyses_response = client.get("/api/v1/workforce/analyses")
    assert analyses_response.status_code == 200
    assert isinstance(analyses_response.json(), list)
