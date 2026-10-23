import sqlite3

from fastapi.testclient import TestClient

from costopt.api.app import create_app
from costopt.integrations.sap.ingestion import ingest_sap_samples
from costopt.integrations.sap.synthetic import ingest_synthetic_sap_data


def test_sap_sample_ingestion_is_additive_and_idempotent(isolated_db):
    first = ingest_sap_samples()
    second = ingest_sap_samples()

    assert first.status == "completed"
    assert first.data_origin == "captured_sample"
    assert first.endpoint_count == 32
    assert first.payload_file_count == 25
    assert first.imported_payload_count == 25
    assert first.skipped_payload_count == 0
    assert first.error_count == 0
    assert first.staged_record_counts == {
        "sap_fieldglass_workers": 1,
        "sap_fieldglass_business_units": 10,
        "sap_ariba_purchase_orders": 1,
        "sap_ariba_contract_workspaces": 1,
    }
    assert first.canonical_record_counts == {"resources": 0}
    assert first.unresolved_record_counts == {"fieldglass_workers": 1}
    assert second.imported_payload_count == 0
    assert second.skipped_payload_count == 25

    with sqlite3.connect(isolated_db) as connection:
        counts = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "sap_source_systems",
                "sap_api_endpoints",
                "sap_ingestion_runs",
                "sap_raw_payloads",
                "sap_ingestion_errors",
                "sap_source_record_mappings",
                "sap_fieldglass_workers",
                "sap_fieldglass_business_units",
                "sap_ariba_purchase_orders",
                "sap_ariba_contract_workspaces",
                "resources",
                "purchase_orders",
            )
        }
        worker_status = connection.execute(
            """
            SELECT canonicalization_status, canonicalization_error
            FROM sap_fieldglass_workers
            WHERE source_worker_id = 'CRPSWK00000098'
            """
        ).fetchone()

    assert counts == {
        "sap_source_systems": 2,
        "sap_api_endpoints": 32,
        "sap_ingestion_runs": 2,
        "sap_raw_payloads": 25,
        "sap_ingestion_errors": 0,
        "sap_source_record_mappings": 13,
        "sap_fieldglass_workers": 1,
        "sap_fieldglass_business_units": 10,
        "sap_ariba_purchase_orders": 1,
        "sap_ariba_contract_workspaces": 1,
        "resources": 110,
        "purchase_orders": 60,
    }
    assert worker_status is not None
    assert worker_status[0] == "unresolved"
    assert "supplierId" in worker_status[1]


def test_sap_ingestion_tracks_payload_classification(isolated_db):
    ingest_sap_samples()

    with sqlite3.connect(isolated_db) as connection:
        counts = dict(
            connection.execute(
                "SELECT payload_kind, COUNT(*) FROM sap_raw_payloads GROUP BY payload_kind"
            ).fetchall()
        )

    assert counts == {
        "error": 8,
        "misfiled": 1,
        "schema_example": 1,
        "success": 14,
        "unverified": 1,
    }


def test_sap_ingestion_can_be_limited_to_one_source(isolated_db):
    result = ingest_sap_samples("fieldglass")

    assert result.endpoint_count == 13
    assert result.payload_file_count == 10
    assert result.staged_record_counts["sap_fieldglass_workers"] == 1
    assert result.staged_record_counts["sap_fieldglass_business_units"] == 10
    assert result.staged_record_counts["sap_ariba_purchase_orders"] == 0


def test_sap_status_endpoint_reports_latest_import(isolated_db):
    ingest_sap_samples()
    client = TestClient(create_app())

    response = client.get("/api/v1/integrations/sap/status")

    assert response.status_code == 200
    body = response.json()
    assert body["configured_endpoint_count"] == 32
    assert body["raw_payload_count"] == 25
    assert body["payload_counts"]["success"] == 14
    assert body["origin_counts"] == {"captured_sample": 25}
    assert body["staging_counts"]["sap_ariba_purchase_orders"] == 1
    assert body["canonical_counts"] == {"resources": 0}
    assert body["canonicalization_counts"] == {"unresolved": 1}
    assert body["latest_run"]["status"] == "completed"
    assert body["latest_run"]["data_origin"] == "captured_sample"


def test_synthetic_sap_data_populates_staging_tables_and_is_idempotent(isolated_db):
    ingest_sap_samples()

    first = ingest_synthetic_sap_data()
    second = ingest_synthetic_sap_data()

    assert first.status == "completed"
    assert first.data_origin == "synthetic_fixture"
    assert first.endpoint_count == 4
    assert first.payload_file_count == 113
    assert first.imported_payload_count == 113
    assert first.skipped_payload_count == 0
    assert first.error_count == 0
    assert first.staged_record_counts == {
        "sap_fieldglass_workers": 110,
        "sap_fieldglass_business_units": 22,
        "sap_ariba_purchase_orders": 60,
        "sap_ariba_contract_workspaces": 20,
    }
    assert first.canonical_record_counts == {"resources": 110}
    assert first.unresolved_record_counts == {"fieldglass_workers": 0}
    assert second.imported_payload_count == 0
    assert second.skipped_payload_count == 113

    with sqlite3.connect(isolated_db) as connection:
        totals = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "sap_raw_payloads",
                "sap_source_record_mappings",
                "sap_fieldglass_workers",
                "sap_fieldglass_business_units",
                "sap_ariba_purchase_orders",
                "sap_ariba_contract_workspaces",
                "resources",
                "purchase_orders",
            )
        }
        origin_counts = dict(
            connection.execute(
                "SELECT data_origin, COUNT(*) FROM sap_raw_payloads GROUP BY data_origin"
            ).fetchall()
        )
        staging_origin_counts = {
            table: dict(
                connection.execute(
                    f"SELECT data_origin, COUNT(*) FROM {table} GROUP BY data_origin"
                ).fetchall()
            )
            for table in (
                "sap_fieldglass_workers",
                "sap_fieldglass_business_units",
                "sap_ariba_purchase_orders",
                "sap_ariba_contract_workspaces",
            )
        }

    assert totals == {
        "sap_raw_payloads": 138,
        "sap_source_record_mappings": 225,
        "sap_fieldglass_workers": 111,
        "sap_fieldglass_business_units": 32,
        "sap_ariba_purchase_orders": 61,
        "sap_ariba_contract_workspaces": 21,
        "resources": 110,
        "purchase_orders": 60,
    }
    assert origin_counts == {"captured_sample": 25, "synthetic_fixture": 113}
    assert staging_origin_counts == {
        "sap_fieldglass_workers": {"captured_sample": 1, "synthetic_fixture": 110},
        "sap_fieldglass_business_units": {"captured_sample": 10, "synthetic_fixture": 22},
        "sap_ariba_purchase_orders": {"captured_sample": 1, "synthetic_fixture": 60},
        "sap_ariba_contract_workspaces": {"captured_sample": 1, "synthetic_fixture": 20},
    }


def test_synthetic_fieldglass_worker_is_promoted_to_canonical_resource(isolated_db):
    with sqlite3.connect(isolated_db) as connection:
        connection.execute("DELETE FROM resources WHERE resource_id = 'res-110'")

    result = ingest_synthetic_sap_data("fieldglass")

    assert result.canonical_record_counts == {"resources": 110}
    assert result.unresolved_record_counts == {"fieldglass_workers": 0}

    with sqlite3.connect(isolated_db) as connection:
        resource = connection.execute(
            """
            SELECT resource_id, supplier_id, squad_id, current_location_id, role, skill,
                   current_rate, pii_access, availability
            FROM resources
            WHERE resource_id = 'res-110'
            """
        ).fetchone()
        staging = connection.execute(
            """
            SELECT canonical_resource_id, canonicalization_status, canonicalization_error
            FROM sap_fieldglass_workers
            WHERE source_worker_id = 'SYN-FG-RES-110'
            """
        ).fetchone()
        mapping = connection.execute(
            """
            SELECT canonical_table, canonical_record_id
            FROM sap_source_record_mappings
            WHERE source_system_id = 'sap-fieldglass'
              AND entity_type = 'worker'
              AND source_record_id = 'SYN-FG-RES-110'
            """
        ).fetchone()

    assert resource == (
        "res-110",
        "sup-tristar-solutions",
        "squad-identity-platform",
        "loc-singapore",
        "Support Engineer",
        "Run support 20-5",
        595.2,
        0,
        "active",
    )
    assert staging == ("res-110", "promoted", None)
    assert mapping == ("resources", "res-110")
