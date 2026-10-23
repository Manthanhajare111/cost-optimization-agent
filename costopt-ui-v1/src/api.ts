const DEFAULT_API_ORIGIN = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000/api/v1";

export interface BackendLocation { location_id: string; country: string; is_offshore: boolean }
export interface BackendScenario { scenario_id: string; scenario_name: string; squad_name: string; target_location_id: string; annual_savings: number }
export interface BackendContext {
  scenario_id: string;
  squad_name: string;
  source_locations: { location_id: string; country: string; resource_count: number }[];
  offshore_locations: { location_id: string; country: string }[];
  resource_count: number;
}
export interface BackendPreview {
  source_id: string;
  label: string;
  status: string;
  row_count: number;
  columns: string[];
  rows: Record<string, unknown>[];
}
export interface BackendUpload extends BackendPreview {
  upload_id: string;
  filename: string;
  matched_count: number;
  ignored_count: number;
  data_kind?: string;
  cleaning_status?: string;
  projects?: { sow_reference: string; delivery_countries: string; worker_count: number }[];
}
export interface BackendCleaningRun {
  run_id: string;
  upload_id: string;
  scenario_id: string;
  ready: boolean;
  issues: { row: number; field: string; severity: "critical" | "warning"; message: string }[];
  changes: { row: number; field: string; original: string; proposed: string; reason: string }[];
  candidate_rows: Record<string, string>[];
  counts: { accepted: number; excluded: number; errors: number; warnings: number };
}
export interface BackendValidation {
  ready: boolean;
  selected_sow?: string;
  checks: { category: string; status: "pass" | "warning" | "critical"; message: string }[];
}
export type BackendDocumentKind = "rate_card" | "contractual_evidence" | "delivery_constraints";
export interface BackendSupportingUpload {
  upload_id: string;
  scenario_id: string;
  source_id: "supporting";
  data_kind: BackendDocumentKind;
  filename: string;
  row_count: number;
  columns: string[];
  rows: Record<string, unknown>[];
  sow_references: string[];
}
export interface BackendConsolidatedPreview {
  status: "consolidated";
  ready: boolean;
  row_count: number;
  columns: string[];
  rows: Record<string, unknown>[];
  sow_options: string[];
  documents: { filename: string; upload_id: string; kind: string; rows_checked: number }[];
}
export interface BackendOption {
  option_id: string;
  location_id: string;
  location_name: string;
  annual_savings: number;
  moved_roles: number;
  retained_roles?: number;
  status: "eligible" | "indicative" | "blocked";
  summary: string;
  rationale: string;
  confidence_score?: number;
  baseline_cost?: number;
  future_cost?: number;
  gaps: string[];
  checks: string[];
  resource_details: Record<string, unknown>[];
  talent_rows?: Record<string, unknown>[];
  estimated_downtime_hours?: number;
  transition_duration_weeks?: number;
  knowledge_transfer_hours?: number;
  onboarding_hours?: number;
  downtime_justification?: string;
  coverage_hours?: number;
  timezone_difference_hours?: number;
  next_actions?: string[];
}
export interface BackendAnalysis {
  analysis_id: string;
  project_title: string;
  case_id: string;
  case_name: string;
  scenario_id: string;
  squad_name: string;
  created_at: string;
  input: {
    source_location_id?: string;
    offshore_location_ids: string[];
    horizon_months?: number;
  };
  sources: Record<string, unknown>[];
  options: BackendOption[];
  recommendation: string;
  recommended_option_id?: string;
  decision_status: "recommendation" | "insufficient_evidence";
  blocking_reasons: string[];
  data_gaps: string[];
}
export interface BackendReview {
  review_id: string;
  analysis_id: string;
  created_at: string;
  reviewer_name: string;
  decision: "request_changes" | "ready_for_approval" | "reject" | "approved";
  selected_option_id?: string;
  edited_recommendation: string;
  rationale: string;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

export class CostOptApi {
  constructor(public readonly baseUrl = DEFAULT_API_ORIGIN.replace(/\/$/, "")) {}

  private async request<T>(path: string, init?: RequestInit): Promise<T> {
    const response = await fetch(`${this.baseUrl}${path}`, init);
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new ApiError(response.status, typeof body.detail === "string" ? body.detail : `API request failed (${response.status}).`);
    }
    return response.json() as Promise<T>;
  }

  async health() { return fetch(this.baseUrl.replace(/\/api\/v1$/, "") + "/health").then((response) => { if (!response.ok) throw new ApiError(response.status, "Backend health check failed."); return response.json(); }); }
  scenarios() { return this.request<BackendScenario[]>("/scenarios"); }
  locations() { return this.request<BackendLocation[]>("/locations"); }
  context(scenarioId: string) { return this.request<BackendContext>(`/workforce/context/${encodeURIComponent(scenarioId)}`); }
  preview(source: "fieldglass" | "excel", scenarioId: string, uploadId?: string) { const query = new URLSearchParams({ scenario_id: scenarioId }); if (uploadId) query.set("upload_id", uploadId); return this.request<BackendPreview>(`/workforce/data-preview/${encodeURIComponent(source)}?${query}`); }
  analyses() { return this.request<BackendAnalysis[]>("/workforce/analyses"); }
  analysis(id: string) { return this.request<BackendAnalysis>(`/workforce/analyses/${encodeURIComponent(id)}`); }
  reviews(id: string) { return this.request<BackendReview[]>(`/workforce/analyses/${encodeURIComponent(id)}/reviews`); }
  async upload(scenarioId: string, file: File) {
    const query = new URLSearchParams({ scenario_id: scenarioId, filename: file.name });
    return this.request<BackendUpload>(`/workforce/upload-preview?${query}`, { method: "POST", headers: { "Content-Type": "application/octet-stream" }, body: await file.arrayBuffer() });
  }
  async uploadSupporting(scenarioId: string, file: File, documentKind: BackendDocumentKind) { const query = new URLSearchParams({ scenario_id: scenarioId, filename: file.name, document_kind: documentKind }); return this.request<BackendSupportingUpload>(`/workforce/upload-custom/supporting?${query}`, { method: "POST", headers: { "Content-Type": "application/octet-stream" }, body: await file.arrayBuffer() }); }
  proposeCleaning(uploadId: string, scenarioId: string) { return this.request<BackendCleaningRun>(`/workforce/cleaning/${encodeURIComponent(uploadId)}/propose`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ scenario_id: scenarioId }) }); }
  cleaningRun(runId: string, scenarioId: string) { const query = new URLSearchParams({ scenario_id: scenarioId }); return this.request<BackendCleaningRun>(`/workforce/cleaning-runs/${encodeURIComponent(runId)}?${query}`); }
  approveCleaning(runId: string, scenarioId: string) { return this.request<BackendUpload>(`/workforce/cleaning-runs/${encodeURIComponent(runId)}/approve`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ scenario_id: scenarioId, reviewer_name: "Alex Morgan", approved: true }) }); }
  validateUpload(scenarioId: string, uploadId: string, selectedSow?: string, supportingUploadIds: string[] = [], destinationCountryIds: string[] = []) { return this.request<BackendValidation>("/workforce/validate-upload", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ scenario_id: scenarioId, upload_id: uploadId, source_filter: selectedSow ? { column: "SOW Reference", contains: selectedSow } : null, supporting_upload_ids: supportingUploadIds, destination_country_ids: destinationCountryIds }) }); }
  consolidatedPreview(scenarioId: string, uploadId: string, supportingUploadIds: string[], destinationCountryIds: string[] = []) { return this.request<BackendConsolidatedPreview>("/workforce/consolidated-preview", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ scenario_id: scenarioId, upload_id: uploadId, supporting_upload_ids: supportingUploadIds, destination_country_ids: destinationCountryIds }) }); }
  analyze(body: Record<string, unknown>) { return this.request<BackendAnalysis>("/workforce/analyze", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }); }
  saveReview(id: string, body: Record<string, unknown>) { return this.request<BackendReview>(`/workforce/analyses/${encodeURIComponent(id)}/reviews`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }); }
}

export const costOptApi = new CostOptApi();
