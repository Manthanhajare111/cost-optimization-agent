export type AnalysisStatus = "draft" | "needs_attention" | "in_progress" | "awaiting_approval" | "approved" | "rejected";
export type WorkflowStep = "add-data" | "check-data" | "setup" | "review" | "approve" | "report";
export type FileStatus = "uploaded" | "review_required" | "ready" | "error";
export type IssueSeverity = "success" | "warning" | "error" | "info";
export type ResolutionStatus = "open" | "resolved" | "excluded";
export type RecommendationStatus = "pending" | "accepted" | "modified" | "rejected" | "removed" | "specialist_review";
export type ApprovalResult = "approved" | "rejected" | "changes_requested";

export interface Analysis {
  id: string;
  name: string;
  status: AnalysisStatus;
  currentStep: WorkflowStep;
  createdBy: string;
  createdDate: string;
  updatedDate: string;
  estimatedSavings: number;
  selectedCountries: string[];
  assumptions: { horizon: number; transitionCost: number; contingency: number; notes: string };
  warningsAcknowledged: boolean;
  origin?: "demo" | "local" | "backend";
  scenarioId?: string;
  moveCountsBySowLevel?: Record<string, number>;
  sourceMode?: "fieldglass" | "excel";
  backendUploadId?: string;
}

export interface AnalysisFile {
  id: string;
  analysisId: string;
  name: string;
  type: string;
  status: FileStatus;
  issues: number;
  fileSize?: number;
  uploadedAt?: string;
  backendUploadId?: string;
  cleaningRunId?: string;
  cleaningReady?: boolean;
  selectedSow?: string;
  validationStatus?: "not_started" | "pending" | "ready" | "blocked";
}

export interface DataIssue {
  id: string;
  analysisId: string;
  severity: IssueSeverity;
  record: string;
  message: string;
  resolutionStatus: ResolutionStatus;
}

export interface Role {
  id: string;
  analysisId: string;
  title: string;
  location: string;
  headcount: number;
  annualCost: number;
  selected: boolean;
  moveCount?: number;
}

export interface Recommendation {
  id: string;
  analysisId: string;
  role: string;
  sourceLocation: string;
  targetLocation: string;
  savings: number;
  originalSavings: number;
  confidence: number;
  risk: "Low" | "Medium" | "High";
  status: RecommendationStatus;
  rationale: string;
  comment: string;
  backendOptionId?: string;
  baselineCost?: number;
  futureCost?: number;
  isRecommended?: boolean;
  details?: RecommendationDetail[];
  checks?: string[];
  gaps?: string[];
  estimatedDowntimeHours?: number;
  transitionDurationWeeks?: number;
  knowledgeTransferHours?: number;
  onboardingHours?: number;
  coverageHours?: number;
  timezoneDifferenceHours?: number;
  nextActions?: string[];
}

export interface RecommendationDetail {
  id: string;
  sow: string;
  role: string;
  count: number;
  availableCount: number;
  fromRegion: string;
  toRegion: string;
  currentCost: number;
  projectedCost: number;
  estimatedSavings: number;
}

export interface ApprovalDecision {
  analysisId: string;
  decision: ApprovalResult;
  approver: string;
  comment: string;
  decidedAt: string;
}

export interface AuditEvent {
  id: string;
  analysisId: string;
  user: string;
  action: string;
  entity: string;
  date: string;
  comment: string;
}

export interface ReportSnapshot {
  analysisId: string;
  generatedAt: string;
  executiveSummary: string;
  dataReadiness: string;
  scope: string;
  currentCost: number;
  proposedCost: number;
  annualSavings: number;
  decision: ApprovalDecision;
  audit: AuditEvent[];
}

export interface ReferenceRow {
  id: string;
  country: string;
  role: string;
  annualRate: number;
  currency: string;
  risk: "Low" | "Medium" | "High";
  effectiveDate: string;
}

export interface RepositorySnapshot {
  analyses: Analysis[];
  files: AnalysisFile[];
  issues: DataIssue[];
  roles: Role[];
  recommendations: Recommendation[];
  approvals: ApprovalDecision[];
  reports: ReportSnapshot[];
  audit: AuditEvent[];
}

export interface AnalysisRepository {
  load(): Promise<RepositorySnapshot>;
  save(snapshot: RepositorySnapshot): Promise<void>;
}

export const statusLabel = (value: string) => value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
export const euro = (value: number) => new Intl.NumberFormat("en-IE", { style: "currency", currency: "EUR", maximumFractionDigits: 0 }).format(value);
