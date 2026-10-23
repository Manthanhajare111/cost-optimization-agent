import json

import pytest

import costopt.storage.agent_run_store as agent_run_store
from costopt.models.domain import AgentRunResult, ScenarioAnalysisRequest
from costopt.pipeline.orchestrator import run_scenario
from costopt.storage.agent_run_store import (
    POLICY_VERSION,
    SNAPSHOT_SCHEMA_VERSION,
    get_agent_run,
    save_agent_run,
)
from costopt.storage.sqlite import get_connection


def test_agent_run_store_persists_the_full_audit_record(isolated_db):
    run = run_scenario(ScenarioAnalysisRequest(scenario_name="germany-philippines"))

    persisted = save_agent_run(run)

    assert persisted.run_id is not None
    loaded = get_agent_run(persisted.run_id)
    assert loaded == persisted

    with get_connection() as connection:
        audit = connection.execute(
            "SELECT scenario_run_id, llm_provider FROM agent_run_audits WHERE run_id = ?",
            (persisted.run_id,),
        ).fetchone()
        assert audit is not None
        assert audit["llm_provider"] == "mixed"
        scenario_run_id = audit["scenario_run_id"]
        scenario_run = connection.execute(
            "SELECT policy_version FROM scenario_runs WHERE scenario_run_id = ?",
            (scenario_run_id,),
        ).fetchone()
        assert scenario_run["policy_version"] == POLICY_VERSION
        assert connection.execute(
            "SELECT COUNT(*) AS count FROM scenario_input_snapshots WHERE scenario_run_id = ?",
            (scenario_run_id,),
        ).fetchone()["count"] == 2
        assert connection.execute(
            "SELECT COUNT(*) AS count FROM agent_run_stages WHERE run_id = ?", (persisted.run_id,)
        ).fetchone()["count"] == len(persisted.stages)
        assert connection.execute(
            "SELECT COUNT(*) AS count FROM approval_requests WHERE scenario_run_id = ?",
            (scenario_run_id,),
        ).fetchone()["count"] == 1
        snapshot_row = connection.execute(
            "SELECT payload_json FROM scenario_input_snapshots "
            "WHERE scenario_run_id = ? AND snapshot_type = 'scenario_input'",
            (scenario_run_id,),
        ).fetchone()

    snapshot = json.loads(snapshot_row["payload_json"])
    assert snapshot["scenario_id"] == "scn-001"
    assert snapshot["contract"]["contract_id"] == "ctr-001"
    assert len(snapshot["resources"]) == 15
    assert snapshot["rate_cards"]
    assert "resource_decisions" not in snapshot
    with get_connection() as connection:
        snapshot_schema = connection.execute(
            "SELECT schema_version FROM scenario_input_snapshots "
            "WHERE scenario_run_id = ? AND snapshot_type = 'scenario_input'",
            (scenario_run_id,),
        ).fetchone()
    assert snapshot_schema["schema_version"] == SNAPSHOT_SCHEMA_VERSION


def test_agent_run_persistence_is_atomic(isolated_db, monkeypatch):
    run = run_scenario(ScenarioAnalysisRequest(scenario_name="germany-philippines"))

    def fail_snapshot(*args, **kwargs):
        raise RuntimeError("snapshot write failed")

    monkeypatch.setattr(agent_run_store, "_save_snapshot", fail_snapshot)

    with pytest.raises(RuntimeError, match="snapshot write failed"):
        save_agent_run(run)

    with get_connection() as connection:
        assert connection.execute(
            "SELECT COUNT(*) AS count FROM recommendation_runs"
        ).fetchone()["count"] == 0
        assert connection.execute(
            "SELECT COUNT(*) AS count FROM scenario_runs"
        ).fetchone()["count"] == 0
        assert connection.execute(
            "SELECT COUNT(*) AS count FROM agent_run_audits"
        ).fetchone()["count"] == 0
