import { HashRouter, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/ui";
import { AddDataPage, AnalysesPage, ApprovalPage, AuditHistoryPage, CheckDataPage, NotFoundPage, ReferenceDataPage, ReportPage, ReportsPage, ReviewPage, RootRedirect, SetupPage } from "./pages";

export default function App() {
  return <HashRouter><AppShell><Routes>
    <Route path="/" element={<RootRedirect />} />
    <Route path="/analyses" element={<AnalysesPage />} />
    <Route path="/analyses/:analysisId/add-data" element={<AddDataPage />} />
    <Route path="/analyses/:analysisId/check-data" element={<CheckDataPage />} />
    <Route path="/analyses/:analysisId/setup" element={<SetupPage />} />
    <Route path="/analyses/:analysisId/review" element={<ReviewPage />} />
    <Route path="/analyses/:analysisId/approve" element={<ApprovalPage />} />
    <Route path="/analyses/:analysisId/report" element={<ReportPage />} />
    <Route path="/reference-data" element={<ReferenceDataPage />} />
    <Route path="/reports" element={<ReportsPage />} />
    <Route path="/audit-history" element={<AuditHistoryPage />} />
    <Route path="*" element={<NotFoundPage />} />
  </Routes></AppShell></HashRouter>;
}
