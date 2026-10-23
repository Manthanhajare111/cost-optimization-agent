CREATE TABLE IF NOT EXISTS organizations (
    organization_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'suspended')),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS organization_memberships (
    organization_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('viewer', 'analyst', 'approver', 'admin')),
    status TEXT NOT NULL CHECK (status IN ('active', 'inactive')),
    created_at TEXT NOT NULL,
    PRIMARY KEY (organization_id, user_id),
    FOREIGN KEY (organization_id) REFERENCES organizations(organization_id),
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS contract_versions (
    contract_version_id TEXT PRIMARY KEY,
    contract_id TEXT NOT NULL,
    version_number INTEGER NOT NULL CHECK (version_number > 0),
    status TEXT NOT NULL CHECK (status IN ('draft', 'active', 'superseded', 'expired')),
    effective_from TEXT NOT NULL,
    effective_to TEXT,
    jurisdiction TEXT,
    document_checksum TEXT NOT NULL,
    supersedes_contract_version_id TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (contract_id, version_number),
    FOREIGN KEY (contract_id) REFERENCES contracts(contract_id),
    FOREIGN KEY (supersedes_contract_version_id) REFERENCES contract_versions(contract_version_id)
);

CREATE TABLE IF NOT EXISTS contract_version_clauses (
    contract_version_clause_id TEXT PRIMARY KEY,
    contract_version_id TEXT NOT NULL,
    clause_id TEXT NOT NULL,
    clause_type TEXT NOT NULL,
    clause_text TEXT NOT NULL,
    clause_checksum TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (contract_version_id, clause_id),
    FOREIGN KEY (contract_version_id) REFERENCES contract_versions(contract_version_id),
    FOREIGN KEY (clause_id) REFERENCES contract_clauses(clause_id)
);

CREATE TABLE IF NOT EXISTS rate_card_versions (
    rate_card_version_id TEXT PRIMARY KEY,
    supplier_id TEXT NOT NULL,
    location_id TEXT NOT NULL,
    role TEXT NOT NULL,
    bill_rate_minor INTEGER NOT NULL CHECK (bill_rate_minor >= 0),
    currency TEXT NOT NULL CHECK (length(currency) = 3),
    effective_from TEXT NOT NULL,
    effective_to TEXT,
    status TEXT NOT NULL CHECK (status IN ('draft', 'active', 'superseded', 'expired')),
    source_checksum TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (supplier_id, location_id, role, effective_from),
    FOREIGN KEY (supplier_id) REFERENCES suppliers(supplier_id),
    FOREIGN KEY (location_id) REFERENCES locations(location_id)
);

CREATE TABLE IF NOT EXISTS scenario_runs (
    scenario_run_id TEXT PRIMARY KEY,
    scenario_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('completed', 'human_review_required', 'approved', 'rejected')),
    policy_version TEXT NOT NULL,
    contract_version_id TEXT,
    rate_card_version_id TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (scenario_id) REFERENCES optimization_scenarios(scenario_id),
    FOREIGN KEY (contract_version_id) REFERENCES contract_versions(contract_version_id),
    FOREIGN KEY (rate_card_version_id) REFERENCES rate_card_versions(rate_card_version_id)
);

CREATE TABLE IF NOT EXISTS scenario_input_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    scenario_run_id TEXT NOT NULL,
    snapshot_type TEXT NOT NULL CHECK (snapshot_type IN ('scenario_input', 'recommendation_output')),
    schema_version TEXT NOT NULL,
    content_checksum TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (scenario_run_id, snapshot_type),
    FOREIGN KEY (scenario_run_id) REFERENCES scenario_runs(scenario_run_id)
);

CREATE TABLE IF NOT EXISTS agent_run_audits (
    run_id TEXT PRIMARY KEY,
    scenario_run_id TEXT NOT NULL UNIQUE,
    scenario_id TEXT NOT NULL,
    scenario_name TEXT NOT NULL,
    llm_provider TEXT NOT NULL,
    requires_human_review INTEGER NOT NULL CHECK (requires_human_review IN (0, 1)),
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (scenario_run_id) REFERENCES scenario_runs(scenario_run_id),
    FOREIGN KEY (scenario_id) REFERENCES optimization_scenarios(scenario_id)
);

CREATE TABLE IF NOT EXISTS agent_run_stages (
    stage_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    sequence_number INTEGER NOT NULL CHECK (sequence_number > 0),
    stage_name TEXT NOT NULL,
    status TEXT NOT NULL,
    outcome TEXT NOT NULL,
    prompt_key TEXT NOT NULL,
    model TEXT,
    used_fallback INTEGER NOT NULL CHECK (used_fallback IN (0, 1)),
    narrative_json TEXT NOT NULL,
    tool_traces_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (run_id, sequence_number),
    FOREIGN KEY (run_id) REFERENCES agent_run_audits(run_id)
);

CREATE TABLE IF NOT EXISTS approval_requests (
    approval_request_id TEXT PRIMARY KEY,
    scenario_run_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'approved', 'rejected', 'cancelled')),
    requested_by_user_id TEXT,
    requested_at TEXT NOT NULL,
    due_at TEXT,
    rationale TEXT NOT NULL,
    FOREIGN KEY (scenario_run_id) REFERENCES scenario_runs(scenario_run_id),
    FOREIGN KEY (requested_by_user_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS approval_decisions (
    approval_decision_id TEXT PRIMARY KEY,
    approval_request_id TEXT NOT NULL,
    reviewer_user_id TEXT,
    decision TEXT NOT NULL CHECK (decision IN ('approved', 'rejected')),
    comments TEXT,
    decided_at TEXT NOT NULL,
    FOREIGN KEY (approval_request_id) REFERENCES approval_requests(approval_request_id),
    FOREIGN KEY (reviewer_user_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS procurement_recommendation_sources (
    source_id TEXT PRIMARY KEY,
    proc_recommendation_id TEXT NOT NULL,
    po_id TEXT,
    invoice_id TEXT,
    procurement_contract_id TEXT,
    source_type TEXT NOT NULL CHECK (source_type IN ('purchase_order', 'invoice', 'procurement_contract')),
    created_at TEXT NOT NULL,
    CHECK (po_id IS NOT NULL OR invoice_id IS NOT NULL OR procurement_contract_id IS NOT NULL),
    FOREIGN KEY (proc_recommendation_id) REFERENCES procurement_recommendations(proc_recommendation_id),
    FOREIGN KEY (po_id) REFERENCES purchase_orders(po_id),
    FOREIGN KEY (invoice_id) REFERENCES invoices(invoice_id),
    FOREIGN KEY (procurement_contract_id) REFERENCES procurement_contracts(procurement_contract_id)
);

CREATE INDEX IF NOT EXISTS idx_contract_versions_contract_status ON contract_versions(contract_id, status);
CREATE INDEX IF NOT EXISTS idx_rate_card_versions_lookup ON rate_card_versions(supplier_id, location_id, role, status);
CREATE INDEX IF NOT EXISTS idx_scenario_runs_scenario_created ON scenario_runs(scenario_id, created_at);
CREATE INDEX IF NOT EXISTS idx_agent_run_stages_run ON agent_run_stages(run_id, sequence_number);
CREATE INDEX IF NOT EXISTS idx_approval_requests_run_status ON approval_requests(scenario_run_id, status);
CREATE INDEX IF NOT EXISTS idx_proc_recommendation_sources_recommendation ON procurement_recommendation_sources(proc_recommendation_id);
