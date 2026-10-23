from types import SimpleNamespace
from unittest.mock import patch

import pytest
from langchain_core.callbacks import BaseCallbackHandler
from pydantic import SecretStr

from costopt.models.domain import ScenarioAnalysisRequest
from costopt.pipeline import workforce_graph
from costopt.pipeline.workforce_graph import get_workforce_graph, run_workforce_graph
from costopt.storage.sqlite import get_connection


def test_workforce_graph_runs_the_allowed_with_approval_path(isolated_db):
    state = run_workforce_graph(ScenarioAnalysisRequest(scenario_name="germany-philippines"))

    assert state["compliance"].outcome == "allowed_with_approval"
    assert state["recommendation"].moved_count == 10
    assert [stage.name for stage in state["stages"]] == [
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
    assert state["requires_human_review"] is True


def test_workforce_graph_routes_blocked_scenarios_to_blocked_recommendation(isolated_db):
    with get_connection() as connection:
        connection.execute(
            "UPDATE contracts SET offshore_permitted = 0 WHERE supplier_id = 'sup-acme-global'"
        )

    state = run_workforce_graph(ScenarioAnalysisRequest(scenario_name="germany-philippines"))

    assert state["compliance"].outcome == "blocked"
    assert state["recommendation"].moved_count == 0
    optimization_stage = next(stage for stage in state["stages"] if stage.name == "optimization")
    assert optimization_stage.outcome == (
        "optimization skipped because contract evidence blocks the target delivery model"
    )


def test_workforce_graph_escalates_missing_contract_evidence(isolated_db):
    with get_connection() as connection:
        connection.execute(
            "DELETE FROM recommendation_evidence WHERE clause_id IN "
            "(SELECT clause_id FROM contract_clauses WHERE contract_id = 'ctr-001' "
            "AND clause_type = 'customer_approval')"
        )
        connection.execute(
            "DELETE FROM contract_clauses WHERE contract_id = 'ctr-001' AND clause_type = 'customer_approval'"
        )

    state = run_workforce_graph(ScenarioAnalysisRequest(scenario_name="germany-philippines"))

    assert state["compliance"].evidence_complete is False
    assert state["compliance"].missing_evidence == ["sup-acme-global:customer_approval"]
    assert state["requires_human_review"] is True
    assert state["recommendation"].moved_count == 0
    assert any("customer_approval" in reason for reason in state["review_reasons"])


def test_workforce_graph_blocks_conflicting_contract_evidence(isolated_db):
    with get_connection() as connection:
        connection.execute(
            "UPDATE contract_clauses SET clause_text = "
            "'Offshore delivery is not permitted under this agreement.' "
            "WHERE contract_id = 'ctr-001' AND clause_type = 'offshore_delivery'"
        )

    state = run_workforce_graph(ScenarioAnalysisRequest(scenario_name="germany-philippines"))

    assert state["compliance"].evidence_complete is False
    assert state["compliance"].evidence_conflicts
    assert state["recommendation"].moved_count == 0
    assert state["requires_human_review"] is True


def test_workforce_graph_exposes_expected_nodes():
    nodes = get_workforce_graph().get_graph().nodes

    assert {
        "load_context",
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
    } <= set(nodes)


def test_langsmith_uses_masked_opt_in_tracer(monkeypatch):
    calls = []
    recommendation = SimpleNamespace(scenario_id="scn-001")

    class GraphStub:
        def invoke(self, state, config):
            calls.append((state, config))
            return {"recommendation": recommendation, "stages": []}

    monkeypatch.setattr(workforce_graph.settings, "langsmith_tracing_enabled", True)
    monkeypatch.setattr(workforce_graph.settings, "langsmith_api_key", SecretStr("test-key"))
    monkeypatch.setattr(workforce_graph, "get_workforce_graph", lambda: GraphStub())
    with patch.object(workforce_graph, "Client") as client, patch.object(
        workforce_graph, "LangChainTracer"
    ) as tracer:
        workforce_graph.run_workforce_graph(ScenarioAnalysisRequest(scenario_id="scn-001"))

    client.assert_called_once_with(
        api_key="test-key", api_url=None, hide_inputs=True,
        hide_outputs=True, hide_metadata=True,
    )
    tracer.assert_called_once_with(project_name="costopt-workforce", client=client.return_value)
    assert calls[0][1]["callbacks"] == [tracer.return_value]


def test_langsmith_opt_in_requires_key(monkeypatch):
    monkeypatch.setattr(workforce_graph.settings, "langsmith_tracing_enabled", True)
    monkeypatch.setattr(workforce_graph.settings, "langsmith_api_key", None)
    with pytest.raises(ValueError, match="LANGSMITH_API_KEY"):
        workforce_graph.run_workforce_graph(ScenarioAnalysisRequest(scenario_id="scn-001"))


def test_explicit_tracer_receives_graph_events_with_ambient_tracing_disabled(isolated_db, monkeypatch):
    class CountingTracer(BaseCallbackHandler):
        def __init__(self):
            self.started = 0

        def on_chain_start(self, serialized, inputs, **kwargs):
            self.started += 1

    tracer = CountingTracer()
    monkeypatch.setattr(workforce_graph.settings, "langsmith_tracing_enabled", True)
    monkeypatch.setattr(workforce_graph.settings, "langsmith_api_key", SecretStr("test-key"))
    with patch.object(workforce_graph, "Client"), patch.object(
        workforce_graph, "LangChainTracer", return_value=tracer
    ):
        state = workforce_graph.run_workforce_graph(
            ScenarioAnalysisRequest(scenario_name="germany-philippines")
        )
    assert len(state["stages"]) == 10
    assert tracer.started >= 10
