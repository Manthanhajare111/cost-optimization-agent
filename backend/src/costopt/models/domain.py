from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


CanonicalAgentName = Literal[
    "data_cleaning",
    "data_validation",
    "planner",
    "retriever",
    "contract",
    "tail_spend",
    "risk_bcp",
    "timezone_mitigation",
    "financial_working_capital",
    "optimization",
    "reporting",
    "approval",
]


class Location(BaseModel):
    location_id: str
    country: str
    region: str
    is_offshore: bool = False
    cost_index: float = Field(ge=0)


class Supplier(BaseModel):
    supplier_id: str
    name: str
    region: str | None = None
    capability_summary: str | None = None


class Squad(BaseModel):
    squad_id: str
    name: str
    business_unit: str


class Resource(BaseModel):
    resource_id: str
    supplier_id: str
    squad_id: str
    current_location_id: str
    role: str
    skill: str
    current_rate: float = Field(ge=0)
    pii_access: bool = False
    availability: str | None = None


class RateCard(BaseModel):
    rate_card_id: str
    supplier_id: str
    location_id: str
    role: str
    bill_rate: float = Field(ge=0)
    currency: str = "EUR"


class ContractRecord(BaseModel):
    contract_id: str
    supplier_id: str
    document_name: str
    contract_type: str
    offshore_permitted: bool
    data_residency_restriction: str | None = None
    customer_approval_required: bool = False


class ContractClause(BaseModel):
    clause_id: str
    contract_id: str | None = None
    clause_type: str
    clause_text: str


class ReferenceData(BaseModel):
    suppliers: list[Supplier] = Field(default_factory=list)
    locations: list[Location] = Field(default_factory=list)
    rate_cards: list[RateCard] = Field(default_factory=list)


class ScenarioMixExpectation(BaseModel):
    retain_roles: int = Field(ge=0)
    move_roles: int = Field(ge=0)


class WorkforceScenarioSeed(BaseModel):
    scenario_name: str
    squad: Squad
    resources: list[Resource] = Field(default_factory=list)
    target_location_id: str
    expected_mix: ScenarioMixExpectation
    billing_units_per_month: float = Field(default=10.14, gt=0)


class ContractScenarioSeed(BaseModel):
    contract: ContractRecord
    clauses: list[ContractClause] = Field(default_factory=list)
    expected_outcome: dict[str, object] = Field(default_factory=dict)
    document_text: str | None = None


class GoldenExpectation(BaseModel):
    scenario_id: str
    scenario_name: str
    squad_id: str
    current_location_id: str
    target_location_id: str
    expected_monthly_savings: float
    expected_annual_savings: float
    expected_confidence_score: float = Field(ge=0, le=1)
    expected_compliance: dict[str, object] = Field(default_factory=dict)
    expected_recommendation_summary: dict[str, object] = Field(default_factory=dict)


class ScenarioAnalysisRequest(BaseModel):
    scenario_name: str | None = Field(
        default=None,
        description="Catalogue scenario name or supported alias.",
    )
    scenario_id: str | None = Field(
        default=None,
        description="Stable scenario identifier, for example scn-001.",
    )
    target_location_id: str | None = Field(
        default=None,
        description="Optional location ID or country name; defaults to the scenario target.",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {"scenario_id": "scn-001"},
                {"scenario_name": "germany-philippines", "target_location_id": "Philippines"},
            ]
        }
    )

    @model_validator(mode="after")
    def require_scenario_identifier(self) -> "ScenarioAnalysisRequest":
        if not (self.scenario_name and self.scenario_name.strip()) and not (
            self.scenario_id and self.scenario_id.strip()
        ):
            raise ValueError("Provide scenario_id or scenario_name.")
        return self


class Citation(BaseModel):
    clause_id: str
    clause_type: str
    quote: str
    determination: Literal[
        "offshore_permitted",
        "data_residency_restriction",
        "customer_approval_required",
    ] | None = None


class ComplianceResult(BaseModel):
    assessment: Literal["allowed", "allowed_with_approval", "blocked"] | None = None
    offshore_permitted: bool
    data_residency_restriction: str | None = None
    customer_approval_required: bool = False
    summary: str
    citations: list[Citation] = Field(default_factory=list)


class SupplierComplianceSummary(BaseModel):
    supplier_id: str
    contract_id: str
    assessment: Literal["allowed", "allowed_with_approval", "blocked"]
    movement_permitted: bool
    evidence_complete: bool
    missing_evidence: list[str] = Field(default_factory=list)
    evidence_conflicts: list[str] = Field(default_factory=list)
    result: ComplianceResult


class ResourceDecision(BaseModel):
    resource_id: str
    supplier_id: str | None = None
    role: str
    skill: str
    action: str
    reason: str
    current_location_id: str
    target_location_id: str | None = None
    current_rate: float = Field(ge=0)
    projected_rate: float = Field(ge=0)


class CostSummary(BaseModel):
    currency: str = "EUR"
    billing_units_per_month: float = Field(gt=0)
    baseline_cost: float = Field(ge=0)
    future_cost: float = Field(ge=0)
    monthly_savings: float
    annual_savings: float


class ScenarioAnalysisResult(BaseModel):
    scenario_id: str
    scenario_name: str
    squad_id: str
    squad_name: str
    current_location_id: str
    current_location_ids: list[str] = Field(default_factory=list)
    target_location_id: str
    retained_count: int = Field(ge=0)
    moved_count: int = Field(ge=0)
    recommendation: str
    rationale: str
    confidence_score: float = Field(ge=0, le=1)
    compliance: ComplianceResult
    supplier_compliance: dict[str, SupplierComplianceSummary] = Field(default_factory=dict)
    costs: CostSummary
    resource_decisions: list[ResourceDecision] = Field(default_factory=list)
    data_quality_issues: list[str] = Field(default_factory=list)


class AgentLLMMetadata(BaseModel):
    enabled: bool
    provider: str
    model: str
    prompt_key: str


class AgentNarrative(BaseModel):
    summary: str
    key_considerations: list[str] = Field(default_factory=list)
    citation_ids: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)


class AgentToolTrace(BaseModel):
    tool_name: str
    status: Literal["completed", "skipped"]
    summary: str
    evidence_ids: list[str] = Field(default_factory=list)


class AgentFinding(BaseModel):
    """Structured, deterministic output produced by one specialist agent."""

    status: Literal["ready", "limited", "blocked", "approval_required", "not_required"]
    summary: str
    metrics: dict[str, object] = Field(default_factory=dict)
    data_gaps: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


class AgentStage(BaseModel):
    name: CanonicalAgentName | Literal["compliance", "recommendation", "human_review"]
    status: Literal["completed"]
    outcome: str
    llm: AgentLLMMetadata
    narrative: AgentNarrative
    used_fallback: bool
    tool_traces: list[AgentToolTrace] = Field(default_factory=list)
    finding: AgentFinding | None = None


class AgentDefinition(BaseModel):
    name: CanonicalAgentName
    display_name: str
    responsibility: str
    implementation_level: Literal["component", "expanded"]
    live_in_workforce_flow: bool = True


class ScenarioInputSnapshot(BaseModel):
    scenario_id: str
    scenario_name: str
    requested_target_location_id: str | None = None
    current_location_id: str
    current_location_ids: list[str] = Field(default_factory=list)
    target_location_id: str
    billing_units_per_month: float = Field(gt=0)
    squad: Squad
    resources: list[Resource] = Field(default_factory=list)
    rate_cards: list[RateCard] = Field(default_factory=list)
    contract: ContractRecord | None = None
    contracts: list[ContractRecord] = Field(default_factory=list)
    clauses: list[ContractClause] = Field(default_factory=list)
    assumptions: dict[str, object] = Field(default_factory=dict)


class ScenarioContext(BaseModel):
    scenario_id: str
    scenario_name: str
    currency: str = Field(min_length=3, max_length=3)
    billing_units_per_month: float = Field(gt=0)
    current_location_ids: list[str] = Field(min_length=1)
    target_location_id: str
    squad: Squad
    resources: list[Resource] = Field(min_length=1)
    rate_cards: list[RateCard] = Field(default_factory=list)
    contracts: list[ContractRecord] = Field(min_length=1)
    clauses: list[ContractClause] = Field(default_factory=list)
    locations: list[Location] = Field(min_length=1)
    assumptions: dict[str, object] = Field(default_factory=dict)

    @property
    def current_location_id(self) -> str:
        return self.current_location_ids[0] if len(self.current_location_ids) == 1 else "multiple"


class AgentRunResult(BaseModel):
    run_id: str | None = None
    recommendation_id: str | None = None
    recommendation: ScenarioAnalysisResult
    stages: list[AgentStage] = Field(default_factory=list)
    requires_human_review: bool = False
    review_reasons: list[str] = Field(default_factory=list)
    input_snapshot: ScenarioInputSnapshot | None = Field(default=None, exclude=True)


class RecommendationRecord(ScenarioAnalysisResult):
    recommendation_id: str
    created_at: datetime
    updated_at: datetime


class RecommendationListItem(BaseModel):
    recommendation_id: str
    scenario_id: str
    scenario_name: str
    squad_name: str
    target_location_id: str
    confidence_score: float = Field(ge=0, le=1)
    monthly_savings: float
    annual_savings: float
    created_at: datetime
    updated_at: datetime


class RecommendationSummary(BaseModel):
    recommendation: str
    monthly_savings: float
    annual_savings: float
    confidence_score: float = Field(ge=0, le=1)
    compliance_summary: str


class DecisionBrief(BaseModel):
    executive_summary: str
    recommended_action: str
    compliance_assessment: Literal["allowed", "allowed_with_approval", "blocked"]
    key_considerations: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    provider: Literal["llm", "deterministic_fallback"]
    used_fallback: bool
    notice: str = "AI-generated explanation. Savings are estimates and require human approval."


class SquadListItem(BaseModel):
    squad_id: str
    name: str
    business_unit: str
    resource_count: int = Field(ge=0)
    supplier_count: int = Field(ge=0)


class ScenarioListItem(BaseModel):
    scenario_id: str
    scenario_name: str
    squad_id: str
    squad_name: str
    target_location_id: str
    target_location_name: str
    baseline_cost: float = Field(ge=0)
    future_cost: float = Field(ge=0)
    monthly_savings: float
    annual_savings: float
    created_at: datetime


class ContractListItem(BaseModel):
    contract_id: str
    supplier_id: str
    supplier_name: str
    document_uri: str
    contract_type: str
    offshore_permitted: bool
    data_residency_restriction: str | None = None
    customer_approval_required: bool = False
    created_at: datetime
