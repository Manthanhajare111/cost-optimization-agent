import sqlite3

from costopt.models.domain import ScenarioAnalysisRequest
from costopt.pipeline.scenario_analysis import analyze_scenario
from costopt.storage.recommendation_store import (
    get_recommendation,
    list_recommendations,
    save_recommendation,
)


def test_recommendation_store_persists_to_sqlite(isolated_db):
    result = analyze_scenario(ScenarioAnalysisRequest(scenario_name="germany-philippines"))
    saved = save_recommendation(result)

    assert saved.recommendation_id.startswith("rec-germany-to-philippines-right-shoring")

    backlog = list_recommendations()
    assert len(backlog) == 1
    assert backlog[0].scenario_id == "scn-001"

    detail = get_recommendation(saved.recommendation_id)
    assert detail is not None
    assert detail.recommendation_id == saved.recommendation_id
    assert detail.costs.monthly_savings == 42794.86

    with sqlite3.connect(isolated_db) as connection:
        count = connection.execute("SELECT COUNT(*) FROM recommendation_runs").fetchone()[0]
    assert count == 1
