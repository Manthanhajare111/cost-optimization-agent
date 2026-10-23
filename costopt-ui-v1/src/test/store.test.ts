import { beforeEach, describe, expect, it } from "vitest";
import { analysisTotals, useAnalysisStore } from "../store";

describe("analysisStore", () => {
  beforeEach(() => { localStorage.clear(); useAnalysisStore.getState().resetDemo(); });

  it("creates an analysis and records an audit event", () => {
    const before = useAnalysisStore.getState().analyses.length;
    const id = useAnalysisStore.getState().createAnalysis();
    const state = useAnalysisStore.getState();
    expect(state.analyses).toHaveLength(before + 1);
    expect(state.analyses[0]).toMatchObject({ id, status: "draft", currentStep: "add-data" });
    expect(state.audit[0]).toMatchObject({ analysisId: id, action: "Created analysis" });
  });

  it("updates totals from accepted recommendations", () => {
    const state = useAnalysisStore.getState();
    const totals = analysisTotals("ANA-1042", state);
    expect(totals.current).toBe(1440000);
    expect(totals.savings).toBe(428000);
    expect(totals.proposed).toBe(1012000);
  });

  it("previews backend financials while the recommended option is pending", () => {
    const totals = analysisTotals("ANA-BACKEND", {
      roles: [],
      recommendations: [{
        id: "OPT-1", analysisId: "ANA-BACKEND", role: "2 workforce roles",
        sourceLocation: "Germany", targetLocation: "India", savings: 184421,
        originalSavings: 184421, confidence: 87, risk: "Low", status: "pending",
        rationale: "Recommended backend option", comment: "", baselineCost: 448000,
        futureCost: 263579, isRecommended: true,
      }],
    });

    expect(totals).toMatchObject({ current: 448000, proposed: 263579, savings: 184421, confidence: 87 });
  });

  it("creates an immutable report snapshot on approval", () => {
    useAnalysisStore.getState().decide("ANA-1042", "approved", "Approved in test");
    const report = useAnalysisStore.getState().reports.find((item) => item.analysisId === "ANA-1042");
    expect(report?.decision.decision).toBe("approved");
    expect(report?.audit[0].action).toBe("approved");
    expect(useAnalysisStore.getState().analyses.find((item) => item.id === "ANA-1042")?.currentStep).toBe("report");
  });

  it("keeps every distinct document type from a multi-file package", () => {
    const state = useAnalysisStore.getState();
    const analysisId = state.createAnalysis();
    state.addMockFile(analysisId, new File(["proposal"], "Proposal_SOW.xlsx"), "proposal_workbook");
    state.addMockFile(analysisId, new File(["rates"], "Rate_Card.xlsx"), "rate_card");
    state.addMockFile(analysisId, new File(["contract"], "Contractual_Evidence.docx"), "contractual_evidence");
    state.addMockFile(analysisId, new File(["constraints"], "Delivery_Constraints.docx"), "delivery_constraints");

    const files = useAnalysisStore.getState().files.filter((item) => item.analysisId === analysisId);
    expect(files).toHaveLength(4);
    expect(new Set(files.map((item) => item.type))).toEqual(new Set(["proposal_workbook", "rate_card", "contractual_evidence", "delivery_constraints"]));
    expect(files.every((item) => item.fileSize && item.uploadedAt)).toBe(true);
  });
});
