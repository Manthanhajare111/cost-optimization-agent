from costopt.models.domain import ScenarioAnalysisRequest
from costopt.pipeline.scenario_analysis import analyze_scenario


def test_germany_philippines_analysis_uses_sqlite_data(isolated_db):
    result = analyze_scenario(ScenarioAnalysisRequest(scenario_name="germany-philippines"))

    assert result.scenario_id == "scn-001"
    assert result.squad_id == "squad-payments-platform"
    assert result.retained_count == 5
    assert result.moved_count == 10
    assert result.confidence_score == 0.87
    assert result.costs.monthly_savings > 0
    assert result.costs.annual_savings == result.costs.monthly_savings * 12


def test_analysis_retains_roles_when_target_rates_do_not_create_savings(isolated_db):
    from costopt.storage.sqlite import get_connection

    with get_connection() as connection:
        connection.execute(
            "UPDATE rate_cards SET bill_rate = 2000 "
            "WHERE supplier_id = 'sup-acme-global' AND location_id = 'loc-philippines'"
        )

    result = analyze_scenario(ScenarioAnalysisRequest(scenario_name="germany-philippines"))

    assert result.moved_count == 0
    assert result.costs.monthly_savings == 0
    assert "does not produce a positive savings opportunity" in result.recommendation
