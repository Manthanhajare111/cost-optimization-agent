import sqlite3

from costopt.storage.repositories import list_contracts, list_scenarios, list_squads


def test_database_row_counts(isolated_db):
    expected = {
        "suppliers": 20,
        "locations": 21,
        "squads": 20,
        "categories": 20,
        "users": 20,
        "resources": 110,
        "rate_cards": 500,
        "contracts": 20,
        "purchase_orders": 60,
        "procurement_contracts": 20,
        "contract_clauses": 60,
        "optimization_scenarios": 20,
        "invoices": 40,
        "recommendations": 20,
        "procurement_recommendations": 20,
        "recommendation_evidence": 60,
        "audit_log": 60,
    }

    with sqlite3.connect(isolated_db) as connection:
        actual = {
            table_name: connection.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
            for table_name in expected
        }

    assert actual == expected


def test_reference_repositories_return_seeded_rows(isolated_db):
    squads = list_squads()
    scenarios = list_scenarios()
    contracts = list_contracts()

    assert len(squads) == 20
    assert len(scenarios) == 20
    assert len(contracts) == 20
    assert scenarios[0].scenario_name == "Germany to Philippines right-shoring"
    assert contracts[0].contract_id == "ctr-001"


def test_all_seeded_scenarios_are_enabled_for_analysis(isolated_db):
    from costopt.storage.repositories import load_scenario_context

    context = load_scenario_context("Core Banking QA Squad to loc-poland scenario")

    assert context.scenario_id == "scn-002"
    assert context.target_location_id == "loc-poland"
