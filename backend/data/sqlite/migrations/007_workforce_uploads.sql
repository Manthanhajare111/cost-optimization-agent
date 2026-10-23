CREATE TABLE IF NOT EXISTS workforce_uploads (
    upload_id TEXT PRIMARY KEY,
    scenario_id TEXT NOT NULL,
    filename TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
