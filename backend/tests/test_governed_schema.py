import sqlite3


def test_governed_schema_migration_creates_required_tables(isolated_db):
    expected_tables = {
        "schema_migrations",
        "organizations",
        "organization_memberships",
        "contract_versions",
        "contract_version_clauses",
        "rate_card_versions",
        "scenario_runs",
        "scenario_input_snapshots",
        "agent_run_audits",
        "agent_run_stages",
        "approval_requests",
        "approval_decisions",
        "procurement_recommendation_sources",
        "sap_source_systems",
        "sap_api_endpoints",
        "sap_ingestion_runs",
        "sap_raw_payloads",
        "sap_ingestion_errors",
        "sap_source_record_mappings",
        "sap_sync_watermarks",
        "sap_fieldglass_workers",
        "sap_fieldglass_business_units",
        "sap_ariba_purchase_orders",
        "sap_ariba_contract_workspaces",
    }

    with sqlite3.connect(isolated_db) as connection:
        actual_tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }

    assert expected_tables <= actual_tables


def test_monetary_minor_unit_columns_are_backfilled(isolated_db):
    with sqlite3.connect(isolated_db) as connection:
        row = connection.execute(
            "SELECT bill_rate, bill_rate_minor FROM rate_cards WHERE rate_card_id = 'rc-001'"
        ).fetchone()
        assert row is not None
        assert row[1] == round(row[0] * 100)
        columns = {
            column[1]
            for column in connection.execute("PRAGMA table_info(optimization_scenarios)").fetchall()
        }

    assert {
        "baseline_cost_minor",
        "future_cost_minor",
        "monthly_savings_minor",
        "annual_savings_minor",
    } <= columns
