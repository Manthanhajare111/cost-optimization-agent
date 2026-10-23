CREATE TABLE IF NOT EXISTS workforce_case_analyses (
    analysis_id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS workforce_case_reviews (
    review_id TEXT PRIMARY KEY,
    analysis_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (analysis_id) REFERENCES workforce_case_analyses(analysis_id)
);

CREATE INDEX IF NOT EXISTS idx_workforce_case_analyses_created
    ON workforce_case_analyses(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_workforce_case_reviews_analysis
    ON workforce_case_reviews(analysis_id, created_at DESC);
