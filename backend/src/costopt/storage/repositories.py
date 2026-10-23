import json
import re
from pathlib import Path
import sqlite3

from costopt.models.domain import (
    ContractClause,
    ContractListItem,
    ContractRecord,
    Location,
    RateCard,
    Resource,
    ScenarioContext,
    ScenarioListItem,
    Squad,
    SquadListItem,
)
from costopt.storage.sqlite import get_connection
from costopt.observability.logging import get_logger


SCENARIO_ALIASES = {
    "germany-philippines": "germany-to-philippines-right-shoring",
    "germany-to-philippines": "germany-to-philippines-right-shoring",
    "germany-philippines-right-shoring": "germany-to-philippines-right-shoring",
    "germany-india": "germany-to-philippines-right-shoring",
    "germany-to-india": "germany-to-philippines-right-shoring",
    "germany-india-right-shoring": "germany-to-philippines-right-shoring",
    "germany-to-india-right-shoring": "germany-to-philippines-right-shoring",
}
logger = get_logger(__name__)


def list_squads() -> list[SquadListItem]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                s.squad_id,
                s.name,
                s.business_unit,
                COUNT(r.resource_id) AS resource_count,
                COUNT(DISTINCT r.supplier_id) AS supplier_count
            FROM squads s
            LEFT JOIN resources r ON r.squad_id = s.squad_id
            GROUP BY s.squad_id, s.name, s.business_unit
            ORDER BY s.name
            """
        ).fetchall()
    return [SquadListItem.model_validate(row) for row in rows]


def list_scenarios() -> list[ScenarioListItem]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                os.scenario_id,
                os.squad_id,
                s.name AS squad_name,
                os.target_location_id,
                l.country AS target_location_name,
                os.baseline_cost,
                os.future_cost,
                os.monthly_savings,
                os.annual_savings,
                os.assumptions,
                os.created_at
            FROM optimization_scenarios os
            JOIN squads s ON s.squad_id = os.squad_id
            JOIN locations l ON l.location_id = os.target_location_id
            ORDER BY os.scenario_id
            """
        ).fetchall()

    items: list[ScenarioListItem] = []
    for row in rows:
        assumptions = _parse_json_text(row["assumptions"])
        items.append(
            ScenarioListItem.model_validate(
                {
                    "scenario_id": row["scenario_id"],
                    "scenario_name": assumptions.get("scenario_name", row["scenario_id"]),
                    "squad_id": row["squad_id"],
                    "squad_name": row["squad_name"],
                    "target_location_id": row["target_location_id"],
                    "target_location_name": row["target_location_name"],
                    "baseline_cost": row["baseline_cost"],
                    "future_cost": row["future_cost"],
                    "monthly_savings": row["monthly_savings"],
                    "annual_savings": row["annual_savings"],
                    "created_at": row["created_at"],
                }
            )
        )
    return items


def list_locations() -> list[Location]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT location_id, country, region, cost_index, is_offshore
            FROM locations
            ORDER BY country
            """
        ).fetchall()
    return [Location.model_validate(_coerce_location_row(row)) for row in rows]


def list_contracts() -> list[ContractListItem]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                c.contract_id,
                c.supplier_id,
                s.name AS supplier_name,
                c.document_uri,
                c.contract_type,
                c.offshore_permitted,
                c.data_residency_restriction,
                c.customer_approval_required,
                c.created_at
            FROM contracts c
            JOIN suppliers s ON s.supplier_id = c.supplier_id
            ORDER BY c.contract_id
            """
        ).fetchall()
    return [
        ContractListItem.model_validate(
            {
                **row,
                "offshore_permitted": bool(row["offshore_permitted"]),
                "customer_approval_required": bool(row["customer_approval_required"]),
            }
        )
        for row in rows
    ]


def load_scenario_context(
    scenario_name: str | None = None,
    target_location_id: str | None = None,
    scenario_id: str | None = None,
) -> ScenarioContext:
    logger.info(
        "Scenario context loading started",
        extra={
            "event": "scenario_context_loading_started",
            "scenario_id": scenario_id,
            "scenario_name": scenario_name,
            "requested_target_location": target_location_id,
        },
    )
    with get_connection() as connection:
        scenario_row = _find_scenario(connection, scenario_name, scenario_id)
        assumptions = _parse_json_text(scenario_row["assumptions"])

        squad_row = connection.execute(
            "SELECT squad_id, name, business_unit FROM squads WHERE squad_id = ?",
            (scenario_row["squad_id"],),
        ).fetchone()
        if squad_row is None:
            raise ValueError(f"Unknown squad_id: {scenario_row['squad_id']}")

        resource_rows = connection.execute(
            """
            SELECT
                resource_id,
                supplier_id,
                squad_id,
                current_location_id,
                role,
                skill,
                current_rate,
                pii_access,
                availability
            FROM resources
            WHERE squad_id = ?
            ORDER BY resource_id
            """,
            (scenario_row["squad_id"],),
        ).fetchall()
        if not resource_rows:
            raise ValueError(f"No resources found for squad_id: {scenario_row['squad_id']}")

        resources = [Resource.model_validate(_coerce_resource_row(row)) for row in resource_rows]
        current_location_ids = sorted({resource.current_location_id for resource in resources})
        declared_location_values = assumptions.get("current_location_ids")
        if isinstance(declared_location_values, list):
            declared_current_locations = {str(item) for item in declared_location_values}
        elif assumptions.get("current_location_id"):
            declared_current_locations = {str(assumptions["current_location_id"])}
        else:
            declared_current_locations = set()
        if declared_current_locations and declared_current_locations != set(current_location_ids):
            raise ValueError(
                "Scenario assumptions do not match the current locations on its resources."
            )
        resolved_target_location_id = _resolve_location_id(
            connection,
            str(target_location_id or scenario_row["target_location_id"]),
        )

        location_ids = sorted({*current_location_ids, resolved_target_location_id})
        location_placeholders = ", ".join("?" for _ in location_ids)
        location_rows = connection.execute(
            f"""
            SELECT location_id, country, region, cost_index, is_offshore
            FROM locations
            WHERE location_id IN ({location_placeholders})
            ORDER BY location_id
            """,
            location_ids,
        ).fetchall()
        if len(location_rows) != len(location_ids):
            raise ValueError("Scenario references a location that does not exist in test.db.")

        supplier_ids = sorted({resource.supplier_id for resource in resources})
        supplier_placeholders = ", ".join("?" for _ in supplier_ids)
        rate_card_rows = connection.execute(
            f"""
            SELECT rate_card_id, supplier_id, location_id, role, bill_rate, currency
            FROM rate_cards
            WHERE supplier_id IN ({supplier_placeholders}) AND location_id = ?
            ORDER BY rate_card_id
            """,
            (*supplier_ids, resolved_target_location_id),
        ).fetchall()
        rate_cards = [RateCard.model_validate(row) for row in rate_card_rows]

        contract_rows = connection.execute(
            f"""
            SELECT
                contract_id,
                supplier_id,
                document_uri,
                contract_type,
                offshore_permitted,
                data_residency_restriction,
                customer_approval_required
            FROM contracts
            WHERE supplier_id IN ({supplier_placeholders})
            ORDER BY supplier_id, contract_id
            """,
            supplier_ids,
        ).fetchall()
        contract_rows_by_supplier = {
            supplier_id: [
                row for row in contract_rows if str(row["supplier_id"]) == supplier_id
            ]
            for supplier_id in supplier_ids
        }
        for supplier_id, rows in contract_rows_by_supplier.items():
            if not rows:
                raise ValueError(f"No contract found for supplier_id: {supplier_id}")
            if len(rows) > 1:
                raise ValueError(
                    f"Multiple contracts found for supplier_id={supplier_id}; "
                    "an active contract version must be selected explicitly."
                )

        selected_contract_rows = [
            contract_rows_by_supplier[supplier_id][0] for supplier_id in supplier_ids
        ]
        contract_ids = [str(row["contract_id"]) for row in selected_contract_rows]
        contract_placeholders = ", ".join("?" for _ in contract_ids)

        clause_rows = connection.execute(
            f"""
            SELECT clause_id, contract_id, clause_type, clause_text
            FROM contract_clauses
            WHERE contract_id IN ({contract_placeholders})
            ORDER BY contract_id, clause_id
            """,
            contract_ids,
        ).fetchall()

    contracts = [
        ContractRecord(
            contract_id=str(row["contract_id"]),
            supplier_id=str(row["supplier_id"]),
            document_name=Path(str(row["document_uri"])).name,
            contract_type=str(row["contract_type"]),
            offshore_permitted=bool(row["offshore_permitted"]),
            data_residency_restriction=row["data_residency_restriction"],
            customer_approval_required=bool(row["customer_approval_required"]),
        )
        for row in selected_contract_rows
    ]
    currency = str(assumptions.get("currency", "EUR")).upper()
    rate_currencies = {rate_card.currency.upper() for rate_card in rate_cards}
    if rate_currencies and rate_currencies != {currency}:
        raise ValueError(
            f"Scenario currency {currency} does not match target rate-card currencies: "
            + ", ".join(sorted(rate_currencies))
        )

    context = ScenarioContext(
        scenario_id=str(scenario_row["scenario_id"]),
        scenario_name=str(assumptions.get("scenario_name", squad_row["name"])),
        currency=currency,
        billing_units_per_month=float(assumptions.get("billing_units_per_month", 10.14)),
        current_location_ids=current_location_ids,
        target_location_id=resolved_target_location_id,
        squad=Squad.model_validate(squad_row),
        resources=resources,
        rate_cards=rate_cards,
        contracts=contracts,
        clauses=[ContractClause.model_validate(row) for row in clause_rows],
        locations=[Location.model_validate(_coerce_location_row(row)) for row in location_rows],
        assumptions=assumptions,
    )
    logger.info(
        "Scenario context loading completed",
        extra={
            "event": "scenario_context_loading_completed",
            "scenario_id": context.scenario_id,
            "resource_count": len(context.resources),
            "supplier_count": len(context.contracts),
            "target_location_id": context.target_location_id,
        },
    )
    return context


def _find_scenario(
    connection: sqlite3.Connection,
    scenario_name: str | None,
    scenario_id: str | None,
) -> dict[str, object]:
    rows = connection.execute(
        """
        SELECT scenario_id, squad_id, target_location_id, assumptions
        FROM optimization_scenarios
        ORDER BY scenario_id
        """
    ).fetchall()
    resolved_id = scenario_id.strip() if scenario_id else None
    if not resolved_id and scenario_name and re.fullmatch(r"scn-\d+", scenario_name.strip().lower()):
        resolved_id = scenario_name.strip().lower()

    if resolved_id:
        match = next((row for row in rows if str(row["scenario_id"]) == resolved_id), None)
        if match is None:
            raise ValueError(f"Unknown scenario_id: {resolved_id}")
        if scenario_name and not re.fullmatch(r"scn-\d+", scenario_name.strip().lower()):
            candidate = str(_parse_json_text(match["assumptions"]).get("scenario_name", ""))
            if _normalize_scenario_name(candidate) != _normalize_scenario_name(scenario_name):
                raise ValueError("scenario_id and scenario_name refer to different scenarios.")
        return match

    normalized_name = _normalize_scenario_name(scenario_name or "")
    for row in rows:
        assumptions = _parse_json_text(row["assumptions"])
        candidate = str(assumptions.get("scenario_name", ""))
        if _normalize_scenario_name(candidate) == normalized_name:
            return row
    raise ValueError(f"Unknown scenario_name: {scenario_name}")


def _resolve_location_id(connection: sqlite3.Connection, requested_location: str) -> str:
    rows = connection.execute(
        "SELECT location_id, country FROM locations ORDER BY location_id"
    ).fetchall()
    normalized = _normalize_scenario_name(requested_location)
    matches = [
        str(row["location_id"])
        for row in rows
        if str(row["location_id"]).lower() == requested_location.lower()
        or _normalize_scenario_name(str(row["country"])) == normalized
        or _normalize_scenario_name(str(row["location_id"]).removeprefix("loc-")) == normalized
    ]
    if not matches:
        raise ValueError(f"Unknown target location: {requested_location}")
    if len(matches) > 1:
        raise ValueError(f"Ambiguous target location: {requested_location}")
    return matches[0]


def _normalize_scenario_name(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return SCENARIO_ALIASES.get(normalized, normalized)


def _parse_json_text(value: object) -> dict[str, object]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    return json.loads(str(value))


def _coerce_resource_row(row: dict[str, object]) -> dict[str, object]:
    payload = dict(row)
    payload["pii_access"] = bool(payload.get("pii_access"))
    return payload


def _coerce_location_row(row: dict[str, object]) -> dict[str, object]:
    payload = dict(row)
    payload["is_offshore"] = bool(payload.get("is_offshore"))
    return payload
