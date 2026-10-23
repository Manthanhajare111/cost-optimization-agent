"""Idempotent ingestion of approved, sanitized SAP API sample payloads."""

from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from costopt.config import settings
from costopt.integrations.sap.models import (
    AribaContractWorkspaceResponse,
    AribaPurchaseOrderResponse,
    FieldglassBusinessUnitResponse,
    FieldglassWorkerPayload,
    SapImportSummary,
    SapIngestionStatus,
    SapLatestRun,
)
from costopt.models.domain import Resource
from costopt.observability.logging import get_logger
from costopt.storage.migrations import apply_migrations
from costopt.storage.sqlite import get_connection


logger = get_logger(__name__)
_SUPPORTED_SOURCES = {"all", "fieldglass", "ariba"}
_SUPPORTED_DATA_ORIGINS = {"captured_sample", "synthetic_fixture"}
_STAGING_TABLES = (
    "sap_fieldglass_workers",
    "sap_fieldglass_business_units",
    "sap_ariba_purchase_orders",
    "sap_ariba_contract_workspaces",
)
_CANONICAL_TABLES = ("resources",)


def ingest_sap_samples(
    source: str = "all",
    samples_dir: Path | None = None,
    data_origin: str = "captured_sample",
) -> SapImportSummary:
    """Stage approved SAP samples and promote complete worker mappings to canonical resources."""
    requested_source = source.casefold().strip()
    if requested_source not in _SUPPORTED_SOURCES:
        raise ValueError("source must be one of: all, fieldglass, ariba")
    if data_origin not in _SUPPORTED_DATA_ORIGINS:
        raise ValueError("data_origin must be one of: captured_sample, synthetic_fixture")
    root = (samples_dir or settings.sap_source_samples_dir).resolve()
    inventory_path = root / "api_inventory.csv"
    if not inventory_path.is_file():
        raise FileNotFoundError(f"SAP API inventory not found: {inventory_path}")

    inventory = _read_inventory(inventory_path, requested_source)
    if not inventory:
        raise ValueError(f"No SAP API inventory entries found for source={requested_source}.")

    with get_connection() as connection:
        apply_migrations(connection)

    run_id = str(uuid4())
    started_at = _now()
    counters = {
        "payload_file_count": 0,
        "imported_payload_count": 0,
        "skipped_payload_count": 0,
        "error_count": 0,
    }
    staged_record_counts = {table: 0 for table in _STAGING_TABLES}
    canonical_record_counts = {table: 0 for table in _CANONICAL_TABLES}
    unresolved_record_counts = {"fieldglass_workers": 0}
    logger.info(
        "SAP sample ingestion started",
        extra={
            "event": "sap_sample_ingestion_started",
            "ingestion_run_id": run_id,
            "requested_source": requested_source,
            "data_origin": data_origin,
            "endpoint_count": len(inventory),
        },
    )

    try:
        with get_connection() as connection:
            connection.execute(
                """
                INSERT INTO sap_ingestion_runs (
                    ingestion_run_id, requested_source, data_origin, status,
                    endpoint_count, started_at
                ) VALUES (?, ?, ?, 'running', ?, ?)
                """,
                (run_id, requested_source, data_origin, len(inventory), started_at),
            )
            for row in inventory:
                _register_endpoint(connection, row, started_at)
                api_dir = root / row["relative_folder"]
                for payload_path in _payload_files(api_dir):
                    counters["payload_file_count"] += 1
                    _ingest_payload(
                        connection,
                        run_id,
                        root,
                        row,
                        payload_path,
                        counters,
                        staged_record_counts,
                        canonical_record_counts,
                        unresolved_record_counts,
                        started_at,
                        data_origin,
                    )

            status = "completed_with_errors" if counters["error_count"] else "completed"
            completed_at = _now()
            connection.execute(
                """
                UPDATE sap_ingestion_runs
                SET status = ?, payload_file_count = ?, imported_payload_count = ?,
                    skipped_payload_count = ?, error_count = ?, completed_at = ?
                WHERE ingestion_run_id = ?
                """,
                (
                    status,
                    counters["payload_file_count"],
                    counters["imported_payload_count"],
                    counters["skipped_payload_count"],
                    counters["error_count"],
                    completed_at,
                    run_id,
                ),
            )
    except Exception:
        _record_failed_run(
            run_id,
            requested_source,
            len(inventory),
            started_at,
            data_origin,
        )
        logger.exception(
            "SAP sample ingestion failed",
            extra={
                "event": "sap_sample_ingestion_failed",
                "ingestion_run_id": run_id,
                "requested_source": requested_source,
                "data_origin": data_origin,
            },
        )
        raise

    result = SapImportSummary(
        ingestion_run_id=run_id,
        data_origin=data_origin,
        status=status,
        endpoint_count=len(inventory),
        staged_record_counts=staged_record_counts,
        canonical_record_counts=canonical_record_counts,
        unresolved_record_counts=unresolved_record_counts,
        **counters,
    )
    logger.info(
        "SAP sample ingestion completed",
        extra={
            "event": "sap_sample_ingestion_completed",
            **result.model_dump(
                exclude={
                    "staged_record_counts",
                    "canonical_record_counts",
                    "unresolved_record_counts",
                }
            ),
            "staged_record_counts": staged_record_counts,
            "canonical_record_counts": canonical_record_counts,
            "unresolved_record_counts": unresolved_record_counts,
        },
    )
    return result


def get_sap_ingestion_status() -> SapIngestionStatus:
    """Return aggregate SAP ingestion and staging status for operations and Swagger."""
    with get_connection() as connection:
        if not _table_exists(connection, "sap_ingestion_runs"):
            return SapIngestionStatus(
                configured_endpoint_count=0,
                raw_payload_count=0,
                staging_counts={table: 0 for table in _STAGING_TABLES},
                canonical_counts={table: 0 for table in _CANONICAL_TABLES},
            )
        configured_endpoint_count = connection.execute(
            "SELECT COUNT(*) AS count FROM sap_api_endpoints"
        ).fetchone()["count"]
        raw_payload_count = connection.execute(
            "SELECT COUNT(*) AS count FROM sap_raw_payloads"
        ).fetchone()["count"]
        payload_rows = connection.execute(
            "SELECT payload_kind, COUNT(*) AS count FROM sap_raw_payloads GROUP BY payload_kind"
        ).fetchall()
        origin_rows = connection.execute(
            "SELECT data_origin, COUNT(*) AS count FROM sap_raw_payloads GROUP BY data_origin"
        ).fetchall()
        latest_row = connection.execute(
            """
            SELECT ingestion_run_id, requested_source, data_origin, status, endpoint_count,
                   payload_file_count, imported_payload_count, skipped_payload_count,
                   error_count, started_at, completed_at
            FROM sap_ingestion_runs
            ORDER BY started_at DESC
            LIMIT 1
            """
        ).fetchone()
        staging_counts = {
            table: connection.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()[
                "count"
            ]
            for table in _STAGING_TABLES
        }
        canonical_counts = {
            table: connection.execute(
                "SELECT COUNT(*) AS count FROM sap_source_record_mappings "
                "WHERE canonical_table = ?",
                (table,),
            ).fetchone()["count"]
            for table in _CANONICAL_TABLES
        }
        canonicalization_rows = connection.execute(
            """
            SELECT canonicalization_status, COUNT(*) AS count
            FROM sap_fieldglass_workers
            GROUP BY canonicalization_status
            """
        ).fetchall()
    return SapIngestionStatus(
        configured_endpoint_count=int(configured_endpoint_count),
        raw_payload_count=int(raw_payload_count),
        payload_counts={str(row["payload_kind"]): int(row["count"]) for row in payload_rows},
        origin_counts={str(row["data_origin"]): int(row["count"]) for row in origin_rows},
        staging_counts=staging_counts,
        canonical_counts=canonical_counts,
        canonicalization_counts={
            str(row["canonicalization_status"]): int(row["count"])
            for row in canonicalization_rows
        },
        latest_run=SapLatestRun.model_validate(latest_row) if latest_row else None,
    )


def _read_inventory(path: Path, requested_source: str) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    required = {"source_system", "api_key", "relative_folder", "ppt_name", "method"}
    if not rows or not required.issubset(rows[0]):
        raise ValueError("SAP API inventory is missing required ingestion columns.")
    if requested_source == "all":
        return rows
    return [row for row in rows if row["source_system"].casefold() == requested_source]


def _register_endpoint(connection: sqlite3.Connection, row: dict[str, str], now: str) -> None:
    source_system_id = _source_system_id(row["source_system"])
    connection.execute(
        """
        INSERT INTO sap_source_systems (
            source_system_id, product_name, status, created_at, updated_at
        ) VALUES (?, ?, 'configured', ?, ?)
        ON CONFLICT(source_system_id) DO UPDATE SET
            product_name = excluded.product_name,
            status = excluded.status,
            updated_at = excluded.updated_at
        """,
        (source_system_id, f"SAP {row['source_system']}", now, now),
    )
    connection.execute(
        """
        INSERT INTO sap_api_endpoints (
            api_endpoint_id, source_system_id, api_key, ppt_name, official_api_name,
            api_version, method, endpoint_path, documentation_url, capture_status, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(api_endpoint_id) DO UPDATE SET
            ppt_name = excluded.ppt_name,
            official_api_name = excluded.official_api_name,
            api_version = excluded.api_version,
            method = excluded.method,
            endpoint_path = excluded.endpoint_path,
            documentation_url = excluded.documentation_url,
            capture_status = excluded.capture_status,
            updated_at = excluded.updated_at
        """,
        (
            _endpoint_id(row),
            source_system_id,
            row["api_key"],
            row["ppt_name"],
            _optional_inventory_value(row.get("official_api_name")),
            _optional_inventory_value(row.get("version")),
            row["method"],
            row.get("endpoint") or None,
            _optional_inventory_value(row.get("documentation_url")),
            row.get("capture_status", "Not captured"),
            now,
        ),
    )


def _ingest_payload(
    connection: sqlite3.Connection,
    run_id: str,
    root: Path,
    inventory_row: dict[str, str],
    path: Path,
    counters: dict[str, int],
    staged_record_counts: dict[str, int],
    canonical_record_counts: dict[str, int],
    unresolved_record_counts: dict[str, int],
    now: str,
    data_origin: str,
) -> None:
    content = path.read_text(encoding="utf-8", errors="replace")
    checksum = hashlib.sha256(content.encode("utf-8")).hexdigest()
    endpoint_id = _endpoint_id(inventory_row)
    source_file = path.relative_to(root).as_posix()
    content_type = "application/json" if path.suffix.casefold() == ".json" else "text/html"
    payload_kind = _payload_kind(path.name)
    parsed: Any = None
    validation_status = "unvalidated"
    if content_type == "application/json":
        try:
            parsed = json.loads(content)
            validation_status = "valid"
        except json.JSONDecodeError as exc:
            validation_status = "invalid"
            counters["error_count"] += 1
            parsed = None

    existing = connection.execute(
        """
        SELECT raw_payload_id FROM sap_raw_payloads
        WHERE api_endpoint_id = ? AND source_file = ? AND content_checksum = ?
        """,
        (endpoint_id, source_file, checksum),
    ).fetchone()
    if existing:
        raw_payload_id = str(existing["raw_payload_id"])
        counters["skipped_payload_count"] += 1
    else:
        raw_payload_id = str(uuid4())
        connection.execute(
            """
            INSERT INTO sap_raw_payloads (
                raw_payload_id, ingestion_run_id, api_endpoint_id, payload_kind,
                source_file, content_type, validation_status, content_checksum,
                content, imported_at, data_origin
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                raw_payload_id,
                run_id,
                endpoint_id,
                payload_kind,
                source_file,
                content_type,
                validation_status,
                checksum,
                content,
                now,
                data_origin,
            ),
        )
        counters["imported_payload_count"] += 1

    if validation_status == "invalid":
        _save_ingestion_error(
            connection,
            run_id,
            endpoint_id,
            raw_payload_id,
            source_file,
            "invalid_json",
            "Response file is not valid JSON.",
            now,
        )
        return
    if payload_kind != "success" or parsed is None:
        return

    try:
        staged, canonical, unresolved = _stage_success_payload(
            connection,
            inventory_row,
            raw_payload_id,
            parsed,
            now,
            data_origin,
        )
        for table, count in staged.items():
            staged_record_counts[table] += count
        for table, count in canonical.items():
            canonical_record_counts[table] += count
        for entity, count in unresolved.items():
            unresolved_record_counts[entity] += count
    except (KeyError, TypeError, ValueError, ValidationError) as exc:
        counters["error_count"] += 1
        _save_ingestion_error(
            connection,
            run_id,
            endpoint_id,
            raw_payload_id,
            source_file,
            "staging_validation_error",
            str(exc),
            now,
        )


def _stage_success_payload(
    connection: sqlite3.Connection,
    inventory_row: dict[str, str],
    raw_payload_id: str,
    payload: Any,
    now: str,
    data_origin: str = "captured_sample",
) -> tuple[dict[str, int], dict[str, int], dict[str, int]]:
    folder = inventory_row["relative_folder"]
    source_system_id = _source_system_id(inventory_row["source_system"])
    if folder == "fieldglass/worker":
        worker = FieldglassWorkerPayload.model_validate(payload)
        resource, canonicalization_error = _map_fieldglass_worker_to_resource(connection, worker)
        custom_fields = worker.worker_custom_fields
        canonicalization_status = "promoted" if resource else "unresolved"
        connection.execute(
            """
            INSERT INTO sap_fieldglass_workers (
                source_worker_id, raw_payload_id, first_name, last_name, email,
                country, state_province, city, postal_code, worker_role, imported_at,
                data_origin, canonical_resource_id, supplier_id, squad_id,
                current_location_id, skill, current_rate, pii_access, availability,
                canonicalization_status, canonicalization_error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_worker_id) DO UPDATE SET
                raw_payload_id = excluded.raw_payload_id,
                first_name = excluded.first_name,
                last_name = excluded.last_name,
                email = excluded.email,
                country = excluded.country,
                state_province = excluded.state_province,
                city = excluded.city,
                postal_code = excluded.postal_code,
                worker_role = excluded.worker_role,
                imported_at = excluded.imported_at,
                data_origin = excluded.data_origin,
                canonical_resource_id = excluded.canonical_resource_id,
                supplier_id = excluded.supplier_id,
                squad_id = excluded.squad_id,
                current_location_id = excluded.current_location_id,
                skill = excluded.skill,
                current_rate = excluded.current_rate,
                pii_access = excluded.pii_access,
                availability = excluded.availability,
                canonicalization_status = excluded.canonicalization_status,
                canonicalization_error = excluded.canonicalization_error
            """,
            (
                worker.username,
                raw_payload_id,
                worker.first_name,
                worker.last_name,
                worker.email,
                worker.country,
                worker.state_province,
                worker.city,
                worker.postal_code,
                worker.role,
                now,
                data_origin,
                custom_fields.costopt_resource_id,
                custom_fields.supplier_id,
                custom_fields.squad_id,
                custom_fields.current_location_id,
                custom_fields.skill,
                custom_fields.current_rate,
                int(custom_fields.pii_access),
                custom_fields.availability,
                canonicalization_status,
                canonicalization_error,
            ),
        )
        if resource:
            _upsert_canonical_resource(connection, resource)
        _upsert_source_mapping(
            connection,
            source_system_id,
            "worker",
            worker.username,
            "resources" if resource else "sap_fieldglass_workers",
            resource.resource_id if resource else worker.username,
            raw_payload_id,
            now,
        )
        return (
            {"sap_fieldglass_workers": 1},
            {"resources": int(resource is not None)},
            {"fieldglass_workers": int(resource is None)},
        )

    if folder == "fieldglass/business_unit":
        response = FieldglassBusinessUnitResponse.model_validate(payload)
        for item in response.data:
            connection.execute(
                """
                INSERT INTO sap_fieldglass_business_units (
                    business_unit_code, raw_payload_id, name, parent_business_unit_code,
                    legal_entity, resource_coordinator_required, distributor_required, imported_at,
                    data_origin
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(business_unit_code) DO UPDATE SET
                    raw_payload_id = excluded.raw_payload_id,
                    name = excluded.name,
                    parent_business_unit_code = excluded.parent_business_unit_code,
                    legal_entity = excluded.legal_entity,
                    resource_coordinator_required = excluded.resource_coordinator_required,
                    distributor_required = excluded.distributor_required,
                    imported_at = excluded.imported_at,
                    data_origin = excluded.data_origin
                """,
                (
                    item.code,
                    raw_payload_id,
                    item.name,
                    item.parent_business_unit,
                    item.legal_entity,
                    _yes_no(item.resource_coordinator_required),
                    _yes_no(item.distributor_required),
                    now,
                    data_origin,
                ),
            )
            _upsert_source_mapping(
                connection,
                source_system_id,
                "business_unit",
                item.code,
                "sap_fieldglass_business_units",
                item.code,
                raw_payload_id,
                now,
            )
        return {"sap_fieldglass_business_units": len(response.data)}, {}, {}

    if folder == "ariba/purchase_orders":
        response = AribaPurchaseOrderResponse.model_validate(payload)
        staged_ids: set[str] = set()
        for item in response.content:
            amount = item.po_amount.amount if item.po_amount else None
            currency = item.po_amount.resolved_currency if item.po_amount else None
            connection.execute(
                """
                INSERT INTO sap_ariba_purchase_orders (
                    source_po_id, raw_payload_id, supplier_name, supplier_anid, vendor_id,
                    buyer_anid, customer_name, amount_minor, currency, status,
                    document_status, order_date_text, payload_id, imported_at, data_origin
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_po_id) DO UPDATE SET
                    raw_payload_id = excluded.raw_payload_id,
                    supplier_name = excluded.supplier_name,
                    supplier_anid = excluded.supplier_anid,
                    vendor_id = excluded.vendor_id,
                    buyer_anid = excluded.buyer_anid,
                    customer_name = excluded.customer_name,
                    amount_minor = excluded.amount_minor,
                    currency = excluded.currency,
                    status = excluded.status,
                    document_status = excluded.document_status,
                    order_date_text = excluded.order_date_text,
                    payload_id = excluded.payload_id,
                    imported_at = excluded.imported_at,
                    data_origin = excluded.data_origin
                """,
                (
                    item.document_number,
                    raw_payload_id,
                    item.supplier_name,
                    item.supplier_anid,
                    item.vendor_id,
                    item.buyer_anid,
                    item.customer_name,
                    _minor_units(amount),
                    _currency(currency),
                    item.status,
                    item.document_status,
                    item.order_date,
                    item.payload_id,
                    now,
                    data_origin,
                ),
            )
            _upsert_source_mapping(
                connection,
                source_system_id,
                "purchase_order",
                item.document_number,
                "sap_ariba_purchase_orders",
                item.document_number,
                raw_payload_id,
                now,
            )
            staged_ids.add(item.document_number)
        return {"sap_ariba_purchase_orders": len(staged_ids)}, {}, {}

    if folder == "ariba/contract_workspace":
        response = AribaContractWorkspaceResponse.model_validate(payload)
        for item in response.value:
            amount = item.contract_amount.amount if item.contract_amount else None
            currency = item.contract_amount.resolved_currency if item.contract_amount else None
            connection.execute(
                """
                INSERT INTO sap_ariba_contract_workspaces (
                    source_contract_id, raw_payload_id, title, description, contract_status,
                    effective_date_text, expiration_date_text, amount_minor, currency,
                    version_number, owner_unique_name, is_active, last_modified_text, imported_at,
                    data_origin
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_contract_id) DO UPDATE SET
                    raw_payload_id = excluded.raw_payload_id,
                    title = excluded.title,
                    description = excluded.description,
                    contract_status = excluded.contract_status,
                    effective_date_text = excluded.effective_date_text,
                    expiration_date_text = excluded.expiration_date_text,
                    amount_minor = excluded.amount_minor,
                    currency = excluded.currency,
                    version_number = excluded.version_number,
                    owner_unique_name = excluded.owner_unique_name,
                    is_active = excluded.is_active,
                    last_modified_text = excluded.last_modified_text,
                    imported_at = excluded.imported_at,
                    data_origin = excluded.data_origin
                """,
                (
                    item.contract_id,
                    raw_payload_id,
                    item.title,
                    item.description,
                    item.contract_status,
                    item.effective_date,
                    item.expiration_date,
                    _minor_units(amount),
                    _currency(currency),
                    item.version,
                    item.owner.unique_name if item.owner else None,
                    int(item.active),
                    item.last_modified,
                    now,
                    data_origin,
                ),
            )
            _upsert_source_mapping(
                connection,
                source_system_id,
                "contract_workspace",
                item.contract_id,
                "sap_ariba_contract_workspaces",
                item.contract_id,
                raw_payload_id,
                now,
            )
        return {"sap_ariba_contract_workspaces": len(response.value)}, {}, {}
    return {}, {}, {}


def _map_fieldglass_worker_to_resource(
    connection: sqlite3.Connection,
    worker: FieldglassWorkerPayload,
) -> tuple[Resource | None, str | None]:
    """Build a canonical Resource only when the source provides complete governed mappings."""
    fields = worker.worker_custom_fields
    required_values = {
        "costoptResourceId": fields.costopt_resource_id,
        "supplierId": fields.supplier_id,
        "squadId": fields.squad_id,
        "currentLocationId": fields.current_location_id,
        "role": worker.role,
        "skill": fields.skill,
        "currentRate": fields.current_rate,
    }
    missing = [name for name, value in required_values.items() if value is None or value == ""]
    if missing:
        return None, "Missing canonical mapping fields: " + ", ".join(missing)

    references = (
        ("suppliers", "supplier_id", fields.supplier_id),
        ("squads", "squad_id", fields.squad_id),
        ("locations", "location_id", fields.current_location_id),
    )
    unresolved_references = [
        f"{table}.{column}={value}"
        for table, column, value in references
        if connection.execute(
            f"SELECT 1 FROM {table} WHERE {column} = ?",
            (value,),
        ).fetchone()
        is None
    ]
    if unresolved_references:
        return None, "Unknown canonical references: " + ", ".join(unresolved_references)

    return (
        Resource(
            resource_id=str(fields.costopt_resource_id),
            supplier_id=str(fields.supplier_id),
            squad_id=str(fields.squad_id),
            current_location_id=str(fields.current_location_id),
            role=str(worker.role),
            skill=str(fields.skill),
            current_rate=float(fields.current_rate),
            pii_access=fields.pii_access,
            availability=fields.availability or "active",
        ),
        None,
    )


def _upsert_canonical_resource(connection: sqlite3.Connection, resource: Resource) -> None:
    connection.execute(
        """
        INSERT INTO resources (
            resource_id, supplier_id, squad_id, current_location_id, role, skill,
            current_rate, pii_access, availability
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(resource_id) DO UPDATE SET
            supplier_id = excluded.supplier_id,
            squad_id = excluded.squad_id,
            current_location_id = excluded.current_location_id,
            role = excluded.role,
            skill = excluded.skill,
            current_rate = excluded.current_rate,
            pii_access = excluded.pii_access,
            availability = excluded.availability
        """,
        (
            resource.resource_id,
            resource.supplier_id,
            resource.squad_id,
            resource.current_location_id,
            resource.role,
            resource.skill,
            resource.current_rate,
            int(resource.pii_access),
            resource.availability,
        ),
    )


def _upsert_source_mapping(
    connection: sqlite3.Connection,
    source_system_id: str,
    entity_type: str,
    source_record_id: str,
    target_table: str,
    target_record_id: str,
    raw_payload_id: str,
    now: str,
) -> None:
    mapping_id = f"{source_system_id}:{entity_type}:{source_record_id}"
    connection.execute(
        """
        INSERT INTO sap_source_record_mappings (
            source_record_mapping_id, source_system_id, entity_type, source_record_id,
            canonical_table, canonical_record_id, raw_payload_id, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_system_id, entity_type, source_record_id) DO UPDATE SET
            canonical_table = excluded.canonical_table,
            canonical_record_id = excluded.canonical_record_id,
            raw_payload_id = excluded.raw_payload_id,
            updated_at = excluded.updated_at
        """,
        (
            mapping_id,
            source_system_id,
            entity_type,
            source_record_id,
            target_table,
            target_record_id,
            raw_payload_id,
            now,
            now,
        ),
    )


def _save_ingestion_error(
    connection: sqlite3.Connection,
    run_id: str,
    endpoint_id: str,
    raw_payload_id: str,
    source_file: str,
    error_type: str,
    message: str,
    now: str,
) -> None:
    connection.execute(
        """
        INSERT INTO sap_ingestion_errors (
            ingestion_error_id, ingestion_run_id, api_endpoint_id, raw_payload_id,
            source_file, error_type, error_message, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (str(uuid4()), run_id, endpoint_id, raw_payload_id, source_file, error_type, message, now),
    )


def _record_failed_run(
    run_id: str,
    source: str,
    endpoint_count: int,
    started_at: str,
    data_origin: str,
) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO sap_ingestion_runs (
                ingestion_run_id, requested_source, status, endpoint_count,
                error_count, started_at, completed_at, data_origin
            ) VALUES (?, ?, 'failed', ?, 1, ?, ?, ?)
            ON CONFLICT(ingestion_run_id) DO UPDATE SET
                status = 'failed', error_count = 1, completed_at = excluded.completed_at
            """,
            (run_id, source, endpoint_count, started_at, _now(), data_origin),
        )


def _payload_files(api_dir: Path) -> list[Path]:
    if not api_dir.is_dir():
        return []
    return sorted(
        path
        for path in api_dir.glob("response*")
        if path.is_file() and path.suffix.casefold() in {".json", ".html"}
    )


def _payload_kind(filename: str) -> str:
    if ".error." in filename:
        return "error"
    if ".misfiled." in filename:
        return "misfiled"
    if ".unverified." in filename:
        return "unverified"
    if ".schema." in filename:
        return "schema_example"
    return "success"


def _source_system_id(source_system: str) -> str:
    return f"sap-{source_system.casefold()}"


def _endpoint_id(row: dict[str, str]) -> str:
    return f"{_source_system_id(row['source_system'])}:{row['api_key']}"


def _optional_inventory_value(value: str | None) -> str | None:
    if not value or value.startswith("NOT_"):
        return None
    return value


def _minor_units(value: Decimal | None) -> int | None:
    if value is None:
        return None
    return int((value * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _currency(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.upper()
    if len(normalized) != 3:
        raise ValueError(f"Invalid currency code: {value}")
    return normalized


def _yes_no(value: str | None) -> int:
    return int(bool(value and value.casefold() in {"yes", "true", "1"}))


def _table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    row = connection.execute(
        "SELECT 1 AS present FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _now() -> str:
    return datetime.now(UTC).isoformat()
