ALTER TABLE sap_ingestion_runs
ADD COLUMN data_origin TEXT NOT NULL DEFAULT 'captured_sample'
CHECK (data_origin IN ('captured_sample', 'synthetic_fixture'));

ALTER TABLE sap_raw_payloads
ADD COLUMN data_origin TEXT NOT NULL DEFAULT 'captured_sample'
CHECK (data_origin IN ('captured_sample', 'synthetic_fixture'));

ALTER TABLE sap_fieldglass_workers
ADD COLUMN data_origin TEXT NOT NULL DEFAULT 'captured_sample'
CHECK (data_origin IN ('captured_sample', 'synthetic_fixture'));

ALTER TABLE sap_fieldglass_business_units
ADD COLUMN data_origin TEXT NOT NULL DEFAULT 'captured_sample'
CHECK (data_origin IN ('captured_sample', 'synthetic_fixture'));

ALTER TABLE sap_ariba_purchase_orders
ADD COLUMN data_origin TEXT NOT NULL DEFAULT 'captured_sample'
CHECK (data_origin IN ('captured_sample', 'synthetic_fixture'));

ALTER TABLE sap_ariba_contract_workspaces
ADD COLUMN data_origin TEXT NOT NULL DEFAULT 'captured_sample'
CHECK (data_origin IN ('captured_sample', 'synthetic_fixture'));

CREATE INDEX IF NOT EXISTS idx_sap_raw_payloads_origin
    ON sap_raw_payloads(data_origin, api_endpoint_id);

CREATE INDEX IF NOT EXISTS idx_sap_workers_origin
    ON sap_fieldglass_workers(data_origin);

CREATE INDEX IF NOT EXISTS idx_sap_business_units_origin
    ON sap_fieldglass_business_units(data_origin);

CREATE INDEX IF NOT EXISTS idx_sap_purchase_orders_origin
    ON sap_ariba_purchase_orders(data_origin);

CREATE INDEX IF NOT EXISTS idx_sap_contract_workspaces_origin
    ON sap_ariba_contract_workspaces(data_origin);
