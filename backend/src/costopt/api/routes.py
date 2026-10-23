from fastapi import APIRouter, HTTPException, Request, Response

from costopt.agents.data_cleaning import CleaningRequest, CleaningApproval, propose, approve, get_run
from costopt.agents.catalog import list_agent_definitions
from costopt.agents.document_validation import DocumentValidationRequest, validate_documents
from costopt.integrations.sap.ingestion import get_sap_ingestion_status
from costopt.integrations.sap.models import SapIngestionStatus
from costopt.integrations.sap.mock_api import get_mock_resource
from costopt.llm.decision_brief import create_decision_brief
from costopt.models.domain import (
    AgentRunResult,
    AgentDefinition,
    ContractListItem,
    DecisionBrief,
    Location,
    RecommendationListItem,
    RecommendationRecord,
    ScenarioAnalysisRequest,
    ScenarioListItem,
    SquadListItem,
)
from costopt.observability.logging import get_logger
from costopt.pipeline.orchestrator import run_scenario
from costopt.pipeline.scenario_analysis import list_scenario_previews
from costopt.pipeline.workforce_uploads import (
    MAX_FILE_BYTES, ingest_supporting_file, ingest_freeform_file, ingest_sow_overview, ingest_template_file, ingest_workforce_file, source_template,
)
from costopt.pipeline.fieldglass_preview import entity_catalogue, entity_preview
from costopt.pipeline.workforce_use_cases import (
    AnalysisTitleUpdate,
    CaseRequest,
    ReviewRequest,
    UploadValidationRequest,
    analyze_case,
    case_context,
    get_analysis,
    list_analyses,
    list_cases,
    list_reviews,
    save_review,
    source_preview,
    consolidated_upload_preview,
    update_analysis_title,
    validate_workforce_upload,
)
from costopt.storage.repositories import (
    list_contracts,
    list_locations,
    list_squads,
)
from costopt.storage.recommendation_store import (
    get_recommendation,
    list_recommendations,
)
from costopt.storage.agent_run_store import get_agent_run, save_agent_run
from costopt.storage.governance import get_source_catalogue


router = APIRouter()
logger = get_logger(__name__)


@router.get("/workforce/use-cases", tags=["workforce-use-cases"])
def get_workforce_use_cases() -> list[dict[str, str]]:
    return list_cases()


@router.get("/workforce/fieldglass/entities", tags=["workforce-use-cases"])
def get_fieldglass_entities() -> dict[str, object]:
    return entity_catalogue()


@router.get("/workforce/fieldglass/entities/{entity}", tags=["workforce-use-cases"])
def get_fieldglass_entity_preview(entity: str, scenario_id: str) -> dict[str, object]:
    try:
        return entity_preview(entity, scenario_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/workforce/context/{scenario_id}", tags=["workforce-use-cases"])
def get_workforce_case_context(scenario_id: str) -> dict[str, object]:
    try:
        return case_context(scenario_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/workforce/cleaning/{upload_id}/propose", tags=["workforce-use-cases"])
def propose_cleaning(upload_id: str, request: CleaningRequest) -> dict[str, object]:
    try:
        return propose(upload_id, request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/workforce/cleaning-runs/{run_id}", tags=["workforce-use-cases"])
def read_cleaning_run(run_id: str, scenario_id: str) -> dict[str, object]:
    try:
        result = get_run(run_id)
        if result["scenario_id"] != scenario_id:
            raise ValueError("Cleaning revision belongs to a different scenario.")
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/workforce/cleaning-runs/{run_id}/approve", tags=["workforce-use-cases"])
def approve_cleaning(run_id: str, request: CleaningApproval) -> dict[str, object]:
    try:
        return approve(run_id, request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/workforce/validate-documents", tags=["workforce-use-cases"])
def validate_document_pack(request: DocumentValidationRequest) -> dict[str, object]:
    try:
        return validate_documents(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/workforce/validate-upload", tags=["workforce-use-cases"])
def validate_uploaded_workforce(request: UploadValidationRequest) -> dict[str, object]:
    try:
        return validate_workforce_upload(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/workforce/consolidated-preview", tags=["workforce-use-cases"])
def get_consolidated_upload_preview(request: UploadValidationRequest) -> dict[str, object]:
    try:
        return consolidated_upload_preview(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/workforce/data-preview/{source_id}", tags=["workforce-use-cases"])
def get_workforce_source_preview(source_id: str, scenario_id: str | None = None,
                                 upload_id: str | None = None) -> dict[str, object]:
    if source_id not in {"excel", "ariba", "fieldglass"}:
        raise HTTPException(status_code=400, detail="Unknown data source.")
    try:
        return source_preview(source_id, scenario_id, upload_id)  # type: ignore[arg-type]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/workforce/upload-preview", tags=["workforce-use-cases"])
async def upload_workforce_preview(request: Request, scenario_id: str, filename: str) -> dict[str, object]:
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > MAX_FILE_BYTES:
            raise HTTPException(status_code=400, detail="Upload is limited to 2 MB.")
    try:
        return ingest_workforce_file(scenario_id, filename, bytes(content))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/workforce/template/{source_id}", tags=["workforce-use-cases"])
def download_workforce_template(source_id: str, scenario_id: str) -> Response:
    try:
        content = source_template(source_id, scenario_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(content=content,
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{scenario_id}-{source_id}-template.xlsx"'})


@router.post("/workforce/upload-template/{source_id}", tags=["workforce-use-cases"])
async def upload_source_template(source_id: str, request: Request, scenario_id: str,
                                 filename: str) -> dict[str, object]:
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > MAX_FILE_BYTES:
            raise HTTPException(status_code=400, detail="Upload is limited to 2 MB.")
    try:
        return ingest_template_file(source_id, scenario_id, filename, bytes(content))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/workforce/upload-custom/{source_id}", tags=["workforce-use-cases"])
async def upload_custom_data(source_id: str, request: Request, scenario_id: str, filename: str, document_kind: str | None = None) -> dict[str, object]:
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > MAX_FILE_BYTES:
            raise HTTPException(status_code=400, detail="Upload is limited to 2 MB.")
    try:
        if source_id == "supporting":
            return ingest_supporting_file(scenario_id, filename, bytes(content), document_kind)
        if source_id == "excel":
            if filename.lower().endswith(".xlsb"):
                return ingest_workforce_file(scenario_id, filename, bytes(content))
            try:
                return ingest_workforce_file(scenario_id, filename, bytes(content))
            except ValueError as workforce_error:
                if filename.lower().endswith(".xlsx"):
                    try:
                        return ingest_sow_overview(scenario_id, filename, bytes(content), source_id)
                    except ValueError:
                        pass
                if "resource_id column" in str(workforce_error):
                    return ingest_freeform_file(scenario_id, filename, bytes(content))
                raise
        if source_id == "fieldglass":
            try:
                return ingest_sow_overview(scenario_id, filename, bytes(content), source_id)
            except ValueError as sow_error:
                try:
                    return ingest_template_file(source_id, scenario_id, filename, bytes(content))
                except ValueError as template_error:
                    raise ValueError(f"Expected the SAP Aggregator SOW Overview or the {source_id.title()} workforce template. "
                                     f"SOW: {sow_error} Template: {template_error}") from template_error
        return ingest_template_file(source_id, scenario_id, filename, bytes(content))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/workforce/analyze", tags=["workforce-use-cases"])
def run_workforce_use_case(request: CaseRequest) -> dict[str, object]:
    try:
        return analyze_case(request).model_dump()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/workforce/analyses", tags=["workforce-use-cases"])
def get_workforce_analyses() -> list[dict[str, object]]:
    return [analysis.model_dump() for analysis in list_analyses()]


@router.get("/workforce/analyses/{analysis_id}", tags=["workforce-use-cases"])
def get_workforce_analysis(analysis_id: str) -> dict[str, object]:
    analysis = get_analysis(analysis_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="Analysis not found.")
    return analysis.model_dump()


@router.patch("/workforce/analyses/{analysis_id}/title", tags=["workforce-use-cases"])
def patch_workforce_analysis_title(analysis_id: str, update: AnalysisTitleUpdate) -> dict[str, object]:
    try:
        return update_analysis_title(analysis_id, update).model_dump()
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/workforce/analyses/{analysis_id}/reviews", tags=["workforce-use-cases"])
def get_workforce_reviews(analysis_id: str) -> list[dict[str, object]]:
    if get_analysis(analysis_id) is None:
        raise HTTPException(status_code=404, detail="Analysis not found.")
    return list_reviews(analysis_id)


@router.post("/workforce/analyses/{analysis_id}/reviews", tags=["workforce-use-cases"])
def post_workforce_review(analysis_id: str, review: ReviewRequest) -> dict[str, object]:
    try:
        return save_review(analysis_id, review)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/mvp-scope", tags=["meta"])
def get_mvp_scope() -> dict[str, object]:
    return {
        "primary_demo_lane": "workforce_right_shoring",
        "secondary_demo_lane": "procurement_spend_intelligence",
        "data_strategy": "synthetic_canonical_plus_sanitized_sap_samples",
        "storage_strategy": {
            "documents": "local_filesystem",
            "structured_data": "local_database",
        },
        "delivery_status": "sqlite-backed-ten-agent-components",
        "scenario_mode": "dynamic_seeded_catalogue",
        "scenario_identifier_fields": ["scenario_id", "scenario_name"],
        "target_location_input": "location_id_or_country",
        "authoritative_run_endpoint": "/api/v1/scenarios/run",
        "agent_count": 10,
        "agent_catalogue_endpoint": "/api/v1/agents",
    }


@router.get("/agents", tags=["agents"], response_model=list[AgentDefinition])
def get_agents() -> list[AgentDefinition]:
    """List the ten target-architecture agents currently represented in the runtime."""
    return list_agent_definitions()


@router.get("/data-governance/source-catalogue", tags=["governance"])
def get_data_governance_source_catalogue() -> dict[str, object]:
    """Expose field ownership, source status and open gaps for the local MVP."""
    return get_source_catalogue()


@router.post(
    "/scenarios/analyze",
    tags=["scenarios"],
    response_model=RecommendationRecord,
    deprecated=True,
)
def analyze_workforce_scenario(
    request: ScenarioAnalysisRequest,
) -> RecommendationRecord:
    try:
        persisted_run = _execute_scenario_run(request)
        if persisted_run.recommendation_id is None:
            raise RuntimeError("Persisted scenario run has no recommendation ID.")
        record = get_recommendation(persisted_run.recommendation_id)
        if record is None:
            raise RuntimeError("Persisted recommendation could not be reloaded.")
        return record
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/scenarios/run",
    tags=["scenarios"],
    response_model=AgentRunResult,
    response_model_exclude_none=True,
)
def run_workforce_agents(request: ScenarioAnalysisRequest) -> AgentRunResult:
    try:
        return _execute_scenario_run(request)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get(
    "/agent-runs/{run_id}",
    tags=["scenarios"],
    response_model=AgentRunResult,
    response_model_exclude_none=True,
)
def get_agent_run_audit(run_id: str) -> AgentRunResult:
    run = get_agent_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Agent run not found.")
    return run


@router.get("/squads", tags=["reference"], response_model=list[SquadListItem])
def get_squads() -> list[SquadListItem]:
    return list_squads()


@router.get("/scenarios", tags=["reference"], response_model=list[ScenarioListItem])
def get_scenarios() -> list[ScenarioListItem]:
    return list_scenario_previews()


@router.get("/contracts", tags=["reference"], response_model=list[ContractListItem])
def get_contracts() -> list[ContractListItem]:
    return list_contracts()


@router.get("/locations", tags=["reference"], response_model=list[Location])
def get_locations() -> list[Location]:
    return list_locations()


@router.get(
    "/integrations/sap/status",
    tags=["integrations"],
    response_model=SapIngestionStatus,
)
def get_sap_status() -> SapIngestionStatus:
    return get_sap_ingestion_status()


@router.get("/integrations/sap/mock/{resource}", tags=["integrations"])
def get_mock_sap_resource(resource: str, offset: int = 0, limit: int = 25) -> dict[str, object]:
    """Expose local-only, paged SAP-shaped sample data; it never calls SAP."""
    try:
        return get_mock_resource(resource, offset=offset, limit=limit)  # type: ignore[arg-type]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/recommendations", tags=["recommendations"], response_model=list[RecommendationListItem])
def get_recommendation_backlog() -> list[RecommendationListItem]:
    return list_recommendations()


@router.get(
    "/recommendations/{recommendation_id}",
    tags=["recommendations"],
    response_model=RecommendationRecord,
)
def get_recommendation_detail(recommendation_id: str) -> RecommendationRecord:
    record = get_recommendation(recommendation_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Recommendation not found.")
    return record


@router.post(
    "/recommendations/{recommendation_id}/explain",
    tags=["recommendations"],
    response_model=DecisionBrief,
)
def explain_recommendation(recommendation_id: str) -> DecisionBrief:
    record = get_recommendation(recommendation_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Recommendation not found.")
    return create_decision_brief(record)


def _execute_scenario_run(request: ScenarioAnalysisRequest) -> AgentRunResult:
    """Authoritative command path for analysis, recommendation, and audit persistence."""
    logger.info(
        "Scenario run started",
        extra={
            "event": "scenario_run_started",
            "scenario_id": request.scenario_id,
            "scenario_name": request.scenario_name,
            "requested_target_location": request.target_location_id,
        },
    )
    try:
        result = save_agent_run(run_scenario(request))
    except (FileNotFoundError, ValueError) as exc:
        logger.warning(
            "Scenario run rejected",
            extra={
                "event": "scenario_run_rejected",
                "scenario_id": request.scenario_id,
                "scenario_name": request.scenario_name,
                "reason": str(exc),
            },
        )
        raise
    except Exception:
        logger.exception(
            "Scenario run failed",
            extra={
                "event": "scenario_run_failed",
                "scenario_id": request.scenario_id,
                "scenario_name": request.scenario_name,
            },
        )
        raise
    logger.info(
        "Scenario run completed",
        extra={
            "event": "scenario_run_completed",
            "run_id": result.run_id,
            "scenario_id": result.recommendation.scenario_id,
            "requires_human_review": result.requires_human_review,
        },
    )
    return result
