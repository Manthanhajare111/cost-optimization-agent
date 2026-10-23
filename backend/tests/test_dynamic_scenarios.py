import logging

from fastapi.testclient import TestClient

from costopt.api.app import create_app
from costopt.models.domain import ScenarioAnalysisRequest
from costopt.pipeline.orchestrator import run_scenario
from costopt.pipeline.workforce_graph import run_workforce_graph
from costopt.storage.repositories import load_scenario_context
from costopt.storage.sqlite import get_connection


def test_context_and_graph_support_multiple_suppliers(isolated_db):
    with get_connection() as connection:
        connection.execute(
            "UPDATE resources SET supplier_id = 'sup-bluewave-tech' WHERE resource_id = 'res-006'"
        )

    context = load_scenario_context(scenario_id="scn-001")
    state = run_workforce_graph(ScenarioAnalysisRequest(scenario_id="scn-001"))

    assert {contract.supplier_id for contract in context.contracts} == {
        "sup-acme-global",
        "sup-bluewave-tech",
    }
    assert set(state["compliance"].supplier_assessments) == {
        "sup-acme-global",
        "sup-bluewave-tech",
    }
    decision = next(
        item for item in state["recommendation"].resource_decisions if item.resource_id == "res-006"
    )
    assert decision.supplier_id == "sup-bluewave-tech"
    assert decision.action == "move"
    assert decision.projected_rate == 468.0


def test_blocked_supplier_is_retained_without_blocking_other_suppliers(isolated_db):
    with get_connection() as connection:
        connection.execute(
            "UPDATE resources SET supplier_id = 'sup-bluewave-tech' WHERE resource_id = 'res-006'"
        )
        connection.execute(
            "UPDATE contracts SET offshore_permitted = 0 WHERE supplier_id = 'sup-bluewave-tech'"
        )
        connection.execute(
            "UPDATE contract_clauses SET clause_text = "
            "'Offshore delivery is not permitted under this agreement.' "
            "WHERE contract_id = 'ctr-002' AND clause_type = 'offshore_delivery'"
        )

    state = run_workforce_graph(ScenarioAnalysisRequest(scenario_id="scn-001"))

    assert state["compliance"].outcome == "allowed_with_approval"
    assert state["compliance"].movement_permitted_for("sup-acme-global") is True
    assert state["compliance"].movement_permitted_for("sup-bluewave-tech") is False
    decisions = state["recommendation"].resource_decisions
    assert next(item for item in decisions if item.resource_id == "res-006").action == "retain"
    assert any(item.action == "move" for item in decisions if item.supplier_id == "sup-acme-global")


def test_offshore_prohibition_does_not_block_a_non_offshore_target(isolated_db):
    with get_connection() as connection:
        connection.execute(
            "UPDATE contracts SET offshore_permitted = 0 WHERE supplier_id = 'sup-acme-global'"
        )
        connection.execute(
            "UPDATE contract_clauses SET clause_text = "
            "'Offshore delivery is not permitted under this agreement.' "
            "WHERE contract_id = 'ctr-001' AND clause_type = 'offshore_delivery'"
        )

    state = run_workforce_graph(
        ScenarioAnalysisRequest(scenario_id="scn-001", target_location_id="Poland")
    )

    assert state["compliance"].movement_permitted is True
    assert state["recommendation"].target_location_id == "loc-poland"
    assert state["recommendation"].moved_count > 0


def test_missing_rate_cards_create_review_instead_of_unsafe_estimates(isolated_db):
    result = run_scenario(ScenarioAnalysisRequest(scenario_id="scn-005"))

    assert result.recommendation.moved_count == 0
    assert result.recommendation.costs.annual_savings == 0
    assert result.recommendation.data_quality_issues
    assert result.requires_human_review is True
    assert any("Missing rate card" in reason for reason in result.review_reasons)


def test_scenario_request_requires_an_identifier(isolated_db):
    client = TestClient(create_app())

    response = client.post("/api/v1/scenarios/run", json={})

    assert response.status_code == 422


def test_important_runtime_actions_emit_lifecycle_logs(isolated_db, caplog):
    caplog.set_level(logging.INFO)

    run_scenario(ScenarioAnalysisRequest(scenario_id="scn-001"))

    messages = {record.getMessage() for record in caplog.records}
    assert "Scenario orchestration started" in messages
    assert "Scenario context loading started" in messages
    assert "Compliance assessment started" in messages
    assert "Workforce optimization completed" in messages
    assert "Workforce graph completed" in messages
