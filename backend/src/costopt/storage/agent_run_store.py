"""Durable, normalized local audit storage for LangGraph workforce runs."""

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from uuid import uuid4

from costopt.models.domain import AgentRunResult
from costopt.storage.recommendation_store import upsert_recommendation
from costopt.storage.sqlite import get_connection
from costopt.observability.logging import get_logger


POLICY_VERSION = "workforce_policy_v3_ten_agent"
SNAPSHOT_SCHEMA_VERSION = "agent_run_v3"
logger = get_logger(__name__)


def save_agent_run(run: AgentRunResult) -> AgentRunResult:
    if run.input_snapshot is None:
        raise ValueError("Agent run is missing its verified scenario input snapshot.")

    run_id = str(uuid4())
    scenario_run_id = str(uuid4())
    now = datetime.now(UTC).isoformat()
    input_snapshot = run.input_snapshot.model_dump_json()
    logger.info(
        "Agent run persistence started",
        extra={
            "event": "agent_run_persistence_started",
            "run_id": run_id,
            "scenario_id": run.recommendation.scenario_id,
        },
    )
    with get_connection() as connection:
        recommendation = upsert_recommendation(connection, run.recommendation)
        persisted = run.model_copy(
            update={
                "run_id": run_id,
                "recommendation_id": recommendation.recommendation_id,
                "input_snapshot": None,
            }
        )
        scenario_status = (
            "human_review_required" if persisted.requires_human_review else "completed"
        )
        payload_json = persisted.model_dump_json()
        connection.execute(
            """
            INSERT INTO scenario_runs (
                scenario_run_id, scenario_id, status, policy_version, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                scenario_run_id,
                persisted.recommendation.scenario_id,
                scenario_status,
                POLICY_VERSION,
                now,
            ),
        )
        _save_snapshot(connection, scenario_run_id, "scenario_input", input_snapshot, now)
        _save_snapshot(connection, scenario_run_id, "recommendation_output", payload_json, now)
        connection.execute(
            """
            INSERT INTO agent_run_audits (
                run_id, scenario_run_id, scenario_id, scenario_name, llm_provider,
                requires_human_review, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                scenario_run_id,
                persisted.recommendation.scenario_id,
                persisted.recommendation.scenario_name,
                _run_provider(persisted),
                int(persisted.requires_human_review),
                payload_json,
                now,
            ),
        )
        for sequence_number, stage in enumerate(persisted.stages, start=1):
            connection.execute(
                """
                INSERT INTO agent_run_stages (
                    stage_id, run_id, sequence_number, stage_name, status, outcome, prompt_key, model,
                    used_fallback, narrative_json, tool_traces_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid4()),
                    run_id,
                    sequence_number,
                    stage.name,
                    stage.status,
                    stage.outcome,
                    stage.llm.prompt_key,
                    stage.llm.model or None,
                    int(stage.used_fallback),
                    stage.narrative.model_dump_json(),
                    json.dumps([trace.model_dump() for trace in stage.tool_traces]),
                    now,
                ),
            )
        if persisted.requires_human_review:
            connection.execute(
                """
                INSERT INTO approval_requests (
                    approval_request_id, scenario_run_id, status, requested_at, rationale
                ) VALUES (?, ?, 'pending', ?, ?)
                """,
                (
                    str(uuid4()),
                    scenario_run_id,
                    now,
                    " ".join(persisted.review_reasons) or "Human review is required before execution.",
                ),
            )
    logger.info(
        "Agent run persistence completed",
        extra={
            "event": "agent_run_persistence_completed",
            "run_id": run_id,
            "recommendation_id": persisted.recommendation_id,
            "requires_human_review": persisted.requires_human_review,
        },
    )
    return persisted


def get_agent_run(run_id: str) -> AgentRunResult | None:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT payload_json FROM agent_run_audits WHERE run_id = ?", (run_id,)
        ).fetchone()
    if row is None:
        return None
    return AgentRunResult.model_validate_json(row["payload_json"])


def _save_snapshot(
    connection: sqlite3.Connection,
    scenario_run_id: str,
    snapshot_type: str,
    payload_json: str,
    now: str,
) -> None:
    connection.execute(
        """
        INSERT INTO scenario_input_snapshots (
            snapshot_id, scenario_run_id, snapshot_type, schema_version, content_checksum, payload_json,
            created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(uuid4()),
            scenario_run_id,
            snapshot_type,
            SNAPSHOT_SCHEMA_VERSION,
            hashlib.sha256(payload_json.encode("utf-8")).hexdigest(),
            payload_json,
            now,
        ),
    )


def _run_provider(run: AgentRunResult) -> str:
    providers = {
        "deterministic_fallback" if stage.used_fallback else stage.llm.provider
        for stage in run.stages
    }
    return next(iter(providers)) if len(providers) == 1 else "mixed"
