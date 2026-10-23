import { useEffect, useMemo, useRef, useState } from "react";
import { Icon, MessageStrip } from "@ui5/webcomponents-react";
import { Navigate, useNavigate, useParams } from "react-router-dom";
import type { Analysis, AnalysisFile, AuditEvent, DataIssue, Recommendation, RecommendationDetail, ReferenceRow, ReportSnapshot, Role } from "./domain";
import { euro, statusLabel } from "./domain";
import { referenceRows } from "./mockData";
import { analysisTotals, useAnalysisStore } from "./store";
import { costOptApi, type BackendDocumentKind } from "./api";
import { Accordion, Breadcrumbs, Button, Card, DataTable, EmptyState, FormField, MetricCard, Modal, PageHeader, SearchField, StatusBadge, StepNavigation, Tabs, type Column } from "./components/ui";

const pathForStep = (analysis: Analysis) => `/analyses/${analysis.id}/${analysis.currentStep}`;
const workspaceCrumbs = (analysis?: Analysis, current?: string) => [{ label: "Analyses", to: "/analyses" }, ...(analysis ? [{ label: analysis.name, to: pathForStep(analysis) }] : []), ...(current ? [{ label: current }] : [])];
const previewColumnsForDisplay = (columns: string[]) => columns.filter((column) => !/^unnamed(?:\s+column|:)?\s*\d+/i.test(column.trim()));
type UploadKind = "proposal_workbook" | BackendDocumentKind;
const inferUploadKind = (file: Pick<File, "name">, fallback: UploadKind): UploadKind => {
  const name = file.name.toLowerCase().replace(/[_-]+/g, " ");
  if (/rate\s*card|rates?\b/.test(name)) return "rate_card";
  if (/delivery.*constraint|constraint|restriction|permission|permit/.test(name)) return "delivery_constraints";
  if (/contract|clause|evidence/.test(name)) return "contractual_evidence";
  if (/proposal|\bsow\b|workforce/.test(name)) return "proposal_workbook";
  return fallback;
};
const fileSizeLabel = (bytes?: number) => bytes === undefined ? "—" : bytes < 1024 ? `${(bytes / 1024).toFixed(1)} KB` : `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
type ValidationRuleDefinition = { id: number; title: string; description: string };
type ValidationCheck = { field: string; message: string; count: number };
type ValidationGroup = ValidationRuleDefinition & { severity: DataIssue["severity"]; resolutionStatus: DataIssue["resolutionStatus"]; members: DataIssue[]; records: string[]; backend: boolean; checks: ValidationCheck[] };

const VALIDATION_RULES: ValidationRuleDefinition[] = [
  { id: 1, title: "Rule 1 - SOW references", description: "SOW references are required, must use the supported format, and cannot be duplicated." },
  { id: 2, title: "Rule 2 - E-levels and worker totals", description: "E1-E5 values must be valid whole-number headcounts and must reconcile with the worker total." },
  { id: 3, title: "Rule 3 - Delivery countries", description: "A delivery-country value is required; multiple countries are allowed for one SOW." },
  { id: 4, title: "Rule 4 - Rate Card", description: "Each rate row must have a valid grade, role, delivery country, currency and daily rate. Discounts must reconcile standard and net rates, effective dates must be valid, and expired rates are blocked. A SOW reference is optional for a generic rate card." },
  { id: 5, title: "Rule 5 - Contract evidence", description: "Contract evidence must reference the SOW and identify relevant clauses, approval requirements, status, and missing evidence." },
  { id: 6, title: "Rule 6 - Delivery constraints", description: "Delivery evidence must reference the SOW and identify applicable country restrictions, permissions, approvals, and evidence gaps." },
];

const validationRuleFor = (field: string, message: string): ValidationRuleDefinition | undefined => {
  const value = `${field} ${message}`.toLowerCase();
  const normalizedField = field.toLowerCase();
  if (/required documents|sow consistency|document validation|workbook structure|workbook review/.test(normalizedField)) return undefined;
  if (/sow reference|sow scope/.test(normalizedField)) return VALIDATION_RULES[0];
  if (/^(e[1-5]|worker total)$|workforce levels/.test(normalizedField)) return VALIDATION_RULES[1];
  if (/delivery countr|source location/.test(field.toLowerCase())) return VALIDATION_RULES[2];
  if (/contract|clause|customer approval/.test(value)) return VALIDATION_RULES[4];
  if (/delivery constraint|delivery restriction|country restriction|country scope|permission|permit/.test(value)) return VALIDATION_RULES[5];
  if (/rate|annual value|currency|billing unit|e-level/.test(value)) return VALIDATION_RULES[3];
  return undefined;
};

const aggregateValidationIssues = (issues: DataIssue[]): ValidationGroup[] => {
  const groups = new Map<number, DataIssue[]>();
  issues.forEach((issue) => {
    const field = issue.record.replace(/^Row\s+\d+\s*(?:[-·])\s*/i, "");
    const rule = validationRuleFor(field, issue.message);
    if (!rule) return;
    groups.set(rule.id, [...(groups.get(rule.id) || []), issue]);
  });
  return VALIDATION_RULES.filter((rule) => groups.has(rule.id)).map((rule) => {
    const members = groups.get(rule.id) || [];
    const open = members.some((item) => item.resolutionStatus === "open");
    const excluded = members.every((item) => item.resolutionStatus === "excluded");
    const openMembers = members.filter((item) => item.resolutionStatus === "open");
    const severitySource = openMembers.length ? openMembers : members;
    const severity: DataIssue["severity"] = severitySource.some((item) => item.severity === "error") ? "error" : severitySource.some((item) => item.severity === "warning") ? "warning" : "success";
    const checkMap = new Map<string, ValidationCheck>();
    members.forEach((item) => {
      const field = item.record.replace(/^Row\s+\d+\s*(?:[-·])\s*/i, "");
      const key = `${field}-${item.message}`;
      const current = checkMap.get(key);
      checkMap.set(key, { field, message: item.message, count: (current?.count || 0) + 1 });
    });
    return { ...rule, severity,
      resolutionStatus: open ? "open" : excluded ? "excluded" : "resolved", members,
      records: [...new Set(members.map((item) => item.record.match(/^Row\s+\d+/i)?.[0] || item.record))],
      backend: members.some((item) => item.id.startsWith("BE-")), checks: [...checkMap.values()] };
  });
};

function useCurrentAnalysis() {
  const { analysisId = "" } = useParams();
  const analysis = useAnalysisStore((state) => state.analyses.find((item) => item.id === analysisId));
  return { analysisId, analysis };
}

export function AnalysesPage() {
  const navigate = useNavigate();
  const { analyses, createAnalysis } = useAnalysisStore();
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("all");
  const rows = analyses.filter((item) => `${item.name} ${item.id}`.toLowerCase().includes(search.toLowerCase()) && (status === "all" || item.status === status));
  const count = (value: Analysis["status"]) => analyses.filter((item) => item.status === value).length;
  const columns: Column<Analysis>[] = [
    { key: "name", label: "Analysis", value: (row) => <span className="primary-cell"><b>{row.name}</b><small>{row.id} · Created by {row.createdBy}</small></span>, sortValue: (row) => row.name },
    { key: "status", label: "Status", value: (row) => <StatusBadge status={row.status} />, sortValue: (row) => row.status },
    { key: "step", label: "Current Step", value: (row) => statusLabel(row.currentStep), sortValue: (row) => row.currentStep },
    { key: "updated", label: "Updated", value: (row) => row.updatedDate, sortValue: (row) => row.updatedDate },
    { key: "savings", label: "Estimated Savings", value: (row) => euro(row.estimatedSavings), sortValue: (row) => row.estimatedSavings, className: "numeric" },
    { key: "open", label: "", value: () => <Icon name="navigation-right-arrow" /> },
  ];
  const newAnalysis = () => { const id = createAnalysis(); navigate(`/analyses/${id}/add-data`); };
  return <div className="page"><Breadcrumbs items={[{ label: "Analyses" }]} /><PageHeader eyebrow="DECISION WORKSPACE" title="Cost Optimization Analyses" description="Create, review and approve evidence-backed workforce cost scenarios." actions={<Button variant="primary" icon="add" onClick={newAnalysis}>New Analysis</Button>} />
    <div className="metric-grid"><MetricCard label="Active" value={analyses.filter((item) => ["draft", "in_progress"].includes(item.status)).length} tone="info" /><MetricCard label="Needs Attention" value={count("needs_attention")} tone="negative" /><MetricCard label="Awaiting Approval" value={count("awaiting_approval")} tone="warning" /><MetricCard label="Approved" value={count("approved")} tone="positive" /><MetricCard label="Estimated Savings" value={euro(analyses.reduce((sum, item) => sum + item.estimatedSavings, 0))} detail="Across all analyses" tone="positive" /></div>
    <div className="filter-bar"><SearchField value={search} onChange={setSearch} placeholder="Search analyses" /><select aria-label="Filter by status" value={status} onChange={(event) => setStatus(event.target.value)}><option value="all">All statuses</option><option value="draft">Draft</option><option value="needs_attention">Needs attention</option><option value="in_progress">In progress</option><option value="awaiting_approval">Awaiting approval</option><option value="approved">Approved</option></select></div>
    <Card className="table-card" title="Analysis worklist" subtitle={`${rows.length} analys${rows.length === 1 ? "is" : "es"}`}><DataTable rows={rows} columns={columns} pageSize={6} ariaLabel="Cost optimization analyses" onRowClick={(row) => navigate(pathForStep(row))} /></Card>
  </div>;
}

export function AddDataPage() {
  const { analysisId, analysis } = useCurrentAnalysis();
  const navigate = useNavigate();
  const { files, issues, backendOnline, backendLoading, addMockFile, loadBackendSample, uploadBackendFile, confirmFile, validateBackendFile } = useAnalysisStore();
  const [dragging, setDragging] = useState(false);
  const [reviewFile, setReviewFile] = useState<AnalysisFile | null>(null);
  const picker = useRef<HTMLInputElement>(null);
  if (!analysis) return <NotFoundPage />;
  const rows = files.filter((item) => item.analysisId === analysisId);
  const columns: Column<AnalysisFile>[] = [
    { key: "file", label: "File", value: (row) => <span className="primary-cell"><b>{row.name}</b><small>{row.id}</small></span>, sortValue: (row) => row.name },
    { key: "size", label: "Size", value: (row) => fileSizeLabel(row.fileSize), sortValue: (row) => row.fileSize || 0 },
    { key: "type", label: "Type", value: (row) => row.type, sortValue: (row) => row.type },
    { key: "uploaded", label: "Uploaded", value: (row) => row.uploadedAt ? new Date(row.uploadedAt).toLocaleString() : "—", sortValue: (row) => row.uploadedAt || "" },
    { key: "status", label: "Status", value: (row) => <StatusBadge status={row.status === "ready" ? "ready" : row.status === "error" ? "error" : "warning"} label={statusLabel(row.status)} /> },
    { key: "issue", label: "Issues", value: (row) => row.validationStatus === "pending" ? "—" : row.issues },
    { key: "action", label: "Action", value: (row) => <Button variant="text" onClick={() => setReviewFile(row)}>Review</Button> },
  ];
  const handleFiles = async (selected?: FileList | File[]) => {
    const batch = Array.from(selected || []);
    for (const file of batch) {
      const kind = inferUploadKind(file, "proposal_workbook");
      if (backendOnline) await uploadBackendFile(analysisId, file, kind);
      else addMockFile(analysisId, file, kind);
    }
    if (picker.current) picker.current.value = "";
  };
  const loadSample = () => { if (backendOnline) void loadBackendSample(analysisId).catch(() => undefined); else addMockFile(analysisId); };
  const activeReviewFile = reviewFile ? files.find((item) => item.id === reviewFile.id) || reviewFile : null;
  const reviewKind = activeReviewFile && ["proposal_workbook", "rate_card", "contractual_evidence", "delivery_constraints"].includes(activeReviewFile.type)
    ? activeReviewFile.type as UploadKind
    : activeReviewFile ? inferUploadKind(activeReviewFile, "proposal_workbook") : "proposal_workbook";
  const supportingReview = reviewKind !== "proposal_workbook";
  const proposalIssues = activeReviewFile?.validationStatus === "blocked"
    ? issues.filter((item) => item.analysisId === analysisId && item.resolutionStatus === "open") : [];
  const proposalCheck = (label: string, pattern: RegExp) => {
    const affected = proposalIssues.some((item) => pattern.test(item.record));
    return { label, status: affected ? "warning" as const : "ready" as const, badge: affected ? "Review Needed" : "Confirmed" };
  };
  const reviewChecks: { label: string; status: "ready" | "warning"; badge: string }[] = reviewKind === "contractual_evidence" ? [
    { label: "Document", status: "ready", badge: "Parsed" },
    { label: "SOW / Project Reference", status: "warning", badge: "Validation Required" },
    { label: "Contract Clauses", status: "warning", badge: "Validation Required" },
    { label: "Restrictions and Approvals", status: "warning", badge: "Validation Required" },
  ] : reviewKind === "rate_card" ? [
    { label: "Document", status: "ready", badge: "Parsed" },
    { label: "Grade, Role and Delivery Country", status: "warning", badge: "Validation Required" },
    { label: "Currency, Unit and Standard Rate", status: "warning", badge: "Validation Required" },
    { label: "Discount and Net Rate", status: "warning", badge: "Validation Required" },
    { label: "Rate Effective Dates and Expiry", status: "warning", badge: "Validation Required" },
  ] : reviewKind === "delivery_constraints" ? [
    { label: "Document", status: "ready", badge: "Parsed" },
    { label: "SOW / Project Reference", status: "warning", badge: "Validation Required" },
    { label: "Country Scope", status: "warning", badge: "Validation Required" },
    { label: "Delivery Restrictions and Approvals", status: "warning", badge: "Validation Required" },
  ] : [
    proposalCheck("Project", /sow reference|headers|workbook|rows/i),
    proposalCheck("Team and Roles", /(?:^|·\s*)(?:e[1-5]|worker total)$/i),
    proposalCheck("Locations", /delivery countries/i),
  ];
  const confirmReview = async () => {
    if (!activeReviewFile) return;
    confirmFile(analysisId, activeReviewFile.id);
    setReviewFile(null);
  };
  const proposalFile = rows.find((file) => file.type === "proposal_workbook");
  const canContinue = proposalFile?.status === "ready";
  const continueToCheckData = async () => {
    if (!proposalFile) return;
    try {
      await validateBackendFile(analysisId, proposalFile.id, proposalFile.selectedSow);
    } catch {
      return;
    }
    navigate(`/analyses/${analysisId}/check-data`);
  };
  return <div className="page add-data-page"><Breadcrumbs items={workspaceCrumbs(analysis, "Add Data")} /><StepNavigation current="add-data" /><PageHeader eyebrow="STEP 1 OF 6" title="Add data" description="Upload workforce evidence or start with deterministic sample Fieldglass data." actions={<StatusBadge status={analysis.status} />} />
    <div className="content-grid"><Card className="analysis-upload-card" title="Upload analysis files" subtitle="Accepted formats: XLSB, XLSX, CSV, DOCX, TXT"><div className={`upload-zone ${dragging ? "dragging" : ""}`} onDragOver={(event) => { event.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={(event) => { event.preventDefault(); setDragging(false); void handleFiles(event.dataTransfer.files).catch(() => undefined); }}>
      <Icon name="upload" /><h3>Drag and drop your files here</h3><p>Proposal SOW and supporting documents</p>
      <input ref={picker} className="file-input" type="file" multiple accept=".xlsb,.xlsx,.csv,.docx,.txt" onChange={(event) => { void handleFiles(event.target.files || undefined).catch(() => undefined); }} />
      <Button variant="primary" disabled={backendLoading} onClick={() => picker.current?.click()}>{backendLoading ? "Uploading…" : "Browse Files"}</Button>
      <small>Upload up to four files. Maximum 2 MB per file.</small>
    </div><Button className="upload-template-action" variant="text" icon="download">Download template</Button></Card>
    <Card className="analysis-upload-card" title="Sample Fieldglass data" subtitle="Pre-loaded: Synthetic SAP Fieldglass workforce extract">
      <div className="upload-zone sample-data-zone">
        <Icon name="database" /><h3>Load sample workforce extract</h3><p>Deterministic roles, rates, and locations</p>
        <Button variant="primary" icon="database" disabled={backendLoading} onClick={loadSample}>{backendLoading ? "Loading…" : "Load Sample Fieldglass Data"}</Button>
        <small>15 benchmark workforce roles with complete rate structures</small>
      </div>
      <div className="sample-info-action"><Icon name="information" /><span>{backendOnline ? "Loaded through FastAPI from local synthetic table (not live SAP)" : "Backend offline: deterministic browser demo data"}</span></div>
    </Card></div>
    <div className="section-stack"><Card className="table-card" title="Files" subtitle="Review extracted rows before validation"><DataTable rows={rows} columns={columns} empty="No files added yet." ariaLabel="Analysis files" /></Card></div>
    <div className="sticky-actions"><span>{canContinue ? "The extracted data is confirmed. Continue to run validation and review the results." : "Upload the required documents, then review and confirm the data package."}</span><div><Button onClick={() => navigate("/analyses")}>Back</Button><Button variant="primary" disabled={!canContinue || backendLoading} onClick={() => void continueToCheckData()}>{backendLoading ? "Validating…" : "Continue to Check Data"}</Button></div></div>
    <Modal open={Boolean(reviewFile)} title={`Review ${statusLabel(reviewKind)}`} size="large" className="extracted-data-modal" onClose={() => setReviewFile(null)} footer={<div className="dialog-actions"><Button onClick={() => setReviewFile(null)}>Cancel</Button><Button variant="primary" disabled={backendLoading} onClick={() => void confirmReview()}>{backendLoading ? "Processing…" : "Confirm Extracted Data"}</Button></div>}>
      <div className="extraction-review-list">{reviewChecks.map((check) => <div className="extraction-review-row" key={check.label}><strong>{check.label}</strong><StatusBadge status={check.status} label={check.badge} /></div>)}</div>
      {supportingReview
        ? <MessageStrip design="Information" hideCloseButton>Confirm this file's extracted contents here. Full package validation runs separately against the Proposal SOW and all reviewed supporting documents.</MessageStrip>
        : <MessageStrip design="Information" hideCloseButton>The Proposal review covers SOW and workforce fields only. Contract clauses and delivery restrictions are validated from their separate supporting documents.</MessageStrip>}
    </Modal>
  </div>;
}

export function CheckDataPage() {
  const { analysisId, analysis } = useCurrentAnalysis();
  const navigate = useNavigate();
  const { issues, files, backendOnline, backendLoading, resolveIssue, acknowledgeWarnings, setStep, selectSowForAnalysis } = useAnalysisStore();
  const rows = issues.filter((item) => item.analysisId === analysisId);
  const reportedValidationGroups = useMemo(() => aggregateValidationIssues(rows), [rows]);
  const [selectedId, setSelectedId] = useState<number | "">(reportedValidationGroups[0]?.id || "");
  const [previewRows, setPreviewRows] = useState<Record<string, unknown>[]>([]);
  const [previewColumns, setPreviewColumns] = useState<string[]>([]);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState("");
  const [previewSearch, setPreviewSearch] = useState("");
  const [sowFilter, setSowFilter] = useState("all");
  const sourceFiles = files.filter((item) => item.analysisId === analysisId);
  const previewFile = sourceFiles.find((item) => item.type === "proposal_workbook");
  const validationHasRun = previewFile?.validationStatus === "ready" || previewFile?.validationStatus === "blocked";
  const validationGroups: ValidationGroup[] = validationHasRun ? VALIDATION_RULES.map((rule) => reportedValidationGroups.find((group) => group.id === rule.id) || ({
    ...rule, severity: "info", resolutionStatus: "open", members: [], records: [], backend: true, checks: [],
  })) : reportedValidationGroups;
  const supportingUploadIds = sourceFiles.filter((item) => ["rate_card", "contractual_evidence", "delivery_constraints"].includes(item.type) && item.backendUploadId).map((item) => item.backendUploadId!);
  const documentCoverage = [
    { kind: "proposal_workbook", label: "Proposal SOW" },
    { kind: "rate_card", label: "Rate Card" },
    { kind: "contractual_evidence", label: "Contract Evidence" },
    { kind: "delivery_constraints", label: "Delivery Constraints" },
  ].map((definition) => ({ ...definition, file: sourceFiles.find((item) => item.type === definition.kind) }));
  const uploadedDocumentCount = documentCoverage.filter((item) => item.file).length;
  useEffect(() => { if (validationGroups.length && !validationGroups.some((item) => item.id === selectedId)) setSelectedId(validationGroups[0].id); }, [validationGroups, selectedId]);
  useEffect(() => { if (previewFile?.selectedSow) setSowFilter(previewFile.selectedSow); }, [previewFile?.selectedSow]);
  useEffect(() => {
    let active = true;
    const loadPreview = async () => {
      setPreviewRows([]); setPreviewColumns([]); setPreviewError("");
      if (!analysis || !backendOnline || !previewFile?.backendUploadId || previewFile.validationStatus !== "ready") return;
      setPreviewLoading(true); setPreviewError("");
      try {
        const destinationCountryIds = analysis.selectedCountries.map((country) => useAnalysisStore.getState().backendLocations.find((location) => location.country === country)?.location_id).filter((value): value is string => Boolean(value));
        const result = await costOptApi.consolidatedPreview(analysis.scenarioId || "scn-001", previewFile.backendUploadId, supportingUploadIds, destinationCountryIds);
        if (!active) return;
        setPreviewRows(result.rows);
        setPreviewColumns(previewColumnsForDisplay(result.columns));
      } catch (error) {
        if (active) setPreviewError(error instanceof Error ? error.message : "The uploaded data preview could not be loaded.");
      } finally { if (active) setPreviewLoading(false); }
    };
    void loadPreview();
    return () => { active = false; };
  }, [analysis, backendOnline, previewFile, supportingUploadIds.join("|")]);
  if (!analysis) return <NotFoundPage />;
  const selected = validationGroups.find((item) => item.id === selectedId);
  const openErrors = rows.filter((item) => item.severity === "error" && item.resolutionStatus === "open");
  const openWarnings = rows.filter((item) => item.severity === "warning" && item.resolutionStatus === "open");
  const openErrorGroups = validationGroups.filter((item) => item.severity === "error" && item.resolutionStatus === "open");
  const openWarningGroups = validationGroups.filter((item) => item.severity === "warning" && item.resolutionStatus === "open");
  const readyGroups = validationGroups.filter((item) => item.resolutionStatus === "resolved");
  const excludedGroups = validationGroups.filter((item) => item.resolutionStatus === "excluded");
  const hasReadySource = sourceFiles.some((item) => item.status === "ready" && (!item.validationStatus || item.validationStatus === "ready"));
  const canContinue = hasReadySource && !openErrors.length && (!openWarnings.length || analysis.warningsAcknowledged);
  const normalizedColumn = (value: string) => value.toLowerCase().replace(/[^a-z0-9]/g, "");
  const sowColumn = previewColumns.find((column) => normalizedColumn(column) === "sowreference");
  const sowOptions = sowColumn ? [...new Set(previewRows.map((row) => String(row[sowColumn] || "").trim()).filter(Boolean))].sort() : [];
  const visiblePreviewRows = previewRows.filter((row) => (sowFilter === "all" || !sowColumn || String(row[sowColumn]) === sowFilter) && Object.values(row).some((value) => String(value ?? "").toLowerCase().includes(previewSearch.toLowerCase())));
  const previewTableRows = visiblePreviewRows.map((values, index) => ({ id: `preview-${index}`, values }));
  const previewTableColumns: Column<{ id: string; values: Record<string, unknown> }>[] = previewColumns.map((column) => ({ key: column, label: column.replaceAll("_", " "), value: (row) => String(row.values[column] ?? "-"), sortValue: (row) => String(row.values[column] ?? "") }));
  const consolidationEmptyMessage = !backendOnline
    ? "The backend is offline, so the selected files have not been parsed or joined. Reconnect the backend and upload the package again."
    : !previewFile
      ? "Upload a Proposal SOW workbook to create consolidated rows."
      : !previewFile.backendUploadId
        ? "The Proposal SOW was added while the backend was unavailable. Return to Add Data and upload it again for parsing."
        : previewFile.validationStatus === "pending"
          ? "Validation has not completed. Return to Add Data and select Continue to Check Data to run it automatically."
        : previewFile.validationStatus === "blocked" || previewFile.cleaningReady === false
          ? "Resolve the Proposal SOW validation findings before its rows can be consolidated."
          : "No workforce rows were produced from the uploaded Proposal SOW. Review its extracted data and validation findings.";
  const applySowFilter = () => { if (!previewFile || sowFilter === "all") return; selectSowForAnalysis(analysisId, sowFilter); };
  const goNext = () => { setStep(analysisId, "setup"); navigate(`/analyses/${analysisId}/setup`); };
  return <div className="page"><Breadcrumbs items={workspaceCrumbs(analysis, "Check Data")} /><PageHeader eyebrow="STEP 2 OF 6" title="Check data" description="Review quality findings before setting the analysis scope." /><StepNavigation current="check-data" />
    <Card className="table-card data-preview-card" title="Consolidated recommendation inputs" subtitle={`${visiblePreviewRows.length} of ${previewRows.length} agent-input rows · ${uploadedDocumentCount} of 4 documents uploaded`} action={previewRows.length ? <StatusBadge status="ready" label={`${supportingUploadIds.length + 1} documents joined`} /> : undefined}>
      <div className="document-coverage" aria-label="Document coverage">{documentCoverage.map((item) => <div key={item.kind}><span><b>{item.label}</b><small>{item.file?.name || "Required document not uploaded"}</small></span><StatusBadge status={item.file ? item.file.status === "ready" ? "ready" : "warning" : "error"} label={item.file ? item.file.status === "ready" ? "Reviewed" : "Uploaded" : "Missing"} /></div>)}</div>
      <div className="data-preview-controls"><SearchField value={previewSearch} onChange={setPreviewSearch} placeholder="Search consolidated data" /><label className="preview-filter"><span>SOW</span><select aria-label="Filter consolidated data by SOW" value={sowFilter} onChange={(event) => setSowFilter(event.target.value)}><option value="all">All SOWs</option>{sowOptions.map((sow) => <option key={sow} value={sow}>{sow}</option>)}</select></label>{sowOptions.length > 0 && <Button variant="primary" disabled={sowFilter === "all" || sowFilter === previewFile?.selectedSow} onClick={applySowFilter}>{sowFilter === previewFile?.selectedSow ? "SOW selected" : "Use SOW for analysis"}</Button>}</div>
      {previewLoading ? <div className="preview-state" role="status">Consolidating validated documents...</div> : previewError ? <MessageStrip design="Negative" hideCloseButton>{previewError}</MessageStrip> : <DataTable rows={previewTableRows} columns={previewTableColumns} pageSize={8} empty={consolidationEmptyMessage} ariaLabel="Consolidated analysis data" />}
    </Card>
    <div className="metric-grid"><MetricCard label="Ready" value={validationHasRun ? readyGroups.length : "—"} detail={validationHasRun ? `${readyGroups.reduce((sum, item) => sum + item.members.length, 0)} passed checks` : "Validation not run"} tone="positive" /><MetricCard label="Needs Fixing" value={validationHasRun ? openErrorGroups.length : "—"} detail={validationHasRun ? `${openErrors.length} affected findings` : "Validation not run"} tone="negative" /><MetricCard label="Warnings" value={validationHasRun ? openWarningGroups.length : "—"} detail={validationHasRun ? `${openWarnings.length} affected findings` : "Validation not run"} tone="warning" /><MetricCard label="Excluded" value={validationHasRun ? excludedGroups.length : "—"} detail={validationHasRun ? `${excludedGroups.reduce((sum, item) => sum + item.members.length, 0)} findings` : "Validation not run"} tone="neutral" /></div>
    {!validationHasRun ? <Card><EmptyState title={backendLoading ? "Validation in progress" : "Validation not completed"} description={backendLoading ? "The backend is checking the Proposal SOW and supporting documents." : previewFile ? "Return to Add Data and select Continue to Check Data. Validation will run automatically before this page opens." : "Add and confirm a Proposal SOW before continuing."} action={!backendLoading ? <Button onClick={() => navigate(`/analyses/${analysisId}/add-data`)}>Return to Add Data</Button> : undefined} /></Card> : !validationGroups.length ? <Card><EmptyState title="Validation passed" description="The backend validation completed without warnings or blocking findings." /></Card> : <div className="validation-layout">
      <Card title="Validation rules and status" subtitle={`${validationGroups.length} rules · ${readyGroups.length} passed · ${openErrorGroups.length} failed · ${openWarningGroups.length} warning · ${validationGroups.filter((group) => !group.members.length).length} not checked`}><div className="issue-list">{validationGroups.map((group) => <button key={group.id} className={`issue-row ${selectedId === group.id ? "selected" : ""}`} onClick={() => setSelectedId(group.id)}><StatusBadge status={group.members.length ? group.resolutionStatus !== "open" ? group.resolutionStatus : group.severity : "info"} label={group.members.length ? undefined : "Not checked"} /><span><b>{group.title}</b><small>{group.members.length ? `${group.checks.length} check${group.checks.length === 1 ? "" : "s"} · ${group.members.length} issue${group.members.length === 1 ? "" : "s"}` : "Not checked because an earlier blocking rule stopped package validation"} · {group.description}</small></span><Icon name="navigation-right-arrow" /></button>)}</div></Card>
      <Card className="detail-panel" title="Rule details">{selected ? <><StatusBadge status={selected.members.length ? selected.resolutionStatus !== "open" ? selected.resolutionStatus : selected.severity : "info"} label={selected.members.length ? undefined : "Not checked"} /><h3>{selected.title}</h3><p>{selected.description}</p><div className="rule-check-list"><strong>Checks in this rule</strong>{selected.checks.length ? selected.checks.map((check) => <div key={`${check.field}-${check.message}`}><b>{check.field}</b><span>{check.message}</span><small>{check.count} result{check.count === 1 ? "" : "s"}</small></div>) : <div><b>Not checked</b><span>Correct the earlier blocking workbook rules, then run validation again.</span></div>}</div>{selected.records.length > 0 && <div className="affected-records"><strong>Affected rows ({selected.records.length})</strong><div>{selected.records.slice(0, 12).map((record) => <span key={record}>{record}</span>)}</div>{selected.records.length > 12 && <small>+{selected.records.length - 12} additional rows</small>}</div>}<div className={`message-box ${selected.members.length ? selected.severity : "info"}`}>{!selected.members.length ? "This rule was not checked because an earlier blocking rule stopped package validation. Run validation again after correcting the source workbook." : selected.severity === "success" ? "This rule passed backend validation. No correction is required." : selected.backend ? "These checks were returned by the backend. Correct the listed source records and validate the document package again." : "Review and correct the affected source rows before continuing."}</div>{selected.resolutionStatus === "open" && selected.members.length > 0 && <div className="toolbar section-stack">{selected.backend ? <Button variant="primary" onClick={() => navigate(`/analyses/${analysisId}/add-data`)}>Return to Add Data</Button> : <><Button variant="primary" onClick={() => selected.members.forEach((item) => resolveIssue(item.id, "resolved"))}>Mark Rule Resolved</Button><Button onClick={() => selected.members.forEach((item) => resolveIssue(item.id, "excluded"))}>Exclude Rule</Button></>}</div>}</> : <EmptyState compact title="Select a validation rule" />}</Card>
    </div>}
    {openWarnings.length > 0 && !openErrors.length && <label className="check-tile section-stack"><input type="checkbox" checked={analysis.warningsAcknowledged} onChange={(event) => acknowledgeWarnings(analysisId, event.target.checked)} />I reviewed the remaining warnings and want to continue.</label>}
    <div className="sticky-actions"><span>{openErrors.length ? "Resolve the backend blocking errors before continuing." : canContinue ? "Data is ready for setup." : !hasReadySource ? "Complete backend validation before continuing." : "Acknowledge the remaining warnings."}</span><div><Button onClick={() => navigate(`/analyses/${analysisId}/add-data`)}>Back</Button><Button variant="primary" disabled={!canContinue} onClick={goNext}>Continue to Setup</Button></div></div>
  </div>;
}

function AssumptionSlider({ label, hint, value, min, max, unit, onChange }: {
  label: string; hint: string; value: number; min: number; max: number; unit: string; onChange: (value: number) => void;
}) {
  const setValue = (next: number) => onChange(Math.min(max, Math.max(min, Number.isFinite(next) ? next : min)));
  const progress = ((value - min) / (max - min)) * 100;
  return <div className="assumption-slider form-field">
    <div className="assumption-slider-heading"><span>{label}</span><div className="assumption-value"><input aria-label={`${label} value`} type="number" min={min} max={max} value={value} onChange={(event) => setValue(Number(event.target.value))} /><span>{unit}</span></div></div>
    <input aria-label={`${label} slider`} className="range-control" type="range" min={min} max={max} step="1" value={value} onChange={(event) => setValue(Number(event.target.value))} style={{ background: `linear-gradient(to right, var(--sapSelectedColor) 0%, var(--sapSelectedColor) ${progress}%, var(--sapField_BorderColor) ${progress}%, var(--sapField_BorderColor) 100%)` }} />
    <div className="range-scale"><span>{min}{unit === "%" ? "%" : " year"}</span><span>{max}{unit === "%" ? "%" : " years"}</span></div>
    <small>{hint}</small>
  </div>;
}

export function SetupPage() {
  const { analysisId, analysis } = useCurrentAnalysis();
  const navigate = useNavigate();
  const { roles, files, backendOnline, backendLocations, setRoleMoveCount, updateSetup, runAnalysis, runBackendAnalysis } = useAnalysisStore();
  const proposalFile = files.find((item) => item.analysisId === analysisId && item.type === "proposal_workbook");
  const selectedSow = proposalFile?.selectedSow;
  const roleRows = roles.filter((item) => item.analysisId === analysisId
    && (!selectedSow || item.title.toLowerCase().startsWith(`${selectedSow.toLowerCase()}-`)));
  const [countries, setCountries] = useState(analysis?.selectedCountries || []);
  const [assumptions, setAssumptions] = useState(analysis?.assumptions || { horizon: 3, transitionCost: 0, contingency: 10, notes: "" });
  const [running, setRunning] = useState(false);
  const [consolidatedRows, setConsolidatedRows] = useState<Record<string, unknown>[]>([]);
  const supportingUploadIds = files.filter((item) => item.analysisId === analysisId && ["rate_card", "contractual_evidence", "delivery_constraints"].includes(item.type) && item.backendUploadId).map((item) => item.backendUploadId!);
  useEffect(() => {
    let active = true;
    if (!analysis || !backendOnline || !proposalFile?.backendUploadId || proposalFile.validationStatus !== "ready") return;
    void costOptApi.consolidatedPreview(analysis.scenarioId || "scn-001", proposalFile.backendUploadId, supportingUploadIds).then((result) => {
      if (active) setConsolidatedRows(result.rows);
    }).catch(() => { if (active) setConsolidatedRows([]); });
    return () => { active = false; };
  }, [analysis, backendOnline, proposalFile, supportingUploadIds.join("|")]);
  if (!analysis) return <NotFoundPage />;
  const countryOptions = backendOnline && backendLocations.length ? backendLocations.filter((item) => item.is_offshore).map((item) => item.country) : ["India", "Portugal", "Poland", "Philippines", "Romania", "Spain"];
  const sourceRateColumn = Object.keys(consolidatedRows[0] || {}).find((column) => column.startsWith("Source Rate"));
  const uniqueScope = new Map<string, Record<string, unknown>>();
  consolidatedRows.filter((row) => !selectedSow || String(row["SOW Reference"]) === selectedSow).forEach((row) => {
    const key = `${row["SOW Reference"] || ""}-${row["E-Level"]}`;
    if (!uniqueScope.has(key)) uniqueScope.set(key, row);
  });
  const scopeValues: Record<string, unknown>[] = uniqueScope.size ? [...uniqueScope.values()] : roleRows.map((role): Record<string, unknown> => {
    const level = role.title.match(/E[1-5]$/i)?.[0]?.toUpperCase() || "";
    return { "SOW Reference": level ? role.title.slice(0, -(level.length + 1)) : role.title, "E-Level": level,
      "Headcount": role.headcount, "Source Country": role.location, "Recommendation Input": "Ready" };
  });
  const scopeRows = scopeValues.map((values, index) => {
    const roleTitle = `${values["SOW Reference"] || ""} ${values["E-Level"] || ""}`;
    return { id: `scope-${index}`, values, role: roleRows.find((role) => role.title.toLowerCase() === roleTitle.toLowerCase()) };
  });
  type ScopeRow = (typeof scopeRows)[number];
  const columns: Column<ScopeRow>[] = [
    { key: "sow", label: "SOW Reference", value: (row) => String(row.values["SOW Reference"] || "—") },
    { key: "level", label: "E-Level", value: (row) => String(row.values["E-Level"] || "—") },
    { key: "available", label: "Available Headcount", value: (row) => Number(row.values["Headcount"] || row.role?.headcount || 0), className: "numeric" },
    { key: "move", label: "Headcount to Move", value: (row) => {
      if (!row.role) return "—";
      const count = row.role.moveCount ?? (row.role.selected ? row.role.headcount : 0);
      return <div className="headcount-stepper"><button type="button" aria-label={`Decrease ${row.role.title} headcount`} disabled={count <= 0} onClick={() => setRoleMoveCount(row.role!.id, count - 1)}>−</button><output aria-label={`${row.role.title} headcount to move`}>{count}</output><button type="button" aria-label={`Increase ${row.role.title} headcount`} disabled={count >= row.role.headcount} onClick={() => setRoleMoveCount(row.role!.id, count + 1)}>+</button></div>;
    } },
    { key: "scope", label: "SOW Delivery Scope", value: (row) => String(row.values["SOW Delivery Scope"] || "—") },
    { key: "source", label: "Source Country", value: (row) => String(row.values["Source Country"] || row.role?.location || "—") },
    ...(sourceRateColumn ? [{ key: "rate", label: sourceRateColumn, value: (row: ScopeRow) => String(row.values[sourceRateColumn] ?? "—"), className: "numeric" } satisfies Column<ScopeRow>] : []),
    { key: "contract", label: "Contract Evidence", value: (row) => String(row.values["Contract Evidence"] || "—") },
    { key: "constraints", label: "Delivery Constraints", value: (row) => String(row.values["Delivery Constraints"] || "—") },
    { key: "ready", label: "Recommendation Input", value: (row) => String(row.values["Recommendation Input"] || "—") },
  ];
  const selectedHeadcount = roleRows.reduce((sum, role) => sum + (role.moveCount ?? (role.selected ? role.headcount : 0)), 0);
  const valid = selectedHeadcount > 0 && countries.length > 0;
  const submit = async () => { if (!valid) return; updateSetup(analysisId, countries, assumptions); setRunning(true); try { if (backendOnline) { const backendId = await runBackendAnalysis(analysisId); navigate(`/analyses/${backendId}/review`); } else { await new Promise((resolve) => setTimeout(resolve, 700)); runAnalysis(analysisId); navigate(`/analyses/${analysisId}/review`); } } catch { /* store surfaces the API error */ } finally { setRunning(false); } };
  return <div className="page"><Breadcrumbs items={workspaceCrumbs(analysis, "Setup")} /><PageHeader eyebrow="STEP 3 OF 6" title="Set up analysis" description="Select the roles, destination countries and financial assumptions to evaluate." /><StepNavigation current="setup" />
    <div className="section-stack"><Card className="table-card" title="1. What to analyze" subtitle={selectedSow ? `Selected in Check Data: ${selectedSow} · Choose how many people to evaluate for a move` : "Choose how many people to evaluate for a move"}><DataTable rows={scopeRows} columns={columns} empty={selectedSow ? `No consolidated recommendation inputs are available for ${selectedSow}. Return to Check Data and select another SOW.` : "No consolidated recommendation inputs are available."} /></Card>
      <Card title="2. Where work may move" subtitle="Select one or more destination countries"><div className="country-grid">{countryOptions.map((country) => <label key={country} className="check-tile"><input type="checkbox" checked={countries.includes(country)} onChange={(event) => setCountries((current) => event.target.checked ? [...current, country] : current.filter((item) => item !== country))} />{country}</label>)}</div></Card>
      <Card title="3. Assumptions (Optional)" subtitle="Set the evaluation period and allowances used to review the recommendation"><div className="form-grid">
        <AssumptionSlider label="Analysis horizon (years)" hint="How many years of recurring costs and savings to consider." value={assumptions.horizon} min={1} max={5} unit="years" onChange={(horizon) => setAssumptions({ ...assumptions, horizon })} />
        <FormField label="Transition cost (EUR)" hint="One-time implementation cost, such as knowledge transfer, onboarding, migration and temporary overlap."><input type="number" min="0" value={assumptions.transitionCost} onChange={(event) => setAssumptions({ ...assumptions, transitionCost: Math.max(0, Number(event.target.value)) })} /></FormField>
        <AssumptionSlider label="Contingency (%)" hint="Additional reserve applied for uncertainty or unexpected transition expenses." value={assumptions.contingency} min={0} max={50} unit="%" onChange={(contingency) => setAssumptions({ ...assumptions, contingency })} />
        <FormField label="Notes" hint="Optional context for reviewers."><textarea value={assumptions.notes} onChange={(event) => setAssumptions({ ...assumptions, notes: event.target.value })} /></FormField>
      </div></Card></div>
    <div className="sticky-actions"><span>{valid ? `${selectedHeadcount} people across ${roleRows.filter((role) => (role.moveCount ?? (role.selected ? role.headcount : 0)) > 0).length} E-levels and ${countries.length} countries selected.` : "Select at least one person and destination country."}</span><div><Button onClick={() => navigate(`/analyses/${analysisId}/check-data`)}>Back</Button><Button variant="primary" disabled={!valid || running} onClick={submit}>{running ? "Running analysis…" : "Run Analysis"}</Button></div></div>
  </div>;
}

function RecommendationDialog({ item, onClose }: { item: Recommendation | null; onClose: () => void }) {
  const update = useAnalysisStore((state) => state.updateRecommendation);
  const [mode, setMode] = useState<Recommendation["status"]>(item?.status || "pending");
  const [target, setTarget] = useState(item?.targetLocation || "India");
  const [savings, setSavings] = useState(item?.savings || 0);
  const [rationale, setRationale] = useState(item?.rationale || "");
  const [comment, setComment] = useState(item?.comment || "");
  const apply = () => { if (!item) return; update(item.id, mode, mode === "modified" ? { targetLocation: target, savings, rationale, comment } : { comment }); onClose(); };
  return <Modal open={Boolean(item)} title="Recommendation Decision" onClose={onClose} footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" onClick={apply}>Save Decision</Button></>}><div className="form-grid"><FormField label="Action"><select value={mode} onChange={(event) => setMode(event.target.value as Recommendation["status"])}><option value="accepted">Accept</option><option value="modified">Modify</option><option value="rejected">Reject</option></select></FormField>{mode === "modified" && <><FormField label="Target location"><select value={target} onChange={(event) => setTarget(event.target.value)}><option>India</option><option>Portugal</option><option>Poland</option><option>Philippines</option></select></FormField><FormField label="Annual savings (EUR)"><input type="number" value={savings} onChange={(event) => setSavings(Number(event.target.value))} /></FormField><FormField label="Rationale"><textarea value={rationale} onChange={(event) => setRationale(event.target.value)} /></FormField></>}<FormField label="Review comment"><textarea value={comment} onChange={(event) => setComment(event.target.value)} /></FormField></div></Modal>;
}

export function ReviewPage() {
  const { analysisId, analysis } = useCurrentAnalysis();
  const navigate = useNavigate();
  const state = useAnalysisStore();
  const [tab, setTab] = useState("overview");
  const [selected, setSelected] = useState<Recommendation | null>(null);
  const [recalculating, setRecalculating] = useState<string | null>(null);
  if (!analysis) return <NotFoundPage />;
  const recommendations = state.recommendations.filter((item) => item.analysisId === analysisId && item.status !== "removed");
  const totals = analysisTotals(analysisId, state);
  const recommended = recommendations.find((item) => item.isRecommended) || recommendations.find((item) => item.status === "pending") || recommendations[0];
  const recommendedHeadcount = recommended?.details?.reduce((sum, detail) => sum + detail.count, 0) || 0;
  const canContinue = recommendations.some((item) => ["accepted", "modified"].includes(item.status)) && !recommendations.some((item) => item.risk === "High" && item.status === "accepted");
  type RecommendationTableRow = RecommendationDetail & { recommendation: Recommendation };
  const recommendationRows: RecommendationTableRow[] = recommendations.flatMap((recommendation) =>
    recommendation.details?.length ? recommendation.details.map((detail) => ({ ...detail, recommendation })) : [{
      id: `${recommendation.id}-summary`, sow: "Not provided", role: recommendation.role, count: 0, availableCount: 0,
      fromRegion: recommendation.sourceLocation, toRegion: recommendation.targetLocation,
      currentCost: recommendation.baselineCost || 0, projectedCost: recommendation.futureCost || 0,
      estimatedSavings: recommendation.savings, recommendation,
    }]);
  const totalRecommendedCount = recommendationRows.reduce((sum, row) => sum + row.count, 0);
  const changeELevelCount = async (row: RecommendationTableRow, nextCount: number) => {
    const maximum = Number.isFinite(row.availableCount) && row.availableCount > 0 ? row.availableCount : row.count;
    const count = Math.max(0, Math.min(maximum, nextCount));
    if (count === row.count || (count === 0 && totalRecommendedCount <= 1)) return;
    setRecalculating(row.id);
    try {
      const nextAnalysisId = await state.runBackendAnalysis(analysisId, { [`${row.role}`]: count });
      navigate(`/analyses/${nextAnalysisId}/review`);
    } catch { /* store surfaces the backend calculation error */ }
    finally { setRecalculating(null); }
  };
  const columns: Column<RecommendationTableRow>[] = [
    { key: "sow", label: "SOW", value: (row) => row.sow, sortValue: (row) => row.sow },
    { key: "role", label: "Role", value: (row) => <b>{row.role}</b>, sortValue: (row) => row.role },
    { key: "count", label: "E-Level Count", value: (row) => {
      if (row.count <= 0) return "—";
      const busy = Boolean(recalculating) || state.backendLoading;
      const maximum = Number.isFinite(row.availableCount) && row.availableCount > 0 ? row.availableCount : row.count;
      return <div className="headcount-stepper"><button type="button" aria-label={`Decrease ${row.sow} ${row.role} count`} disabled={busy || (row.count <= 1 && totalRecommendedCount <= 1)} onClick={() => void changeELevelCount(row, row.count - 1)}>−</button><output aria-label={`${row.sow} ${row.role} selected count`}>{recalculating === row.id ? "…" : row.count}</output><button type="button" aria-label={`Increase ${row.sow} ${row.role} count`} disabled={busy || row.count >= maximum} onClick={() => void changeELevelCount(row, row.count + 1)}>+</button></div>;
    }, sortValue: (row) => row.count },
    { key: "from", label: "From Region", value: (row) => row.fromRegion, sortValue: (row) => row.fromRegion },
    { key: "to", label: "To Region", value: (row) => row.toRegion, sortValue: (row) => row.toRegion },
    { key: "current", label: "Current Costs", value: (row) => euro(row.currentCost), sortValue: (row) => row.currentCost, className: "numeric" },
    { key: "projected", label: "Projected Costs", value: (row) => euro(row.projectedCost), sortValue: (row) => row.projectedCost, className: "numeric" },
    { key: "savings", label: "Estimated Savings", value: (row) => euro(row.estimatedSavings), sortValue: (row) => row.estimatedSavings, className: "numeric" },
    { key: "confidence", label: "Confidence", value: (row) => `${row.recommendation.confidence}%`, sortValue: (row) => row.recommendation.confidence },
    { key: "risk", label: "Risk", value: (row) => <StatusBadge status={row.recommendation.risk === "Low" ? "success" : row.recommendation.risk === "High" ? "error" : "warning"} label={row.recommendation.risk} /> },
    { key: "status", label: "Decision", value: (row) => <StatusBadge status={row.recommendation.status} /> },
    { key: "action", label: "Action", value: (row) => <Button variant="text" onClick={() => setSelected(row.recommendation)}>Review</Button> },
  ];
  const submit = async () => { try { await state.submitForApprovalBackend(analysisId); navigate(`/analyses/${analysisId}/approve`); } catch { /* store surfaces the API error */ } };
  return <div className="page"><Breadcrumbs items={workspaceCrumbs(analysis, "Review")} /><PageHeader eyebrow="STEP 4 OF 6" title="Review recommendations" description="Validate the financial impact, decide each recommendation and inspect supporting risks." /><StepNavigation current="review" /><Tabs active={tab} onChange={setTab} tabs={[{ id: "overview", label: "Overview" }, { id: "recommendations", label: "Recommendations" }, { id: "risks", label: "Risks and Assumptions" }, { id: "operations", label: "Operations" }]} />
    {tab === "overview" && <><div className="metric-grid review-metrics"><MetricCard label="Current Annual Cost" value={euro(totals.current)} /><MetricCard label="Proposed Annual Cost" value={euro(totals.proposed)} tone="info" /><MetricCard label="Annual Savings" value={euro(totals.savings)} tone="positive" /><MetricCard label="First-Year Savings" value={euro(totals.firstYear)} tone="positive" /><MetricCard label="Confidence" value={`${totals.confidence}%`} tone="info" /><MetricCard label="Overall Risk" value="Medium" tone="warning" /></div><Card title="Decision summary">{recommended ? <><p>Review the agent's recommended scenario and decide whether it should proceed:</p><ul><li><b>Proposed change:</b> Evaluate moving {recommended.role.toLowerCase()} to {recommended.targetLocation}.</li><li><b>Expected financial impact:</b> Cost changes from {euro(totals.current)} to {euro(totals.proposed)}, with estimated annual savings of {euro(totals.savings)}.</li><li><b>Assessment:</b> The recommendation has {recommended.confidence}% confidence and {recommended.risk.toLowerCase()} risk.</li><li><b>Your decision:</b> Open the Recommendations tab to accept it, modify the destination or savings, reject it, or request specialist review.</li></ul></> : <p>No recommendation is available. Return to Setup and run the analysis.</p>}<MessageStrip design="Information" hideCloseButton>Nothing is executed automatically. An accepted recommendation still requires approval before any workforce or supplier action.</MessageStrip></Card></>}
    {tab === "recommendations" && <Card className="table-card" title="Recommendations" subtitle="Agent-generated details by SOW and E-level. Use −/+ to change the count and automatically recalculate the recommendation."><DataTable rows={recommendationRows} columns={columns} empty="Run the analysis to generate recommendations." /></Card>}
    {tab === "risks" && <div className="risk-layout"><Accordion title="Risks" open>{recommended ? <ul><li><b>Transition and continuity:</b> Moving {recommendedHeadcount ? `${recommendedHeadcount} people` : recommended.role} to {recommended.targetLocation} is estimated to require approximately {recommended.transitionDurationWeeks ?? "an agreed number of"} transition week(s) and {recommended.estimatedDowntimeHours ?? "a planned"} hour(s) of controlled cutover. Confirm the transition plan before approval.</li><li><b>Knowledge transfer:</b> Plan approximately {recommended.knowledgeTransferHours ?? "sufficient"} knowledge-transfer hours and {recommended.onboardingHours ?? "sufficient"} onboarding hours before cutover so service delivery is not interrupted.</li><li><b>Evidence and approval:</b> Review the contract and delivery checks before accepting the move. {recommended.checks?.[0] || "Human approval is required before any workforce or supplier action."}</li>{recommended.gaps?.slice(0, 3).map((gap) => <li key={gap}><b>Information to confirm:</b> {gap}</li>)}</ul> : <p>No agent recommendation is available. Run the analysis to generate its risks.</p>}</Accordion><Accordion title="Assumptions"><ul><li><b>Analysis horizon — {analysis.assumptions.horizon} years:</b> Recurring source costs, destination costs and savings are evaluated over this period.</li><li><b>Transition cost — {euro(analysis.assumptions.transitionCost)}:</b> This is the one-time allowance for migration, knowledge transfer, onboarding and temporary overlap. A zero value means no separate transition cost was provided.</li><li><b>Contingency — {analysis.assumptions.contingency}%:</b> This reserve covers uncertainty in the estimated transition cost and should be considered when reviewing first-year savings.</li>{analysis.assumptions.notes && <li><b>Reviewer context:</b> {analysis.assumptions.notes}</li>}</ul></Accordion></div>}
    {tab === "operations" && <div className="risk-layout">
      <Accordion title="Transition plan" open>{recommended ? <ul><li><b>Planned movement:</b> Transition {recommendedHeadcount || recommended.role} {recommendedHeadcount ? "people" : ""} to {recommended.targetLocation}.</li><li><b>Transition duration:</b> Approximately {recommended.transitionDurationWeeks ?? "not yet estimated"} week(s).</li><li><b>Controlled downtime:</b> Approximately {recommended.estimatedDowntimeHours ?? "not yet estimated"} hour(s) for cutover and service validation.</li><li><b>Preparation effort:</b> {recommended.knowledgeTransferHours ?? "Unestimated"} knowledge-transfer hours and {recommended.onboardingHours ?? "unestimated"} onboarding hours.</li></ul> : <p>Run the analysis to generate an operational transition plan.</p>}</Accordion>
      <Accordion title="Transition cost"><ul><li><b>Entered one-time cost:</b> {euro(analysis.assumptions.transitionCost)} for migration, onboarding, knowledge transfer and temporary overlap.</li><li><b>Contingency reserve:</b> {analysis.assumptions.contingency}% ({euro(analysis.assumptions.transitionCost * analysis.assumptions.contingency / 100)}).</li><li><b>Total transition allowance:</b> {euro(analysis.assumptions.transitionCost * (1 + analysis.assumptions.contingency / 100))}. Confirm this amount before approving the business case.</li></ul></Accordion>
      <Accordion title="Time-zone coverage"><ul><li><b>Time-zone difference:</b> {recommended?.timezoneDifferenceHours !== undefined ? `${recommended.timezoneDifferenceHours} hour(s)` : "Not available; confirm working-hour locations and schedules."}</li><li><b>Estimated business-hour overlap:</b> {recommended?.coverageHours !== undefined ? `${recommended.coverageHours} hour(s) in a standard eight-hour day` : "Not available; confirm required collaboration coverage."}</li><li><b>Operational decision:</b> Confirm that the overlap supports handovers, meetings, incident response and customer coverage.</li></ul></Accordion>
      <Accordion title="Compliance"><ul>{recommended?.checks?.length ? recommended.checks.map((check) => <li key={check}>{check}</li>) : <li>No completed compliance check was returned; obtain contract and delivery approval before proceeding.</li>}{recommended?.gaps?.map((gap) => <li key={gap}><b>Open evidence:</b> {gap}</li>)}</ul></Accordion>
      <Accordion title="Actions before approval"><ul>{recommended?.nextActions?.length ? recommended.nextActions.map((action) => <li key={action}>{action}</li>) : <><li>Confirm the final headcount and destination with the project owner.</li><li>Validate the transition cost, operational coverage and compliance evidence.</li><li>Record an Accept, Modify or Reject decision in the Recommendations tab.</li></>}</ul></Accordion>
    </div>}
    <div className="sticky-actions"><span>{canContinue ? "The selected recommendations are ready for approval." : "Accept or modify at least one recommendation to continue."}</span><div><Button onClick={() => navigate(`/analyses/${analysisId}/setup`)}>Back</Button><Button variant="primary" disabled={!canContinue} onClick={submit}>Continue to Approval</Button></div></div><RecommendationDialog key={selected?.id || "none"} item={selected} onClose={() => setSelected(null)} />
  </div>;
}

export function ApprovalPage() {
  const { analysisId, analysis } = useCurrentAnalysis();
  const navigate = useNavigate();
  const state = useAnalysisStore();
  const [decision, setDecision] = useState<"approved" | "rejected" | "changes_requested" | null>(null);
  const [comment, setComment] = useState("");
  if (!analysis) return <NotFoundPage />;
  const recommendations = state.recommendations.filter((item) => item.analysisId === analysisId && ["accepted", "modified"].includes(item.status));
  const totals = analysisTotals(analysisId, state);
  const save = async () => { if (!decision || (decision !== "approved" && !comment.trim())) return; const selectedDecision = decision; try { await state.decideBackend(analysisId, selectedDecision, comment || "Approved after human review."); setDecision(null); navigate(selectedDecision === "approved" ? `/analyses/${analysisId}/report` : "/analyses"); } catch { /* store surfaces the API error */ } };
  return <div className="page"><Breadcrumbs items={workspaceCrumbs(analysis, "Approval")} /><PageHeader eyebrow="STEP 5 OF 6" title="Approve final scenario" description="Review the final human-adjusted scenario before recording a decision." /><StepNavigation current="approve" />
    <div className="metric-grid review-metrics"><MetricCard label="Recommendations" value={recommendations.length} tone="info" /><MetricCard label="Annual Savings" value={euro(totals.savings)} tone="positive" /><MetricCard label="First-Year Savings" value={euro(totals.firstYear)} tone="positive" /><MetricCard label="Confidence" value={`${totals.confidence}%`} tone="info" /><MetricCard label="Risk" value="Medium" tone="warning" /><MetricCard label="Decision Status" value={statusLabel(analysis.status)} tone="warning" /></div>
    <div className="section-stack"><Card title="Approval summary"><div className="decision-summary"><div className="summary-item"><small>Current annual cost</small><strong>{euro(totals.current)}</strong></div><div className="summary-item"><small>Proposed annual cost</small><strong>{euro(totals.proposed)}</strong></div><div className="summary-item"><small>Destination countries</small><strong>{analysis.selectedCountries.join(", ")}</strong></div></div></Card>
      <Accordion title="Final Scenario" open><ul>{recommendations.map((item) => <li key={item.id}><b>{item.role}</b>: {item.sourceLocation} to {item.targetLocation}, {euro(item.savings)} annual savings.</li>)}</ul></Accordion>
      <Accordion title="Changes From AI"><ul>{recommendations.filter((item) => item.status === "modified").map((item) => <li key={item.id}><b>{item.role}</b>: Savings changed from {euro(item.originalSavings)} to {euro(item.savings)}. {item.comment}</li>)}</ul>{!recommendations.some((item) => item.status === "modified") && <p>No recommendations were modified.</p>}</Accordion>
      <Card title="Approval actions"><p>This records a human decision only. It does not execute a workforce, supplier or SAP action.</p><div className="approval-actions"><Button variant="primary" onClick={() => setDecision("approved")}>Approve</Button><Button variant="danger" onClick={() => setDecision("rejected")}>Reject</Button><Button onClick={() => setDecision("changes_requested")}>Request Changes</Button></div></Card></div>
    <Modal open={Boolean(decision)} title={decision ? statusLabel(decision) : "Decision"} size="small" onClose={() => setDecision(null)} footer={<><Button onClick={() => setDecision(null)}>Cancel</Button><Button variant={decision === "rejected" ? "danger" : "primary"} disabled={decision !== "approved" && !comment.trim()} onClick={save}>Confirm Decision</Button></>}><FormField label={decision === "approved" ? "Approval comment" : "Comment (required)"}><textarea value={comment} onChange={(event) => setComment(event.target.value)} placeholder="Record the reason for this decision" /></FormField></Modal>
  </div>;
}

export function ReportPage() {
  const { analysisId, analysis } = useCurrentAnalysis();
  const navigate = useNavigate();
  const report = useAnalysisStore((state) => state.reports.find((item) => item.analysisId === analysisId));
  if (!analysis) return <NotFoundPage />;
  if (!report) return <div className="page"><Breadcrumbs items={workspaceCrumbs(analysis, "Report")} /><PageHeader title="Analysis report" /><Card><EmptyState title="Report not available" description="A report is created only after the analysis is approved." action={<Button onClick={() => navigate(pathForStep(analysis))}>Return to analysis</Button>} /></Card></div>;
  const auditColumns: Column<AuditEvent>[] = [{ key: "date", label: "Date", value: (row) => new Date(row.date).toLocaleString(), sortValue: (row) => row.date }, { key: "user", label: "User", value: (row) => row.user }, { key: "action", label: "Action", value: (row) => row.action }, { key: "comment", label: "Comment", value: (row) => row.comment }];
  return <div className="page report-page"><Breadcrumbs items={workspaceCrumbs(analysis, "Report")} /><PageHeader eyebrow="STEP 6 OF 6" title="Approved analysis report" description={`Generated ${new Date(report.generatedAt).toLocaleString()}`} actions={<Button className="no-print" onClick={() => window.print()} icon="print">Print</Button>} /><StepNavigation current="report" />
    <Card className="report-section" title="Executive Summary"><p>{report.executiveSummary}</p></Card><Card className="report-section" title="Data Readiness"><p>{report.dataReadiness}</p></Card><Card className="report-section" title="Analysis Scope"><p>{report.scope}</p></Card><Card className="report-section" title="Financial Impact"><div className="report-facts"><div><small>Current annual cost</small><strong>{euro(report.currentCost)}</strong></div><div><small>Proposed annual cost</small><strong>{euro(report.proposedCost)}</strong></div><div><small>Annual savings</small><strong>{euro(report.annualSavings)}</strong></div><div><small>Savings rate</small><strong>{report.currentCost ? Math.round(report.annualSavings / report.currentCost * 100) : 0}%</strong></div></div></Card>
    <Card className="report-section" title="Approval Decision"><div className="decision-summary"><div className="summary-item"><small>Decision</small><strong><StatusBadge status={report.decision.decision} /></strong></div><div className="summary-item"><small>Approver</small><strong>{report.decision.approver}</strong></div><div className="summary-item"><small>Decision date</small><strong>{new Date(report.decision.decidedAt).toLocaleDateString()}</strong></div></div><p>{report.decision.comment}</p></Card>
    <Card className="report-section table-card" title="Audit Summary"><DataTable rows={report.audit} columns={auditColumns} pageSize={8} /></Card>
  </div>;
}

export function ReferenceDataPage() {
  const [search, setSearch] = useState(""); const [risk, setRisk] = useState("all");
  const rows = referenceRows.filter((row) => `${row.country} ${row.role}`.toLowerCase().includes(search.toLowerCase()) && (risk === "all" || row.risk === risk));
  const columns: Column<ReferenceRow>[] = [{ key: "country", label: "Country", value: (row) => row.country, sortValue: (row) => row.country }, { key: "role", label: "Role", value: (row) => row.role, sortValue: (row) => row.role }, { key: "rate", label: "Annual Rate", value: (row) => euro(row.annualRate), sortValue: (row) => row.annualRate, className: "numeric" }, { key: "currency", label: "Currency", value: (row) => row.currency }, { key: "risk", label: "Risk", value: (row) => <StatusBadge status={row.risk === "Low" ? "success" : row.risk === "High" ? "error" : "warning"} label={row.risk} /> }, { key: "date", label: "Effective Date", value: (row) => row.effectiveDate, sortValue: (row) => row.effectiveDate }];
  return <div className="page"><Breadcrumbs items={[{ label: "Reference Data" }]} /><PageHeader eyebrow="GOVERNED INPUTS" title="Reference Data" description="Read-only country, rate and risk values used by the prototype." /><div className="filter-bar"><SearchField value={search} onChange={setSearch} placeholder="Search country or role" /><select aria-label="Filter by risk" value={risk} onChange={(event) => setRisk(event.target.value)}><option value="all">All risk levels</option><option>Low</option><option>Medium</option><option>High</option></select></div><Card className="table-card" title="Rate and location reference"><DataTable rows={rows} columns={columns} /></Card></div>;
}

export function ReportsPage() {
  const navigate = useNavigate();
  const reports = useAnalysisStore((state) => state.reports);
  const analyses = useAnalysisStore((state) => state.analyses);
  const rows = reports.map((report) => ({ ...report, id: report.analysisId }));
  const columns: Column<ReportSnapshot & { id: string }>[] = [{ key: "analysis", label: "Analysis", value: (row) => <span className="primary-cell"><b>{analyses.find((item) => item.id === row.analysisId)?.name || row.analysisId}</b><small>{row.analysisId}</small></span>, sortValue: (row) => row.analysisId }, { key: "generated", label: "Generated", value: (row) => new Date(row.generatedAt).toLocaleDateString(), sortValue: (row) => row.generatedAt }, { key: "savings", label: "Annual Savings", value: (row) => euro(row.annualSavings), sortValue: (row) => row.annualSavings, className: "numeric" }, { key: "decision", label: "Decision", value: (row) => <StatusBadge status={row.decision.decision} /> }, { key: "open", label: "", value: () => <Icon name="navigation-right-arrow" /> }];
  return <div className="page"><Breadcrumbs items={[{ label: "Reports" }]} /><PageHeader eyebrow="APPROVED OUTPUTS" title="Reports" description="Open immutable snapshots created by approved analyses." /><Card className="table-card" title="Generated reports"><DataTable rows={rows} columns={columns} onRowClick={(row) => navigate(`/analyses/${row.analysisId}/report`)} empty="No approved reports yet." /></Card></div>;
}

export function AuditHistoryPage() {
  const [search, setSearch] = useState("");
  const audit = useAnalysisStore((state) => state.audit);
  const rows = useMemo(() => audit.filter((row) => `${row.user} ${row.action} ${row.entity} ${row.comment}`.toLowerCase().includes(search.toLowerCase())), [audit, search]);
  const columns: Column<AuditEvent>[] = [{ key: "date", label: "Date", value: (row) => new Date(row.date).toLocaleString(), sortValue: (row) => row.date }, { key: "user", label: "User", value: (row) => row.user, sortValue: (row) => row.user }, { key: "analysis", label: "Analysis", value: (row) => row.analysisId, sortValue: (row) => row.analysisId }, { key: "action", label: "Action", value: (row) => row.action, sortValue: (row) => row.action }, { key: "entity", label: "Entity", value: (row) => row.entity }, { key: "comment", label: "Comment", value: (row) => row.comment }];
  return <div className="page"><Breadcrumbs items={[{ label: "Audit History" }]} /><PageHeader eyebrow="TRACEABILITY" title="Audit History" description="Review the append-only mock record of analysis and human-review decisions." /><div className="filter-bar"><SearchField value={search} onChange={setSearch} placeholder="Search audit history" /></div><Card className="table-card" title="Recorded events" subtitle={`${rows.length} events`}><DataTable rows={rows} columns={columns} pageSize={8} /></Card></div>;
}

export function NotFoundPage() {
  const navigate = useNavigate();
  return <div className="page"><Breadcrumbs items={[{ label: "Not Found" }]} /><Card><EmptyState title="We couldn't find that page" description="The analysis may have been reset or the address is invalid." action={<Button variant="primary" onClick={() => navigate("/analyses")}>Return to Analyses</Button>} /></Card></div>;
}

export function RootRedirect() { return <Navigate to="/analyses" replace />; }
