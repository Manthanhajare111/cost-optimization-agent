CREATE TABLE IF NOT EXISTS sap_source_systems (
    source_system_id TEXT PRIMARY KEY,
    product_name TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL CHECK (status IN ('configured', 'pending_access', 'disabled')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sap_api_endpoints (
    api_endpoint_id TEXT PRIMARY KEY,
    source_system_id TEXT NOT NULL,
    api_key TEXT NOT NULL,
    ppt_name TEXT NOT NULL,
    official_api_name TEXT,
    api_version TEXT,
    method TEXT NOT NULL CHECK (method IN ('GET', 'POST', 'PUT', 'PATCH', 'DELETE')),
    endpoint_path TEXT,
    documentation_url TEXT,
    capture_status TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (source_system_id, api_key),
    FOREIGN KEY (source_system_id) REFERENCES sap_source_systems(source_system_id)
);

CREATE TABLE IF NOT EXISTS sap_ingestion_runs (
    ingestion_run_id TEXT PRIMARY KEY,
    requested_source TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('running', 'completed', 'completed_with_errors', 'failed')
    ),
    endpoint_count INTEGER NOT NULL DEFAULT 0 CHECK (endpoint_count >= 0),
    payload_file_count INTEGER NOT NULL DEFAULT 0 CHECK (payload_file_count >= 0),
    imported_payload_count INTEGER NOT NULL DEFAULT 0 CHECK (imported_payload_count >= 0),
    skipped_payload_count INTEGER NOT NULL DEFAULT 0 CHECK (skipped_payload_count >= 0),
    error_count INTEGER NOT NULL DEFAULT 0 CHECK (error_count >= 0),
    started_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS sap_raw_payloads (
    raw_payload_id TEXT PRIMARY KEY,
    ingestion_run_id TEXT NOT NULL,
    api_endpoint_id TEXT NOT NULL,
    payload_kind TEXT NOT NULL CHECK (
        payload_kind IN ('success', 'error', 'misfiled', 'unverified', 'schema_example')
    ),
    source_file TEXT NOT NULL,
    content_type TEXT NOT NULL CHECK (content_type IN ('application/json', 'text/html')),
    validation_status TEXT NOT NULL CHECK (validation_status IN ('valid', 'invalid', 'unvalidated')),
    content_checksum TEXT NOT NULL,
    content TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    UNIQUE (api_endpoint_id, source_file, content_checksum),
    FOREIGN KEY (ingestion_run_id) REFERENCES sap_ingestion_runs(ingestion_run_id),
    FOREIGN KEY (api_endpoint_id) REFERENCES sap_api_endpoints(api_endpoint_id)
);

CREATE TABLE IF NOT EXISTS sap_ingestion_errors (
    ingestion_error_id TEXT PRIMARY KEY,
    ingestion_run_id TEXT NOT NULL,
    api_endpoint_id TEXT,
    raw_payload_id TEXT,
    source_file TEXT,
    error_type TEXT NOT NULL,
    error_message TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (ingestion_run_id) REFERENCES sap_ingestion_runs(ingestion_run_id),
    FOREIGN KEY (api_endpoint_id) REFERENCES sap_api_endpoints(api_endpoint_id),
    FOREIGN KEY (raw_payload_id) REFERENCES sap_raw_payloads(raw_payload_id)
);

CREATE TABLE IF NOT EXISTS sap_source_record_mappings (
    source_record_mapping_id TEXT PRIMARY KEY,
    source_system_id TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    source_record_id TEXT NOT NULL,
    canonical_table TEXT NOT NULL,
    canonical_record_id TEXT NOT NULL,
    raw_payload_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (source_system_id, entity_type, source_record_id),
    FOREIGN KEY (source_system_id) REFERENCES sap_source_systems(source_system_id),
    FOREIGN KEY (raw_payload_id) REFERENCES sap_raw_payloads(raw_payload_id)
);

CREATE TABLE IF NOT EXISTS sap_sync_watermarks (
    api_endpoint_id TEXT PRIMARY KEY,
    watermark_type TEXT NOT NULL,
    watermark_value TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (api_endpoint_id) REFERENCES sap_api_endpoints(api_endpoint_id)
);

CREATE TABLE IF NOT EXISTS sap_fieldglass_workers (
    source_worker_id TEXT PRIMARY KEY,
    raw_payload_id TEXT NOT NULL,
    first_name TEXT,
    last_name TEXT,
    email TEXT,
    country TEXT,
    state_province TEXT,
    city TEXT,
    postal_code TEXT,
    worker_role TEXT,
    imported_at TEXT NOT NULL,
    FOREIGN KEY (raw_payload_id) REFERENCES sap_raw_payloads(raw_payload_id)
);

CREATE TABLE IF NOT EXISTS sap_fieldglass_business_units (
    business_unit_code TEXT PRIMARY KEY,
    raw_payload_id TEXT NOT NULL,
    name TEXT NOT NULL,
    parent_business_unit_code TEXT,
    legal_entity TEXT,
    resource_coordinator_required INTEGER NOT NULL CHECK (
        resource_coordinator_required IN (0, 1)
    ),
    distributor_required INTEGER NOT NULL CHECK (distributor_required IN (0, 1)),
    imported_at TEXT NOT NULL,
    FOREIGN KEY (raw_payload_id) REFERENCES sap_raw_payloads(raw_payload_id)
);

CREATE TABLE IF NOT EXISTS sap_ariba_purchase_orders (
    source_po_id TEXT PRIMARY KEY,
    raw_payload_id TEXT NOT NULL,
    supplier_name TEXT,
    supplier_anid TEXT,
    vendor_id TEXT,
    buyer_anid TEXT,
    customer_name TEXT,
    amount_minor INTEGER,
    currency TEXT CHECK (currency IS NULL OR length(currency) = 3),
    status TEXT,
    document_status TEXT,
    order_date_text TEXT,
    payload_id TEXT,
    imported_at TEXT NOT NULL,
    FOREIGN KEY (raw_payload_id) REFERENCES sap_raw_payloads(raw_payload_id)
);

CREATE TABLE IF NOT EXISTS sap_ariba_contract_workspaces (
    source_contract_id TEXT PRIMARY KEY,
    raw_payload_id TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    contract_status TEXT,
    effective_date_text TEXT,
    expiration_date_text TEXT,
    amount_minor INTEGER,
    currency TEXT CHECK (currency IS NULL OR length(currency) = 3),
    version_number INTEGER,
    owner_unique_name TEXT,
    is_active INTEGER NOT NULL CHECK (is_active IN (0, 1)),
    last_modified_text TEXT,
    imported_at TEXT NOT NULL,
    FOREIGN KEY (raw_payload_id) REFERENCES sap_raw_payloads(raw_payload_id)
);

CREATE INDEX IF NOT EXISTS idx_sap_api_endpoints_source
    ON sap_api_endpoints(source_system_id, api_key);
CREATE INDEX IF NOT EXISTS idx_sap_ingestion_runs_started
    ON sap_ingestion_runs(started_at);
CREATE INDEX IF NOT EXISTS idx_sap_raw_payloads_endpoint_kind
    ON sap_raw_payloads(api_endpoint_id, payload_kind);
CREATE INDEX IF NOT EXISTS idx_sap_ingestion_errors_run
    ON sap_ingestion_errors(ingestion_run_id);
CREATE INDEX IF NOT EXISTS idx_sap_source_mappings_canonical
    ON sap_source_record_mappings(canonical_table, canonical_record_id);
CREATE INDEX IF NOT EXISTS idx_sap_ariba_purchase_orders_supplier
    ON sap_ariba_purchase_orders(supplier_anid, vendor_id);
