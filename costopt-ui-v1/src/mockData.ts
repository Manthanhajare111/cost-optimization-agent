import type { RepositorySnapshot, ReferenceRow } from "./domain";

const stamp = "2026-10-20T09:30:00.000Z";

export const seedSnapshot: RepositorySnapshot = {
  analyses: [
    { id: "ANA-1042", origin: "demo", name: "Customer Platform Right-Shoring", status: "awaiting_approval", currentStep: "approve", createdBy: "A. Mehta", createdDate: "2026-10-12", updatedDate: "2026-10-19", estimatedSavings: 428000, selectedCountries: ["India", "Portugal"], assumptions: { horizon: 3, transitionCost: 120000, contingency: 10, notes: "Maintain EU coverage during transition." }, warningsAcknowledged: true },
    { id: "ANA-1038", origin: "demo", name: "Finance Operations Benchmark", status: "needs_attention", currentStep: "check-data", createdBy: "S. Farheen", createdDate: "2026-10-08", updatedDate: "2026-10-18", estimatedSavings: 0, selectedCountries: [], assumptions: { horizon: 3, transitionCost: 0, contingency: 10, notes: "" }, warningsAcknowledged: false },
    { id: "ANA-1029", origin: "demo", name: "SAP Delivery Hub Review", status: "approved", currentStep: "report", createdBy: "M. Rao", createdDate: "2026-09-22", updatedDate: "2026-10-11", estimatedSavings: 312000, selectedCountries: ["India"], assumptions: { horizon: 3, transitionCost: 80000, contingency: 8, notes: "Approved pilot." }, warningsAcknowledged: true },
    { id: "ANA-1024", origin: "demo", name: "Data Engineering Sourcing", status: "in_progress", currentStep: "review", createdBy: "A. Mehta", createdDate: "2026-09-16", updatedDate: "2026-10-06", estimatedSavings: 196000, selectedCountries: ["Poland", "India"], assumptions: { horizon: 2, transitionCost: 65000, contingency: 12, notes: "" }, warningsAcknowledged: true },
  ],
  files: [
    { id: "FIL-1", analysisId: "ANA-1042", name: "fieldglass-workforce.xlsx", type: "Workforce", status: "ready", issues: 1 },
    { id: "FIL-2", analysisId: "ANA-1038", name: "finance-resources.csv", type: "Workforce", status: "review_required", issues: 3 },
    { id: "FIL-3", analysisId: "ANA-1029", name: "sap-delivery-sample.xlsx", type: "Workforce", status: "ready", issues: 0 },
  ],
  issues: [
    { id: "ISS-1", analysisId: "ANA-1042", severity: "warning", record: "Row 238 · Role FG-238", message: "Rate card expires within the analysis horizon.", resolutionStatus: "resolved" },
    { id: "ISS-2", analysisId: "ANA-1038", severity: "error", record: "Row 1842 · Worker 1842", message: "Current annual cost is missing.", resolutionStatus: "open" },
    { id: "ISS-3", analysisId: "ANA-1038", severity: "warning", record: "Row 14 · Role FIN-14", message: "Location code is not mapped to reference data.", resolutionStatus: "open" },
    { id: "ISS-4", analysisId: "ANA-1038", severity: "info", record: "Row 9 · Supplier S-009", message: "Supplier record was excluded from the calculation.", resolutionStatus: "excluded" },
  ],
  roles: [
    { id: "ROL-1", analysisId: "ANA-1042", title: "Senior Developer", location: "Germany", headcount: 8, annualCost: 960000, selected: true },
    { id: "ROL-2", analysisId: "ANA-1042", title: "QA Engineer", location: "Germany", headcount: 5, annualCost: 480000, selected: true },
    { id: "ROL-3", analysisId: "ANA-1042", title: "Product Owner", location: "Germany", headcount: 2, annualCost: 260000, selected: false },
    { id: "ROL-4", analysisId: "ANA-1029", title: "SAP Consultant", location: "Germany", headcount: 6, annualCost: 780000, selected: true },
  ],
  recommendations: [
    { id: "REC-1", analysisId: "ANA-1042", role: "Senior Developer", sourceLocation: "Germany", targetLocation: "India", savings: 310000, originalSavings: 310000, confidence: 88, risk: "Low", status: "accepted", rationale: "Strong rate advantage with verified capacity and delivery overlap.", comment: "" },
    { id: "REC-2", analysisId: "ANA-1042", role: "QA Engineer", sourceLocation: "Germany", targetLocation: "Portugal", savings: 118000, originalSavings: 118000, confidence: 81, risk: "Medium", status: "modified", rationale: "Nearshore option preserves time-zone alignment.", comment: "Retain two senior QA roles during transition." },
    { id: "REC-3", analysisId: "ANA-1024", role: "Data Engineer", sourceLocation: "Germany", targetLocation: "Poland", savings: 196000, originalSavings: 196000, confidence: 77, risk: "Medium", status: "pending", rationale: "Available skills with moderate transition complexity.", comment: "" },
  ],
  approvals: [
    { analysisId: "ANA-1029", decision: "approved", approver: "P. Kulkarni", comment: "Approved for controlled pilot.", decidedAt: "2026-10-11T14:20:00.000Z" },
  ],
  reports: [{
    analysisId: "ANA-1029", generatedAt: "2026-10-11T14:20:00.000Z",
    executiveSummary: "SAP Delivery Hub Review identifies EUR 312,000 in annual savings through a controlled India delivery pilot.",
    dataReadiness: "All required workforce, rate-card and location fields passed validation.",
    scope: "India · SAP Consultant delivery roles",
    currentCost: 780000, proposedCost: 468000, annualSavings: 312000,
    decision: { analysisId: "ANA-1029", decision: "approved", approver: "P. Kulkarni", comment: "Approved for controlled pilot.", decidedAt: "2026-10-11T14:20:00.000Z" },
    audit: [{ id: "AUD-3", analysisId: "ANA-1029", user: "P. Kulkarni", action: "Approved", entity: "Approval", date: "2026-10-11T14:20:00.000Z", comment: "Approved for controlled pilot." }],
  }],
  audit: [
    { id: "AUD-1", analysisId: "ANA-1042", user: "A. Mehta", action: "Submitted for approval", entity: "Analysis", date: stamp, comment: "Recommended scenario reviewed." },
    { id: "AUD-2", analysisId: "ANA-1038", user: "S. Farheen", action: "Data validation failed", entity: "File", date: "2026-10-18T08:15:00.000Z", comment: "Three records need attention." },
    { id: "AUD-3", analysisId: "ANA-1029", user: "P. Kulkarni", action: "Approved", entity: "Approval", date: "2026-10-11T14:20:00.000Z", comment: "Approved for controlled pilot." },
  ],
};

export const referenceRows: ReferenceRow[] = [
  { id: "REF-1", country: "Germany", role: "Senior Developer", annualRate: 120000, currency: "EUR", risk: "Low", effectiveDate: "2026-01-01" },
  { id: "REF-2", country: "India", role: "Senior Developer", annualRate: 58000, currency: "EUR", risk: "Low", effectiveDate: "2026-01-01" },
  { id: "REF-3", country: "Portugal", role: "QA Engineer", annualRate: 72000, currency: "EUR", risk: "Medium", effectiveDate: "2026-01-01" },
  { id: "REF-4", country: "Poland", role: "Data Engineer", annualRate: 78000, currency: "EUR", risk: "Medium", effectiveDate: "2026-01-01" },
  { id: "REF-5", country: "Philippines", role: "QA Engineer", annualRate: 46000, currency: "EUR", risk: "Medium", effectiveDate: "2026-01-01" },
];
