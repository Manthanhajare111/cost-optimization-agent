import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";
import type {
  Analysis, AnalysisFile, ApprovalDecision, AuditEvent, DataIssue, Recommendation,
  RecommendationStatus, ReportSnapshot, RepositorySnapshot, Role, WorkflowStep,
} from "./domain";
import { seedSnapshot } from "./mockData";
import { costOptApi, type BackendAnalysis, type BackendDocumentKind, type BackendLocation, type BackendPreview, type BackendReview } from "./api";

type ToastState = { message: string; kind: "success" | "warning" | "error" | "info" } | null;

interface AnalysisState extends RepositorySnapshot {
  navOpen: boolean;
  toast: ToastState;
  backendOnline: boolean;
  backendLoading: boolean;
  backendError: string | null;
  backendLocations: BackendLocation[];
  syncBackend: () => Promise<void>;
  loadBackendSample: (analysisId: string) => Promise<void>;
  uploadBackendFile: (analysisId: string, file: File, documentKind?: "proposal_workbook" | BackendDocumentKind) => Promise<void>;
  validateBackendFile: (analysisId: string, fileId: string, selectedSowOverride?: string) => Promise<void>;
  selectSowForAnalysis: (analysisId: string, sowReference: string) => void;
  runBackendAnalysis: (analysisId: string, countOverrides?: Record<string, number>) => Promise<string>;
  submitForApprovalBackend: (analysisId: string) => Promise<void>;
  decideBackend: (analysisId: string, decision: ApprovalDecision["decision"], comment: string) => Promise<void>;
  createAnalysis: () => string;
  addMockFile: (analysisId: string, file?: File, documentKind?: "proposal_workbook" | BackendDocumentKind) => void;
  confirmFile: (analysisId: string, fileId: string) => void;
  resolveConflict: (analysisId: string) => void;
  resolveIssue: (issueId: string, resolution: "resolved" | "excluded") => void;
  acknowledgeWarnings: (analysisId: string, value: boolean) => void;
  toggleRole: (roleId: string) => void;
  setRoleMoveCount: (roleId: string, count: number) => void;
  updateSetup: (analysisId: string, countries: string[], assumptions: Analysis["assumptions"]) => void;
  runAnalysis: (analysisId: string) => void;
  updateRecommendation: (id: string, status: RecommendationStatus, changes?: Partial<Recommendation>) => void;
  submitForApproval: (analysisId: string) => void;
  decide: (analysisId: string, decision: ApprovalDecision["decision"], comment: string) => void;
  setStep: (analysisId: string, step: WorkflowStep) => void;
  setNavOpen: (value: boolean) => void;
  notify: (toast: ToastState) => void;
  resetDemo: () => void;
}

const cloneSeed = () => structuredClone(seedSnapshot);
const now = () => new Date().toISOString();
const auditEvent = (analysisId: string, action: string, entity: string, comment: string): AuditEvent => ({
  id: `AUD-${Math.round(Math.random() * 999)}`,
  analysisId,
  user: "Alex Morgan",
  action,
  entity,
  date: now(),
  comment,
});

const updateAnalysis = (items: Analysis[], id: string, patch: Partial<Analysis>) =>
  items.map((item) => item.id === id ? { ...item, ...patch, updatedDate: now().slice(0, 10) } : item);

const reviewState = (analysis: BackendAnalysis, reviews: BackendReview[]) => {
  const latest = reviews[0];
  if (latest?.decision === "approved") return { status: "approved" as const, currentStep: "report" as const };
  if (latest?.decision === "ready_for_approval") return { status: "awaiting_approval" as const, currentStep: "approve" as const };
  if (latest?.decision === "request_changes") return { status: "needs_attention" as const, currentStep: "review" as const };
  if (latest?.decision === "reject") return { status: "rejected" as const, currentStep: "approve" as const };
  return analysis.decision_status === "insufficient_evidence"
    ? { status: "needs_attention" as const, currentStep: "review" as const }
    : { status: "in_progress" as const, currentStep: "review" as const };
};

const recommendationDetails = (option: BackendAnalysis["options"][number]) => {
  const moved = option.resource_details.filter((detail) => String(detail.action || "").toLowerCase() === "move");
  const totalCurrentRate = option.resource_details.reduce((sum, detail) => sum + Number(detail.current_rate_eur || 0), 0);
  const annualFactor = totalCurrentRate > 0 && option.baseline_cost
    ? (option.baseline_cost / totalCurrentRate) * 12
    : 10.14 * 12;
  const availability = new Map((option.talent_rows || []).map((row) => [
    `${String(row.level || "").toUpperCase()}`,
    Number(row.available || 0),
  ]));
  const grouped = new Map<string, { sow: string; role: string; count: number; fromRegion: string; currentRate: number; projectedRate: number }>();
  moved.forEach((detail) => {
    const sow = String(detail.sow_reference || "Not provided");
    const role = String(detail.level || detail.role || "Not provided").toUpperCase();
    const rawLocation = String(detail.current_location_id || "Current region");
    const fromRegion = rawLocation.replace(/^loc-/i, "").split("-").map((part) => part.charAt(0).toUpperCase() + part.slice(1)).join(" ");
    const key = `${role}|${fromRegion}`;
    const current = grouped.get(key) || { sow, role, count: 0, fromRegion, currentRate: 0, projectedRate: 0 };
    current.count += 1;
    current.currentRate += Number(detail.current_rate_eur || 0);
    current.projectedRate += Number(detail.projected_rate_eur || 0);
    grouped.set(key, current);
  });
  return [...grouped.entries()].map(([key, detail]) => {
    const currentCost = Math.round(detail.currentRate * annualFactor);
    const projectedCost = Math.round(detail.projectedRate * annualFactor);
    return { id: `${key}`, sow: detail.sow, role: detail.role, count: detail.count,
      availableCount: availability.get(`${detail.role}`) || detail.count, fromRegion: detail.fromRegion,
      toRegion: option.location_name, currentCost, projectedCost, estimatedSavings: Math.max(0, currentCost - projectedCost) };
  });
};

const mapBackend = (analysis: BackendAnalysis, reviews: BackendReview[]) => {
  const latest = reviews[0];
  const selectedId = latest?.selected_option_id || analysis.recommended_option_id;
  const state = reviewState(analysis, reviews);
  const recommendations: Recommendation[] = analysis.options.map((option) => ({
    id: option.option_id, backendOptionId: option.option_id, analysisId: analysis.analysis_id,
    role: `${option.moved_roles} role${option.moved_roles === 1 ? "" : "s"}`,
    sourceLocation: "Current workforce", targetLocation: option.location_name,
    savings: Math.round(option.annual_savings), originalSavings: Math.round(option.annual_savings),
    confidence: Math.round((option.confidence_score ?? 0.7) * 100),
    risk: option.status === "eligible" ? "Low" : option.status === "indicative" ? "Medium" : "High",
    status: selectedId === option.option_id && ["approved", "ready_for_approval"].includes(latest?.decision || "") ? "accepted" : "pending",
    rationale: option.rationale || option.summary, comment: latest?.selected_option_id === option.option_id ? latest.rationale : "",
    baselineCost: Math.round((option.baseline_cost || 0) * 12), futureCost: Math.round((option.future_cost || 0) * 12),
    isRecommended: option.option_id === analysis.recommended_option_id,
    details: recommendationDetails(option),
    checks: option.checks, gaps: option.gaps,
    estimatedDowntimeHours: option.estimated_downtime_hours,
    transitionDurationWeeks: option.transition_duration_weeks,
    knowledgeTransferHours: option.knowledge_transfer_hours,
    onboardingHours: option.onboarding_hours,
    coverageHours: option.coverage_hours,
    timezoneDifferenceHours: option.timezone_difference_hours,
    nextActions: option.next_actions,
  }));
  const date = analysis.created_at.slice(0, 10);
  const item: Analysis = {
    id: analysis.analysis_id, name: analysis.project_title || analysis.case_name, ...state,
    createdBy: "Backend workflow", createdDate: date, updatedDate: date,
    estimatedSavings: Math.round(analysis.options.find((option) => option.option_id === selectedId)?.annual_savings || analysis.options[0]?.annual_savings || 0),
    selectedCountries: analysis.options.map((option) => option.location_name),
    assumptions: { horizon: Math.max(1, Math.round((analysis.input.horizon_months || 36) / 12)), transitionCost: 0, contingency: 10, notes: analysis.recommendation },
    warningsAcknowledged: analysis.decision_status !== "insufficient_evidence", origin: "backend", scenarioId: analysis.scenario_id,
  };
  const audit: AuditEvent[] = reviews.map((review) => ({ id: review.review_id, analysisId: analysis.analysis_id, user: review.reviewer_name, action: review.decision.replaceAll("_", " "), entity: "Approval", date: review.created_at, comment: review.rationale }));
  const selected = analysis.options.find((option) => option.option_id === selectedId);
  const approval: ApprovalDecision | undefined = latest && latest.decision !== "ready_for_approval" ? { analysisId: analysis.analysis_id, decision: latest.decision === "approved" ? "approved" : latest.decision === "reject" ? "rejected" : "changes_requested", approver: latest.reviewer_name, comment: latest.rationale, decidedAt: latest.created_at } : undefined;
  const report: ReportSnapshot | undefined = latest?.decision === "approved" && approval ? { analysisId: analysis.analysis_id, generatedAt: latest.created_at, executiveSummary: analysis.recommendation, dataReadiness: "Backend evidence and eligibility checks passed before approval.", scope: analysis.options.map((option) => option.location_name).join(", "), currentCost: Math.round(selected?.baseline_cost || 0), proposedCost: Math.round(selected?.future_cost || 0), annualSavings: Math.round(selected?.annual_savings || 0), decision: approval, audit } : undefined;
  return { item, recommendations, audit, approval, report };
};

const rolesFromPreview = (analysisId: string, preview: BackendPreview, sourceCountry = "Germany"): Role[] => {
  const grouped = new Map<string, { count: number; cost: number; location: string }>();
  preview.rows.forEach((row) => {
    const title = String(row.role || row.worker_role || row.skill || "Workforce role");
    const current = grouped.get(title) || { count: 0, cost: 0, location: sourceCountry };
    current.count += 1;
    current.cost += Number(row.current_rate_eur || row.current_rate || row.annual_cost || 0) * 12;
    current.location = String(row.country || row.location || sourceCountry).replace(/^loc-/, "");
    grouped.set(title, current);
  });
  return [...grouped].map(([title, value], index) => ({ id: `ROL-${index + 1}`, analysisId, title, location: value.location, headcount: value.count, annualCost: Math.round(value.cost), selected: true, moveCount: value.count }));
};

const cleaningIssues = (analysisId: string, run: import("./api").BackendCleaningRun): DataIssue[] => {
  const findings: DataIssue[] = run.issues.map((issue, index) => ({
    id: `BE-CLEAN-${index}`, analysisId,
    severity: issue.severity === "critical" ? "error" : "warning",
    record: issue.row ? `Row ${issue.row} · ${issue.field}` : issue.field,
    message: issue.message, resolutionStatus: "open",
  }));
  const passedWorkbookRules = [
    { record: "sow reference", pattern: /sow reference|headers|workbook|rows/i, message: "SOW references passed the required-value, format, and duplicate checks." },
    { record: "worker total", pattern: /^(?:e[1-5]|worker total)$/i, message: "E1-E5 values and worker totals passed the workforce checks." },
    { record: "delivery countries", pattern: /delivery countr/i, message: "Delivery-country values passed the required-value check; multiple countries remain allowed." },
  ].filter((rule) => !run.issues.some((issue) => rule.pattern.test(issue.field)));
  return [...findings, ...passedWorkbookRules.map((rule, index): DataIssue => ({
    id: `BE-CLEAN-${index}`, analysisId,
    severity: "success", record: rule.record, message: rule.message, resolutionStatus: "resolved",
  }))];
};

const validationIssues = (analysisId: string, result: import("./api").BackendValidation): DataIssue[] => result.checks.map((check, index) => ({
  id: `BE-VALIDATE-${Date.now()}-${index}`, analysisId,
  severity: check.status === "critical" ? "error" : check.status === "warning" ? "warning" : "success",
  record: check.category, message: check.message,
  resolutionStatus: check.status === "pass" ? "resolved" : "open",
}));

export const useAnalysisStore = create<AnalysisState>()(persist((set, get) => ({
  ...cloneSeed(),
  navOpen: false,
  toast: null,
  backendOnline: false,
  backendLoading: false,
  backendError: null,
  backendLocations: [],

  syncBackend: async () => {
    set({ backendLoading: true, backendError: null });
    try {
      await costOptApi.health();
      const [locations, analyses] = await Promise.all([costOptApi.locations(), costOptApi.analyses()]);
      const reviewSets = await Promise.all(analyses.map((analysis) => costOptApi.reviews(analysis.analysis_id)));
      const mapped = analyses.map((analysis, index) => mapBackend(analysis, reviewSets[index]));
      set((state) => {
        const localIds = new Set(state.analyses.filter((item) => item.origin === "local").map((item) => item.id));
        const localOnly = <T extends { analysisId: string }>(items: T[]) => items.filter((item) => localIds.has(item.analysisId));
        return {
          backendOnline: true, backendLoading: false, backendError: null, backendLocations: locations,
          analyses: [...state.analyses.filter((item) => item.origin === "local"), ...mapped.map((entry) => entry.item)],
          files: localOnly(state.files), issues: localOnly(state.issues), roles: localOnly(state.roles),
          recommendations: [...localOnly(state.recommendations), ...mapped.flatMap((entry) => entry.recommendations)],
          approvals: [...localOnly(state.approvals), ...mapped.flatMap((entry) => entry.approval ? [entry.approval] : [])], reports: [...localOnly(state.reports), ...mapped.flatMap((entry) => entry.report ? [entry.report] : [])],
          audit: [...localOnly(state.audit), ...mapped.flatMap((entry) => entry.audit)],
        };
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : "Backend is unavailable.";
      set({ backendOnline: false, backendLoading: false, backendError: message });
    }
  },

  loadBackendSample: async (analysisId) => {
    set({ backendLoading: true, backendError: null });
    try {
      const analysis = get().analyses.find((item) => item.id === analysisId);
      const scenarioId = analysis?.scenarioId || "scn-001";
      const [context, preview] = await Promise.all([costOptApi.context(scenarioId), costOptApi.preview("fieldglass", scenarioId)]);
      const file: AnalysisFile = { id: `FIL-${Date.now()}`, analysisId, name: preview.label, type: "Fieldglass mock", status: "review_required", issues: 0 };
      set((state) => ({ backendOnline: true, backendLoading: false, files: [file, ...state.files.filter((item) => item.analysisId !== analysisId)], roles: [...state.roles.filter((item) => item.analysisId !== analysisId), ...rolesFromPreview(analysisId, preview, context.source_locations[0]?.country)], analyses: updateAnalysis(state.analyses, analysisId, { status: "in_progress", sourceMode: "fieldglass", scenarioId }), audit: [auditEvent(analysisId, "Loaded backend sample", "File", preview.label), ...state.audit], toast: { message: "Backend Fieldglass-style sample loaded for review.", kind: "success" } }));
    } catch (error) { const message = error instanceof Error ? error.message : "Could not load backend sample."; set({ backendLoading: false, backendError: message, toast: { message, kind: "error" } }); throw error; }
  },

  uploadBackendFile: async (analysisId, selectedFile, documentKind = "proposal_workbook") => {
    set({ backendLoading: true, backendError: null });
    try {
      const scenarioId = get().analyses.find((item) => item.id === analysisId)?.scenarioId || "scn-001";
      if (documentKind !== "proposal_workbook") {
        const upload = await costOptApi.uploadSupporting(scenarioId, selectedFile, documentKind);
        const file: AnalysisFile = { id: `FIL-${Date.now()}`, analysisId, name: upload.filename, type: upload.data_kind, status: "review_required", issues: 0, fileSize: selectedFile.size, uploadedAt: new Date().toISOString(), backendUploadId: upload.upload_id, validationStatus: "pending" };
        set((state) => ({ backendOnline: true, backendLoading: false, files: [file, ...state.files.filter((item) => item.analysisId !== analysisId || item.type !== upload.data_kind)], analyses: updateAnalysis(state.analyses, analysisId, { status: "in_progress", sourceMode: "excel", scenarioId }), audit: [auditEvent(analysisId, "Uploaded supporting document", "File", `${upload.data_kind}: ${upload.filename}`), ...state.audit], toast: { message: `${upload.filename} parsed. Confirm the data package to validate and consolidate it.`, kind: "success" } }));
        return;
      }
      const upload = await costOptApi.upload(scenarioId, selectedFile);
      const selectedSow = upload.projects?.map((project) => project.sow_reference).find(Boolean);
      const file: AnalysisFile = { id: `FIL-${Date.now()}`, analysisId, name: upload.filename, type: upload.data_kind || "Workforce", status: "review_required", issues: 0, fileSize: selectedFile.size, uploadedAt: new Date().toISOString(), backendUploadId: upload.upload_id, selectedSow, validationStatus: "pending" };
      set((state) => ({ backendOnline: true, backendLoading: false, files: [file, ...state.files.filter((item) => item.analysisId !== analysisId || ["rate_card", "contractual_evidence", "delivery_constraints"].includes(item.type))], roles: [...state.roles.filter((item) => item.analysisId !== analysisId), ...rolesFromPreview(analysisId, upload)], issues: state.issues.filter((item) => item.analysisId !== analysisId), analyses: updateAnalysis(state.analyses, analysisId, { status: "in_progress", sourceMode: "excel", backendUploadId: upload.upload_id, scenarioId }), audit: [auditEvent(analysisId, "Uploaded backend file", "File", upload.filename), ...state.audit], toast: { message: "File parsed. Confirm the extracted data, then validate it in Check Data.", kind: "success" } }));
    } catch (error) { const message = error instanceof Error ? error.message : "Upload failed."; set({ backendLoading: false, backendError: message, toast: { message, kind: "error" } }); throw error; }
  },

  validateBackendFile: async (analysisId, fileId, selectedSowOverride) => {
    const state = get(); const file = state.files.find((item) => item.id === fileId); const analysis = state.analyses.find((item) => item.id === analysisId);
    if (!file || !analysis) throw new Error("Uploaded file not found.");
    if (["rate_card", "contractual_evidence", "delivery_constraints"].includes(file.type)) {
      const primary = state.files.find((item) => item.analysisId === analysisId && item.type === "proposal_workbook");
      if (!primary) throw new Error("Upload the Proposal SOW workbook before validating supporting documents.");
      return get().validateBackendFile(analysisId, primary.id, primary.selectedSow);
    }
    if (!file.backendUploadId || analysis.sourceMode === "fieldglass") {
      get().confirmFile(analysisId, fileId);
      set((current) => ({ files: current.files.map((item) => item.id === fileId ? { ...item, validationStatus: "ready" } : item) }));
      return;
    }
    set({ backendLoading: true, backendError: null });
    try {
      const scenarioId = analysis.scenarioId || "scn-001";
      let uploadId = file.backendUploadId;
      let approvedUpload: import("./api").BackendUpload | undefined;
      // Always create a fresh cleaning run before validation. Cleaning findings
      // are persisted in browser state, so reusing an earlier run can keep
      // findings from rules that have since changed (for example, treating a
      // multi-country SOW as invalid). The backend resolves approved uploads
      // to their original workbook and evaluates it with the current rules.
      const cleaning = file.type === "proposal_workbook" ? await costOptApi.proposeCleaning(uploadId, scenarioId) : undefined;
      const cleaningRunId = cleaning?.run_id || file.cleaningRunId;
      const cleaningReady = cleaning?.ready ?? file.cleaningReady;
      const selectedSow = selectedSowOverride || file.selectedSow || cleaning?.candidate_rows.map((row) => row["sow reference"]).find(Boolean);
      if (cleaningRunId) {
        if (!cleaningReady) {
          const mappedCleaningIssues = cleaning ? cleaningIssues(analysisId, cleaning) : get().issues.filter((item) => item.analysisId === analysisId);
          set((current) => ({ backendLoading: false, issues: [...current.issues.filter((item) => item.analysisId !== analysisId), ...mappedCleaningIssues], files: current.files.map((item) => item.id === fileId ? { ...item, cleaningRunId, cleaningReady: false, selectedSow, issues: mappedCleaningIssues.filter((issue) => issue.severity !== "success").length, validationStatus: "blocked" } : item), analyses: updateAnalysis(current.analyses, analysisId, { currentStep: "check-data", status: "needs_attention" }), toast: { message: "Backend cleaning found blocking issues. Correct the workbook and upload it again.", kind: "error" } }));
          return;
        }
        approvedUpload = await costOptApi.approveCleaning(cleaningRunId, scenarioId);
        uploadId = approvedUpload.upload_id;
      }
      const supportingUploadIds = get().files.filter((item) => item.analysisId === analysisId && ["rate_card", "contractual_evidence", "delivery_constraints"].includes(item.type) && item.backendUploadId).map((item) => item.backendUploadId!);
      const destinationCountryIds = analysis.selectedCountries.map((country) => get().backendLocations.find((location) => location.country === country)?.location_id).filter((value): value is string => Boolean(value));
      const validation = await costOptApi.validateUpload(scenarioId, uploadId, selectedSow || approvedUpload?.projects?.[0]?.sow_reference, supportingUploadIds, destinationCountryIds);
      const mappedIssues = validationIssues(analysisId, validation);
      set((current) => ({
        backendOnline: true, backendLoading: false,
        files: current.files.map((item) => item.id === fileId ? { ...item, backendUploadId: uploadId, cleaningRunId, cleaningReady, issues: mappedIssues.filter((issue) => issue.severity !== "success").length, selectedSow: validation.selected_sow || item.selectedSow, validationStatus: validation.ready ? "ready" : "blocked" } : item.analysisId === analysisId && ["rate_card", "contractual_evidence", "delivery_constraints"].includes(item.type) ? { ...item, validationStatus: validation.ready ? "ready" : "blocked" } : item),
        roles: approvedUpload ? [...current.roles.filter((item) => item.analysisId !== analysisId), ...rolesFromPreview(analysisId, approvedUpload)] : current.roles,
        issues: [...current.issues.filter((item) => item.analysisId !== analysisId), ...mappedIssues],
        analyses: updateAnalysis(current.analyses, analysisId, { backendUploadId: uploadId, currentStep: "check-data", status: validation.ready ? "in_progress" : "needs_attention" }),
        audit: [auditEvent(analysisId, "Completed backend validation", "File", validation.ready ? "Validation passed." : "Validation returned blocking findings."), ...current.audit],
        toast: { message: validation.ready ? "Backend validation passed." : "Backend validation found issues that must be resolved.", kind: validation.ready ? "success" : "warning" },
      }));
    } catch (error) { const message = error instanceof Error ? error.message : "Backend validation failed."; set({ backendLoading: false, backendError: message, toast: { message, kind: "error" } }); throw error; }
  },

  runBackendAnalysis: async (analysisId, countOverrides = {}) => {
    const state = get(); const analysis = state.analyses.find((item) => item.id === analysisId);
    if (!analysis) throw new Error("Analysis not found.");
    set({ backendLoading: true, backendError: null });
    try {
      const scenarioId = analysis.scenarioId || "scn-001";
      const context = await costOptApi.context(scenarioId);
      const locationIds = analysis.selectedCountries.map((country) => state.backendLocations.find((location) => location.country === country)?.location_id).filter((value): value is string => Boolean(value));
      if (!locationIds.length) throw new Error("Selected countries are not available in backend reference data.");
      const source = analysis.sourceMode || "fieldglass";
      const validatedFile = state.files.find((item) => item.analysisId === analysisId && item.type === "proposal_workbook" && item.validationStatus === "ready");
      const supportingUploadIds = state.files.filter((item) => item.analysisId === analysisId && ["rate_card", "contractual_evidence", "delivery_constraints"].includes(item.type) && item.backendUploadId).map((item) => item.backendUploadId!);
      const moveCountsBySowLevel: Record<string, number> = {};
      state.roles.filter((role) => role.analysisId === analysisId).forEach((role) => {
        const match = role.title.match(/^(.*)-(E[1-5])$/i);
        if (!match || (validatedFile?.selectedSow && match[1].toLowerCase() !== validatedFile.selectedSow.toLowerCase())) return;
        moveCountsBySowLevel[match[2].toUpperCase()] = role.moveCount ?? (role.selected ? role.headcount : 0);
      });
      Object.assign(moveCountsBySowLevel, analysis.moveCountsBySowLevel || {}, countOverrides);
      const result = await costOptApi.analyze({ case_id: "right_shoring", scenario_id: scenarioId, project_title: analysis.name, ...(source !== "excel" ? { source_location_id: context.source_locations[0]?.location_id } : {}), offshore_location_ids: locationIds, source_ids: [source], source_modes: { [source]: source === "excel" ? "manual" : "auto" }, supporting_upload_ids: supportingUploadIds, move_counts_by_sow_level: moveCountsBySowLevel, ...(validatedFile?.selectedSow ? { source_filters: { excel: { column: "SOW Reference", contains: validatedFile.selectedSow } } } : {}), ...(analysis.backendUploadId ? { upload_id: analysis.backendUploadId, source_upload_ids: { [source]: analysis.backendUploadId } } : {}) });
      const mapped = mapBackend(result, []);
      mapped.item.moveCountsBySowLevel = moveCountsBySowLevel;
      set((current) => ({ backendOnline: true, backendLoading: false, analyses: [mapped.item, ...current.analyses.filter((item) => item.id !== analysisId)], files: current.files.map((item) => item.analysisId === analysisId ? { ...item, analysisId: result.analysis_id } : item), roles: current.roles.map((item) => item.analysisId === analysisId ? { ...item, analysisId: result.analysis_id } : item), issues: current.issues.map((item) => item.analysisId === analysisId ? { ...item, analysisId: result.analysis_id } : item), recommendations: [...current.recommendations.filter((item) => item.analysisId !== analysisId), ...mapped.recommendations], audit: [auditEvent(result.analysis_id, "Generated backend recommendations", "Analysis", `${mapped.recommendations.length} backend options generated.`), ...current.audit.filter((item) => item.analysisId !== analysisId)], toast: { message: "Backend analysis complete. Review the governed options.", kind: "success" } }));
      return result.analysis_id;
    } catch (error) { const message = error instanceof Error ? error.message : "Backend analysis failed."; set({ backendLoading: false, backendError: message, toast: { message, kind: "error" } }); throw error; }
  },

  submitForApprovalBackend: async (analysisId) => {
    const state = get(); const analysis = state.analyses.find((item) => item.id === analysisId);
    if (analysis?.origin !== "backend") { state.submitForApproval(analysisId); return; }
    const selected = state.recommendations.find((item) => item.analysisId === analysisId && ["accepted", "modified"].includes(item.status));
    if (!selected) throw new Error("Select an eligible recommendation before continuing.");
    set({ backendLoading: true, backendError: null });
    try {
      await costOptApi.saveReview(analysisId, { reviewer_name: "Alex Morgan", decision: "ready_for_approval", selected_option_id: selected.backendOptionId || selected.id, edited_recommendation: (selected.rationale || "Recommendation reviewed by a human reviewer.").padEnd(10, "."), rationale: (selected.comment || "Recommendation reviewed and submitted for formal approval.").padEnd(10, ".") });
      get().submitForApproval(analysisId); set({ backendOnline: true, backendLoading: false });
    } catch (error) { const message = error instanceof Error ? error.message : "Submission failed."; set({ backendLoading: false, backendError: message, toast: { message, kind: "error" } }); throw error; }
  },

  decideBackend: async (analysisId, decision, comment) => {
    const state = get(); const selected = state.recommendations.find((item) => item.analysisId === analysisId && ["accepted", "modified"].includes(item.status));
    if (!state.analyses.find((item) => item.id === analysisId)?.origin || state.analyses.find((item) => item.id === analysisId)?.origin !== "backend") { state.decide(analysisId, decision, comment); return; }
    set({ backendLoading: true, backendError: null });
    try {
      const backendDecision = decision === "approved" ? "approved" : decision === "rejected" ? "reject" : "request_changes";
      await costOptApi.saveReview(analysisId, { reviewer_name: "Alex Morgan", decision: backendDecision, selected_option_id: selected?.backendOptionId || selected?.id, edited_recommendation: (selected?.rationale || comment || "Human reviewer recorded a decision.").padEnd(10, "."), rationale: (comment || "Human reviewer recorded this final decision.").padEnd(10, ".") });
      get().decide(analysisId, decision, comment); set({ backendOnline: true, backendLoading: false });
    } catch (error) { const message = error instanceof Error ? error.message : "Decision could not be saved."; set({ backendLoading: false, backendError: message, toast: { message, kind: "error" } }); throw error; }
  },

  createAnalysis: () => {
    const id = `ANA-${1100 + get().analyses.length}`;
    const date = now().slice(0, 10);
    const analysis: Analysis = {
      id, name: `New Cost Optimization Analysis ${id}`, status: "draft", currentStep: "add-data",
      createdBy: "Alex Morgan", createdDate: date, updatedDate: date, estimatedSavings: 0, origin: "local", scenarioId: "scn-001",
      selectedCountries: [], assumptions: { horizon: 3, transitionCost: 0, contingency: 10, notes: "" }, warningsAcknowledged: false,
    };
    set((state) => ({ analyses: [analysis, ...state.analyses], audit: [auditEvent(id, "Created analysis", "Analysis", "New draft created."), ...state.audit] }));
    return id;
  },

  addMockFile: (analysisId, file, documentKind = "proposal_workbook") => {
    const nextFile: AnalysisFile = {
      id: `FIL-${Math.random().toString(36).slice(2, 8)}`, analysisId, name: file?.name || "fieldglass-sample.xlsx", type: documentKind,
      status: "review_required", issues: documentKind === "proposal_workbook" ? 1 : 0,
      fileSize: file?.size, uploadedAt: new Date().toISOString(),
    };
    const roles: Role[] = [
      { id: `ROL-${analysisId}-1`, analysisId, title: "Senior Developer", location: "Germany", headcount: 8, annualCost: 960000, selected: true },
      { id: `ROL-${analysisId}-2`, analysisId, title: "QA Engineer", location: "Germany", headcount: 5, annualCost: 480000, selected: true },
      { id: `ROL-${analysisId}-3`, analysisId, title: "Product Owner", location: "Germany", headcount: 2, annualCost: 260000, selected: false },
    ];
    const issues: DataIssue[] = [
      { id: `ISS-${analysisId}-1`, analysisId, severity: "warning", record: "Row 238 · Role FG-238", message: "Rate card expires within the analysis horizon.", resolutionStatus: "open" },
    ];
    set((state) => ({
      files: [nextFile, ...state.files.filter((item) => item.analysisId !== analysisId || item.type !== documentKind)],
      roles: documentKind === "proposal_workbook" ? [...state.roles.filter((item) => item.analysisId !== analysisId), ...roles] : state.roles,
      issues: documentKind === "proposal_workbook" ? [...state.issues.filter((item) => item.analysisId !== analysisId), ...issues] : state.issues,
      analyses: updateAnalysis(state.analyses, analysisId, { status: "in_progress" }),
      audit: [auditEvent(analysisId, file ? "Uploaded file" : "Loaded sample data", "File", nextFile.name), ...state.audit],
      toast: { message: "Data loaded. Review the extracted records before continuing.", kind: "success" },
    }));
  },

  confirmFile: (analysisId, fileId) => set((state) => ({
    files: state.files.map((item) => item.id === fileId ? { ...item, status: "ready" } : item),
    analyses: updateAnalysis(state.analyses, analysisId, { currentStep: "check-data" }),
    audit: [auditEvent(analysisId, "Confirmed extracted data", "File", fileId), ...state.audit],
    toast: { message: "Extracted data confirmed.", kind: "success" },
  })),

  resolveConflict: (analysisId) => set((state) => ({
    issues: state.issues.map((issue) => issue.analysisId === analysisId && issue.severity === "info" ? { ...issue, resolutionStatus: "resolved" } : issue),
    toast: { message: "The source conflict was resolved.", kind: "success" },
  })),

  resolveIssue: (issueId, resolution) => set((state) => {
    const target = state.issues.find((issue) => issue.id === issueId);
    return {
      issues: state.issues.map((issue) => issue.id === issueId ? { ...issue, resolutionStatus: resolution } : issue),
      audit: target ? [auditEvent(target.analysisId, resolution === "resolved" ? "Resolved data issue" : "Excluded record", "Data issue", target.record), ...state.audit] : state.audit,
    };
  }),

  acknowledgeWarnings: (analysisId, value) => set((state) => ({ analyses: updateAnalysis(state.analyses, analysisId, { warningsAcknowledged: value }) })),
  selectSowForAnalysis: (analysisId, sowReference) => set((state) => ({
    files: state.files.map((file) => file.analysisId === analysisId && file.type === "proposal_workbook"
      ? { ...file, selectedSow: sowReference }
      : file),
    audit: [auditEvent(analysisId, "Changed analysis SOW", "Analysis scope", sowReference), ...state.audit],
    toast: { message: `${sowReference} selected for analysis. Existing document validation remains unchanged.`, kind: "success" },
  })),
  toggleRole: (roleId) => set((state) => ({ roles: state.roles.map((role) => role.id === roleId ? { ...role, selected: !role.selected } : role) })),
  setRoleMoveCount: (roleId, count) => set((state) => ({ roles: state.roles.map((role) => role.id === roleId
    ? { ...role, moveCount: Math.max(0, Math.min(role.headcount, Math.round(count))), selected: count > 0 }
    : role) })),
  updateSetup: (analysisId, selectedCountries, assumptions) => set((state) => ({ analyses: updateAnalysis(state.analyses, analysisId, { selectedCountries, assumptions }) })),

  runAnalysis: (analysisId) => set((state) => {
    const analysis = state.analyses.find((item) => item.id === analysisId)!;
    const selected = state.roles.filter((role) => role.analysisId === analysisId && role.selected);
    const targets = analysis.selectedCountries.length ? analysis.selectedCountries : ["India"];
    const recommendations: Recommendation[] = selected.map((role, index) => {
      const savings = Math.round(role.annualCost * (index % 2 ? .31 : .36));
      return { id: `REC-${index + 1}`, analysisId, role: role.title, sourceLocation: role.location, targetLocation: targets[index % targets.length], savings, originalSavings: savings, confidence: 87 - index * 5, risk: index % 2 ? "Medium" : "Low", status: "pending", rationale: index % 2 ? "Balanced cost and time-zone coverage with manageable transition effort." : "Verified skills and capacity provide a strong cost opportunity.", comment: "" };
    });
    return {
      recommendations: [...state.recommendations.filter((item) => item.analysisId !== analysisId), ...recommendations],
      analyses: updateAnalysis(state.analyses, analysisId, { currentStep: "review", status: "in_progress", estimatedSavings: recommendations.reduce((sum, item) => sum + item.savings, 0) }),
      audit: [auditEvent(analysisId, "Generated recommendations", "Analysis", `${recommendations.length} options generated.`), ...state.audit],
      toast: { message: "Analysis complete. Review the recommendations.", kind: "success" },
    };
  }),

  updateRecommendation: (id, status, changes = {}) => set((state) => {
    const target = state.recommendations.find((item) => item.id === id);
    const recommendations = state.recommendations.map((item) => {
      if (item.id !== id) return item;
      const details = item.details?.map((detail) => {
        const totalDetailSavings = item.details?.reduce((sum, value) => sum + value.estimatedSavings, 0) || 0;
        const requestedSavings = changes.savings ?? item.savings;
        const share = totalDetailSavings > 0 ? detail.estimatedSavings / totalDetailSavings : 1 / Math.max(item.details?.length || 1, 1);
        const estimatedSavings = changes.savings === undefined ? detail.estimatedSavings : Math.round(requestedSavings * share);
        return { ...detail, toRegion: changes.targetLocation ?? detail.toRegion, estimatedSavings,
          projectedCost: changes.savings === undefined ? detail.projectedCost : Math.max(0, detail.currentCost - estimatedSavings) };
      });
      return { ...item, ...changes, status, details };
    });
    const total = target ? recommendations.filter((item) => item.analysisId === target.analysisId && ["accepted", "modified"].includes(item.status)).reduce((sum, item) => sum + item.savings, 0) : 0;
    return {
      recommendations,
      analyses: target ? updateAnalysis(state.analyses, target.analysisId, { estimatedSavings: total }) : state.analyses,
      audit: target ? [auditEvent(target.analysisId, `Recommendation ${status.replaceAll("_", " ")}`, "Recommendation", target.role), ...state.audit] : state.audit,
      toast: { message: `Recommendation marked ${status.replaceAll("_", " ")}.`, kind: "success" },
    };
  }),

  submitForApproval: (analysisId) => set((state) => ({
    analyses: updateAnalysis(state.analyses, analysisId, { status: "awaiting_approval", currentStep: "approve" }),
    audit: [auditEvent(analysisId, "Submitted for approval", "Analysis", "Human review completed."), ...state.audit],
  })),

  decide: (analysisId, decision, comment) => set((state) => {
    const approval: ApprovalDecision = { analysisId, decision, approver: "Alex Morgan", comment, decidedAt: now() };
    const analysis = state.analyses.find((item) => item.id === analysisId)!;
    const recs = state.recommendations.filter((item) => item.analysisId === analysisId && ["accepted", "modified"].includes(item.status));
    const currentCost = state.roles.filter((role) => role.analysisId === analysisId && role.selected).reduce((sum, role) => sum + role.annualCost, 0);
    const annualSavings = recs.reduce((sum, item) => sum + item.savings, 0);
    const event = auditEvent(analysisId, decision.replaceAll("_", " "), "Approval", comment);
    const snapshot: ReportSnapshot = {
      analysisId, generatedAt: now(), executiveSummary: `${analysis.name} identifies ${annualSavings.toLocaleString("en-IE")} EUR in annual savings across ${recs.length} accepted recommendations.`,
      dataReadiness: "All blocking data issues were resolved before review.", scope: `${analysis.selectedCountries.join(", ")} · ${recs.length} selected recommendation(s)`,
      currentCost, proposedCost: Math.max(0, currentCost - annualSavings), annualSavings, decision: approval, audit: [event, ...state.audit.filter((item) => item.analysisId === analysisId)],
    };
    const approved = decision === "approved";
    return {
      approvals: [approval, ...state.approvals.filter((item) => item.analysisId !== analysisId)],
      reports: approved ? [snapshot, ...state.reports.filter((item) => item.analysisId !== analysisId)] : state.reports,
      analyses: updateAnalysis(state.analyses, analysisId, { status: approved ? "approved" : decision === "rejected" ? "rejected" : "needs_attention", currentStep: approved ? "report" : decision === "changes_requested" ? "review" : "approve" }),
      audit: [event, ...state.audit], toast: { message: approved ? "Analysis approved and report generated." : "Decision saved.", kind: approved ? "success" : "warning" },
    };
  }),

  setStep: (analysisId, currentStep) => set((state) => ({ analyses: updateAnalysis(state.analyses, analysisId, { currentStep }) })),
  setNavOpen: (navOpen) => set({ navOpen }),
  notify: (toast) => set({ toast }),
  resetDemo: () => set({ ...cloneSeed(), toast: { message: "Demo data reset.", kind: "info" }, navOpen: false }),
}), {
  name: "costopt-ui-v1",
  version: 4,
  storage: createJSONStorage(() => localStorage),
  migrate: (persistedState, version) => {
    const state = persistedState as AnalysisState;
    let migrated = state;
    const legacyRows: Record<string, string> = {
      "Role FG-238": "Row 238 · Role FG-238",
      "Worker 1842": "Row 1842 · Worker 1842",
      "Role FIN-14": "Row 14 · Role FIN-14",
      "Supplier S-009": "Row 9 · Supplier S-009",
    };
    if (version < 2 && state.issues) migrated = { ...migrated, issues: state.issues.map((issue) => ({ ...issue, record: legacyRows[issue.record] || issue.record })) };
    if (version < 3 && state.files) migrated = { ...migrated, files: state.files.map((file) => {
      if (file.type !== "Workforce") return file;
      const name = file.name.toLowerCase().replace(/[_-]+/g, " ");
      const type = /rate\s*card|rates?\b/.test(name) ? "rate_card"
        : /delivery.*constraint|constraint|restriction|permission|permit/.test(name) ? "delivery_constraints"
        : /contract|clause|evidence/.test(name) ? "contractual_evidence"
        : /proposal|\bsow\b|workforce/.test(name) ? "proposal_workbook" : file.type;
      return { ...file, type };
    }) };
    if (version < 4 && migrated.files) migrated = { ...migrated, files: migrated.files.map((file) =>
      file.backendUploadId && file.validationStatus && file.status === "error"
        ? { ...file, status: "ready" as const }
        : file
    ) };
    return migrated;
  },
  partialize: ({ navOpen: _nav, toast: _toast, backendLoading: _loading, backendError: _error, ...domain }) => domain,
}));

export const analysisTotals = (analysisId: string, state: Pick<AnalysisState, "roles" | "recommendations">) => {
  const recommendations = state.recommendations.filter((item) => item.analysisId === analysisId && item.status !== "removed");
  const decided = recommendations.filter((item) => ["accepted", "modified"].includes(item.status));
  const preview = recommendations.find((item) => item.isRecommended) || recommendations.find((item) => item.status === "pending");
  const active = decided.length ? decided : preview ? [preview] : [];
  const roleCost = state.roles.filter((role) => role.analysisId === analysisId && role.selected).reduce((sum, role) => sum + role.annualCost, 0);
  const backendCost = active.reduce((sum, item) => sum + (item.baselineCost || 0), 0);
  const current = backendCost || roleCost;
  const savings = active.reduce((sum, item) => sum + item.savings, 0);
  const backendFutureCost = active.reduce((sum, item) => sum + (item.futureCost || 0), 0);
  const proposed = backendFutureCost && !active.some((item) => item.status === "modified") ? backendFutureCost : Math.max(0, current - savings);
  return { current, proposed, savings, firstYear: Math.max(0, savings - current * .08), confidence: active.length ? Math.round(active.reduce((sum, item) => sum + item.confidence, 0) / active.length) : 0 };
};
