ALTER TABLE sap_fieldglass_workers
ADD COLUMN canonical_resource_id TEXT;

ALTER TABLE sap_fieldglass_workers
ADD COLUMN supplier_id TEXT;

ALTER TABLE sap_fieldglass_workers
ADD COLUMN squad_id TEXT;

ALTER TABLE sap_fieldglass_workers
ADD COLUMN current_location_id TEXT;

ALTER TABLE sap_fieldglass_workers
ADD COLUMN skill TEXT;

ALTER TABLE sap_fieldglass_workers
ADD COLUMN current_rate REAL;

ALTER TABLE sap_fieldglass_workers
ADD COLUMN pii_access INTEGER NOT NULL DEFAULT 0
CHECK (pii_access IN (0, 1));

ALTER TABLE sap_fieldglass_workers
ADD COLUMN availability TEXT;

ALTER TABLE sap_fieldglass_workers
ADD COLUMN canonicalization_status TEXT NOT NULL DEFAULT 'unresolved'
CHECK (canonicalization_status IN ('promoted', 'unresolved'));

ALTER TABLE sap_fieldglass_workers
ADD COLUMN canonicalization_error TEXT;

CREATE INDEX IF NOT EXISTS idx_sap_workers_canonicalization
    ON sap_fieldglass_workers(canonicalization_status, canonical_resource_id);
