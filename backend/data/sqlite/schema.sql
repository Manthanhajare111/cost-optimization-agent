PRAGMA foreign_keys = OFF;

DROP TABLE IF EXISTS workforce_uploads;
DROP TABLE IF EXISTS workforce_case_reviews;
DROP TABLE IF EXISTS workforce_case_analyses;
DROP TABLE IF EXISTS sap_ariba_contract_workspaces;
DROP TABLE IF EXISTS sap_ariba_purchase_orders;
DROP TABLE IF EXISTS sap_fieldglass_business_units;
DROP TABLE IF EXISTS sap_fieldglass_workers;
DROP TABLE IF EXISTS sap_sync_watermarks;
DROP TABLE IF EXISTS sap_source_record_mappings;
DROP TABLE IF EXISTS sap_ingestion_errors;
DROP TABLE IF EXISTS sap_raw_payloads;
DROP TABLE IF EXISTS sap_ingestion_runs;
DROP TABLE IF EXISTS sap_api_endpoints;
DROP TABLE IF EXISTS sap_source_systems;
DROP TABLE IF EXISTS agent_run_stages;
DROP TABLE IF EXISTS approval_decisions;
DROP TABLE IF EXISTS approval_requests;
DROP TABLE IF EXISTS agent_run_audits;
DROP TABLE IF EXISTS scenario_input_snapshots;
DROP TABLE IF EXISTS scenario_runs;
DROP TABLE IF EXISTS contract_version_clauses;
DROP TABLE IF EXISTS contract_versions;
DROP TABLE IF EXISTS rate_card_versions;
DROP TABLE IF EXISTS procurement_recommendation_sources;
DROP TABLE IF EXISTS organization_memberships;
DROP TABLE IF EXISTS organizations;
DROP TABLE IF EXISTS schema_migrations;
DROP TABLE IF EXISTS recommendation_runs;
DROP TABLE IF EXISTS audit_log;
DROP TABLE IF EXISTS recommendation_evidence;
DROP TABLE IF EXISTS recommendations;
DROP TABLE IF EXISTS optimization_scenarios;
DROP TABLE IF EXISTS contract_clauses;
DROP TABLE IF EXISTS contracts;
DROP TABLE IF EXISTS rate_cards;
DROP TABLE IF EXISTS resources;
DROP TABLE IF EXISTS squads;
DROP TABLE IF EXISTS locations;
DROP TABLE IF EXISTS invoices;
DROP TABLE IF EXISTS procurement_contracts;
DROP TABLE IF EXISTS purchase_orders;
DROP TABLE IF EXISTS procurement_recommendations;
DROP TABLE IF EXISTS categories;
DROP TABLE IF EXISTS users;
DROP TABLE IF EXISTS suppliers;

CREATE TABLE suppliers (
    supplier_id TEXT PRIMARY KEY,
    name TEXT,
    region TEXT,
    capability TEXT,
    created_at TEXT
);

CREATE TABLE locations (
    location_id TEXT PRIMARY KEY,
    country TEXT,
    region TEXT,
    cost_index REAL,
    is_offshore INTEGER
);

CREATE TABLE squads (
    squad_id TEXT PRIMARY KEY,
    name TEXT,
    business_unit TEXT
);

CREATE TABLE resources (
    resource_id TEXT PRIMARY KEY,
    supplier_id TEXT NOT NULL,
    squad_id TEXT,
    current_location_id TEXT NOT NULL,
    role TEXT,
    skill TEXT,
    current_rate REAL,
    pii_access INTEGER DEFAULT 0,
    availability TEXT,
    FOREIGN KEY (supplier_id) REFERENCES suppliers(supplier_id),
    FOREIGN KEY (squad_id) REFERENCES squads(squad_id),
    FOREIGN KEY (current_location_id) REFERENCES locations(location_id)
);

CREATE TABLE rate_cards (
    rate_card_id TEXT PRIMARY KEY,
    supplier_id TEXT NOT NULL,
    location_id TEXT NOT NULL,
    role TEXT,
    bill_rate REAL,
    currency TEXT,
    FOREIGN KEY (supplier_id) REFERENCES suppliers(supplier_id),
    FOREIGN KEY (location_id) REFERENCES locations(location_id)
);

CREATE TABLE contracts (
    contract_id TEXT PRIMARY KEY,
    supplier_id TEXT NOT NULL,
    document_uri TEXT,
    contract_type TEXT,
    offshore_permitted INTEGER,
    data_residency_restriction TEXT,
    customer_approval_required INTEGER,
    created_at TEXT,
    FOREIGN KEY (supplier_id) REFERENCES suppliers(supplier_id)
);

CREATE TABLE contract_clauses (
    clause_id TEXT PRIMARY KEY,
    contract_id TEXT NOT NULL,
    clause_type TEXT,
    clause_text TEXT,
    embedding TEXT,
    FOREIGN KEY (contract_id) REFERENCES contracts(contract_id)
);

CREATE TABLE optimization_scenarios (
    scenario_id TEXT PRIMARY KEY,
    squad_id TEXT NOT NULL,
    target_location_id TEXT NOT NULL,
    baseline_cost REAL,
    future_cost REAL,
    monthly_savings REAL,
    annual_savings REAL,
    assumptions TEXT,
    created_at TEXT,
    FOREIGN KEY (squad_id) REFERENCES squads(squad_id),
    FOREIGN KEY (target_location_id) REFERENCES locations(location_id)
);

CREATE TABLE recommendations (
    recommendation_id TEXT PRIMARY KEY,
    scenario_id TEXT NOT NULL,
    confidence_score REAL,
    compliance_summary TEXT,
    risk_assessment TEXT,
    rationale TEXT,
    created_at TEXT,
    FOREIGN KEY (scenario_id) REFERENCES optimization_scenarios(scenario_id)
);

CREATE TABLE recommendation_evidence (
    evidence_id TEXT PRIMARY KEY,
    recommendation_id TEXT NOT NULL,
    clause_id TEXT NOT NULL,
    FOREIGN KEY (recommendation_id) REFERENCES recommendations(recommendation_id),
    FOREIGN KEY (clause_id) REFERENCES contract_clauses(clause_id)
);

CREATE TABLE categories (
    category_id TEXT PRIMARY KEY,
    name TEXT,
    commodity_code TEXT
);

CREATE TABLE purchase_orders (
    po_id TEXT PRIMARY KEY,
    supplier_id TEXT NOT NULL,
    category_id TEXT NOT NULL,
    business_unit TEXT,
    amount REAL,
    currency TEXT,
    order_date TEXT,
    FOREIGN KEY (supplier_id) REFERENCES suppliers(supplier_id),
    FOREIGN KEY (category_id) REFERENCES categories(category_id)
);

CREATE TABLE procurement_contracts (
    procurement_contract_id TEXT PRIMARY KEY,
    supplier_id TEXT NOT NULL,
    category_id TEXT NOT NULL,
    negotiated_rate REAL,
    currency TEXT,
    is_preferred_supplier INTEGER,
    start_date TEXT,
    end_date TEXT,
    FOREIGN KEY (supplier_id) REFERENCES suppliers(supplier_id),
    FOREIGN KEY (category_id) REFERENCES categories(category_id)
);

CREATE TABLE invoices (
    invoice_id TEXT PRIMARY KEY,
    supplier_id TEXT NOT NULL,
    po_id TEXT,
    procurement_contract_id TEXT,
    invoiced_amount REAL,
    currency TEXT,
    invoice_date TEXT,
    FOREIGN KEY (supplier_id) REFERENCES suppliers(supplier_id),
    FOREIGN KEY (po_id) REFERENCES purchase_orders(po_id),
    FOREIGN KEY (procurement_contract_id) REFERENCES procurement_contracts(procurement_contract_id)
);

CREATE TABLE procurement_recommendations (
    proc_recommendation_id TEXT PRIMARY KEY,
    use_case TEXT,
    estimated_savings REAL,
    currency TEXT,
    confidence_score REAL,
    rationale TEXT,
    risk_assessment TEXT,
    created_at TEXT
);

CREATE TABLE users (
    user_id TEXT PRIMARY KEY,
    email TEXT,
    role TEXT
);

CREATE TABLE audit_log (
    audit_id TEXT PRIMARY KEY,
    user_id TEXT,
    entity_type TEXT NOT NULL,
    entity_id TEXT,
    action TEXT NOT NULL,
    details TEXT,
    ip_address TEXT,
    created_at TEXT,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE TABLE recommendation_runs (
    recommendation_id TEXT PRIMARY KEY,
    scenario_id TEXT,
    scenario_name TEXT NOT NULL,
    squad_id TEXT NOT NULL,
    target_location_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (scenario_id) REFERENCES optimization_scenarios(scenario_id),
    FOREIGN KEY (squad_id) REFERENCES squads(squad_id),
    FOREIGN KEY (target_location_id) REFERENCES locations(location_id)
);

CREATE INDEX idx_resources_supplier_id ON resources (supplier_id);
CREATE INDEX idx_resources_squad_id ON resources (squad_id);
CREATE INDEX idx_resources_current_location_id ON resources (current_location_id);
CREATE INDEX idx_rate_cards_supplier_location_role ON rate_cards (supplier_id, location_id, role);
CREATE INDEX idx_contracts_supplier_id ON contracts (supplier_id);
CREATE INDEX idx_contract_clauses_contract_id ON contract_clauses (contract_id);
CREATE INDEX idx_scenarios_squad_id ON optimization_scenarios (squad_id);
CREATE INDEX idx_scenarios_target_location_id ON optimization_scenarios (target_location_id);
CREATE INDEX idx_recommendations_scenario_id ON recommendations (scenario_id);
CREATE INDEX idx_recommendation_evidence_recommendation_id ON recommendation_evidence (recommendation_id);
CREATE INDEX idx_recommendation_evidence_clause_id ON recommendation_evidence (clause_id);
CREATE INDEX idx_purchase_orders_supplier_id ON purchase_orders (supplier_id);
CREATE INDEX idx_purchase_orders_category_id ON purchase_orders (category_id);
CREATE INDEX idx_procurement_contracts_supplier_id ON procurement_contracts (supplier_id);
CREATE INDEX idx_procurement_contracts_category_id ON procurement_contracts (category_id);
CREATE INDEX idx_invoices_supplier_id ON invoices (supplier_id);
CREATE INDEX idx_invoices_po_id ON invoices (po_id);
CREATE INDEX idx_invoices_procurement_contract_id ON invoices (procurement_contract_id);
CREATE INDEX idx_audit_log_user_id ON audit_log (user_id);
CREATE INDEX idx_audit_log_entity_type_entity_id ON audit_log (entity_type, entity_id);
CREATE INDEX idx_recommendation_runs_squad_target ON recommendation_runs (squad_id, target_location_id);
CREATE INDEX idx_recommendation_runs_updated_at ON recommendation_runs (updated_at);

PRAGMA foreign_keys = ON;
