from pathlib import Path
from typing import Literal, cast

from pydantic import BaseModel, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT_DIR = Path(__file__).resolve().parents[2]
AgentName = Literal[
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


class AgentLLMProfile(BaseModel):
    """Non-secret LLM configuration available to a single runtime agent."""

    agent: AgentName
    enabled: bool
    provider: str
    model: str
    temperature: float = Field(ge=0, le=2)
    max_tokens: int = Field(gt=0)
    prompt_key: str


class Settings(BaseSettings):
    app_name: str = "CostOpt"
    environment: str = "local"
    log_level: str = "INFO"
    log_format: str = "json"
    data_dir: Path = ROOT_DIR / "data"
    runtime_dir: Path = ROOT_DIR / "data" / "runtime"
    db_path: Path = ROOT_DIR / "data" / "runtime" / "test.db"
    document_dir: Path = ROOT_DIR / "data" / "contracts" / "raw"
    synthetic_data_dir: Path = ROOT_DIR / "data" / "synthetic"
    sap_source_samples_dir: Path = ROOT_DIR / "data" / "source_samples" / "sap"
    use_mock_compliance: bool = True
    enable_procurement: bool = False
    gemini_api_key: SecretStr | None = Field(default=None, validation_alias="GEMINI_API_KEY")
    gemini_model: str = "gemini-3.5-flash-lite"
    llm_timeout_seconds: float = 20.0
    agent_llm_enabled: bool = False
    # Explicit validation requests can use Gemini independently of the optional
    # recommendation narrators. This never enables financial/compliance overrides.
    data_validation_llm_enabled: bool = True
    langsmith_tracing_enabled: bool = False
    langsmith_api_key: SecretStr | None = Field(default=None, validation_alias="LANGSMITH_API_KEY")
    langsmith_project: str = "costopt-workforce"
    langsmith_endpoint: str | None = None
    compliance_agent_llm_enabled: bool = False
    compliance_agent_llm_model: str | None = None
    compliance_agent_llm_temperature: float = Field(default=0.0, ge=0, le=2)
    compliance_agent_llm_max_tokens: int = Field(default=700, gt=0)
    optimization_agent_llm_enabled: bool = False
    optimization_agent_llm_model: str | None = None
    optimization_agent_llm_temperature: float = Field(default=0.0, ge=0, le=2)
    optimization_agent_llm_max_tokens: int = Field(default=500, gt=0)
    orchestrator_agent_llm_enabled: bool = False
    orchestrator_agent_llm_model: str | None = None
    orchestrator_agent_llm_temperature: float = Field(default=0.0, ge=0, le=2)
    orchestrator_agent_llm_max_tokens: int = Field(default=500, gt=0)
    optimization_engine: str = "ortools"
    workforce_retain_roles: str = "Architect,Delivery Lead"

    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_prefix="COSTOPT_",
        extra="ignore",
    )

    @model_validator(mode="after")
    def resolve_backend_paths(self) -> "Settings":
        """Resolve relative .env paths from backend/, independent of launch directory."""
        for field_name in ("data_dir", "runtime_dir", "db_path",
                           "document_dir", "synthetic_data_dir", "sap_source_samples_dir"):
            value = getattr(self, field_name)
            if not value.is_absolute():
                setattr(self, field_name, (ROOT_DIR / value).resolve())
        return self

    @property
    def agent_llm_profiles(self) -> dict[AgentName, AgentLLMProfile]:
        """Map all target roles to their current LLM permissions.

        Only evidence explanation, optimization explanation, and reporting are LLM-enabled
        today. The other roles deliberately run deterministic components until their SAP
        tools and prompts are introduced.
        """
        provider = "gemini"
        deterministic_roles: tuple[AgentName, ...] = (
            "planner",
            "retriever",
            "tail_spend",
            "risk_bcp",
            "timezone_mitigation",
            "financial_working_capital",
            "approval",
        )
        profiles: dict[AgentName, AgentLLMProfile] = {
            role: AgentLLMProfile(
                agent=role,
                enabled=False,
                provider="deterministic",
                model="",
                temperature=0,
                max_tokens=1,
                prompt_key="not_applicable",
            )
            for role in deterministic_roles
        }
        profiles.update({
            "contract": AgentLLMProfile(
                agent="contract",
                enabled=self.agent_llm_enabled and self.compliance_agent_llm_enabled,
                provider=provider if self.agent_llm_enabled and self.compliance_agent_llm_enabled else "deterministic",
                model=(self.compliance_agent_llm_model or self.gemini_model) if self.agent_llm_enabled and self.compliance_agent_llm_enabled else "",
                temperature=self.compliance_agent_llm_temperature,
                max_tokens=self.compliance_agent_llm_max_tokens,
                prompt_key="compliance_evidence_review_v1",
            ),
            "optimization": AgentLLMProfile(
                agent="optimization",
                enabled=self.agent_llm_enabled and self.optimization_agent_llm_enabled,
                provider=provider if self.agent_llm_enabled and self.optimization_agent_llm_enabled else "deterministic",
                model=(self.optimization_agent_llm_model or self.gemini_model) if self.agent_llm_enabled and self.optimization_agent_llm_enabled else "",
                temperature=self.optimization_agent_llm_temperature,
                max_tokens=self.optimization_agent_llm_max_tokens,
                prompt_key="optimization_explanation_v1",
            ),
            "reporting": AgentLLMProfile(
                agent="reporting",
                enabled=self.agent_llm_enabled and self.orchestrator_agent_llm_enabled,
                provider=provider if self.agent_llm_enabled and self.orchestrator_agent_llm_enabled else "deterministic",
                model=(self.orchestrator_agent_llm_model or self.gemini_model) if self.agent_llm_enabled and self.orchestrator_agent_llm_enabled else "",
                temperature=self.orchestrator_agent_llm_temperature,
                max_tokens=self.orchestrator_agent_llm_max_tokens,
                prompt_key="orchestrator_decision_brief_v1",
            ),
        })
        return cast(dict[AgentName, AgentLLMProfile], profiles)

    def get_agent_llm_profile(self, agent: AgentName) -> AgentLLMProfile:
        return self.agent_llm_profiles[agent]

    @property
    def retain_roles(self) -> set[str]:
        return {
            role.strip().casefold()
            for role in self.workforce_retain_roles.split(",")
            if role.strip()
        }


settings = Settings()
