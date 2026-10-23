import re
import sqlite3
from datetime import UTC, datetime

from costopt.models.domain import (
    RecommendationListItem,
    RecommendationRecord,
    ScenarioAnalysisResult,
)
from costopt.storage.sqlite import get_connection


def save_recommendation(result: ScenarioAnalysisResult) -> RecommendationRecord:
    with get_connection() as connection:
        return upsert_recommendation(connection, result)


def upsert_recommendation(
    connection: sqlite3.Connection,
    result: ScenarioAnalysisResult,
) -> RecommendationRecord:
    """Persist a recommendation using the caller's transaction."""
    recommendation_id = _build_recommendation_id(
        scenario_name=result.scenario_name,
        squad_id=result.squad_id,
        target_location_id=result.target_location_id,
    )
    now = datetime.now(UTC)
    existing_row = connection.execute(
        "SELECT payload_json FROM recommendation_runs WHERE recommendation_id = ?",
        (recommendation_id,),
    ).fetchone()
    existing = (
        RecommendationRecord.model_validate_json(existing_row["payload_json"])
        if existing_row is not None
        else None
    )
    created_at = existing.created_at if existing is not None else now

    record = RecommendationRecord(
        recommendation_id=recommendation_id,
        created_at=created_at,
        updated_at=now,
        **result.model_dump(),
    )

    connection.execute(
        """
        INSERT INTO recommendation_runs (
            recommendation_id,
            scenario_id,
            scenario_name,
            squad_id,
            target_location_id,
            payload_json,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(recommendation_id) DO UPDATE SET
            scenario_id = excluded.scenario_id,
            scenario_name = excluded.scenario_name,
            squad_id = excluded.squad_id,
            target_location_id = excluded.target_location_id,
            payload_json = excluded.payload_json,
            updated_at = excluded.updated_at
        """,
        (
            record.recommendation_id,
            record.scenario_id,
            record.scenario_name,
            record.squad_id,
            record.target_location_id,
            record.model_dump_json(),
            record.created_at.isoformat(),
            record.updated_at.isoformat(),
        ),
    )
    return record


def list_recommendations() -> list[RecommendationListItem]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT payload_json
            FROM recommendation_runs
            ORDER BY updated_at DESC
            """
        ).fetchall()
    records = [RecommendationRecord.model_validate_json(row["payload_json"]) for row in rows]
    return [
        RecommendationListItem(
            recommendation_id=record.recommendation_id,
            scenario_id=record.scenario_id,
            scenario_name=record.scenario_name,
            squad_name=record.squad_name,
            target_location_id=record.target_location_id,
            confidence_score=record.confidence_score,
            monthly_savings=record.costs.monthly_savings,
            annual_savings=record.costs.annual_savings,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
        for record in records
    ]


def get_recommendation(recommendation_id: str) -> RecommendationRecord | None:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT payload_json
            FROM recommendation_runs
            WHERE recommendation_id = ?
            """,
            (recommendation_id,),
        ).fetchone()
    if row is None:
        return None
    return RecommendationRecord.model_validate_json(row["payload_json"])


def _build_recommendation_id(
    scenario_name: str,
    squad_id: str,
    target_location_id: str,
) -> str:
    slug = _slugify(scenario_name)
    return f"rec-{slug}-{squad_id}-{target_location_id}"


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
