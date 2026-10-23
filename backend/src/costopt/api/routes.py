from fastapi import APIRouter, HTTPException, Request, Response

from costopt.agents.catalog import list_agent_definitions
from costopt.agents.data_cleaning import CleaningApproval, CleaningRequest, approve, get_run, propose
from costopt.agents.document_validation import DocumentValidationRequest, validate_documents
from costopt.models.domain import AgentDefinition, Location, ScenarioListItem
from costopt.observability.logging import get_logger
from costopt.pipeline.scenario_analysis import list_scenario_previews
from costopt.pipeline.workforce_uploads import (
    MAX_FILE_BYTES,
    ingest_freeform_file,
    ingest_sow_overview,
    ingest_supporting_file,
    ingest_template_file,
    ingest_workforce_file,
    source_template,
)
from costopt.pipeline.workforce_use_cases import (
    AnalysisTitleUpdate,
    CaseRequest,
    ReviewRequest,
    UploadValidationRequest,
    analyze_case,
    case_context,
    consolidated_upload_preview,
    get_analysis,
    list_analyses,
    list_cases,
    list_reviews,
    save_review,
    source_preview,
    update_analysis_title,
    validate_workforce_upload,
)
from costopt.storage.repositories import list_locations

router = APIRouter()
logger = get_logger(__name__)


# --- Scenarios & Reference Data ---

@router.get("/scenarios", tags=["reference"], response_model=list[ScenarioListItem])
def get_scenarios() -> list[ScenarioListItem]:
    """List scenario previews with recalculated costs."""
    return list_scenario_previews()


@router.get("/locations", tags=["reference"], response_model=list[Location])
def get_locations() -> list[Location]:
    """List supported delivery and offshore locations."""
    return list_locations()


@router.get("/agents", tags=["agents"], response_model=list[AgentDefinition])
def get_agents() -> list[AgentDefinition]:
    """List the governed agents available in the system."""
    return list_agent_definitions()


# --- Workforce Use-Case Flow ---

@router.get("/workforce/use-cases", tags=["workforce-use-cases"])
def get_workforce_use_cases() -> list[dict[str, str]]:
    return list_cases()


@router.get("/workforce/fieldglass/entities", tags=["workforce-use-cases"])
def get_fieldglass_entities() -> dict[str, object]:
    return {"live_connected": False, "entities": []}


@router.get("/workforce/context/{scenario_id}", tags=["workforce-use-cases"])
def get_workforce_case_context(scenario_id: str) -> dict[str, object]:
    try:
        return case_context(scenario_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/workforce/data-preview/{source_id}", tags=["workforce-use-cases"])
def get_workforce_source_preview(
    source_id: str,
    scenario_id: str | None = None,
    upload_id: str | None = None,
) -> dict[str, object]:
    if source_id not in {"excel", "ariba", "fieldglass"}:
        raise HTTPException(status_code=400, detail="Unknown data source.")
    try:
        return source_preview(source_id, scenario_id, upload_id)  # type: ignore[arg-type]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/workforce/template/{source_id}", tags=["workforce-use-cases"])
def download_workforce_template(source_id: str, scenario_id: str) -> Response:
    try:
        content = source_template(source_id, scenario_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{scenario_id}-{source_id}-template.xlsx"'},
    )


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


@router.post("/workforce/upload-custom/{source_id}", tags=["workforce-use-cases"])
async def upload_custom_data(
    source_id: str,
    request: Request,
    scenario_id: str,
    filename: str,
    document_kind: str | None = None,
) -> dict[str, object]:
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
                    raise ValueError(
                        f"Expected the SAP Aggregator SOW Overview or the {source_id.title()} workforce template. "
                        f"SOW: {sow_error} Template: {template_error}"
                    ) from template_error
        return ingest_template_file(source_id, scenario_id, filename, bytes(content))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# --- Data Cleaning (Human-in-the-Loop) ---

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


# --- Validation & Consolidation ---

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


# --- Workforce Analysis & Reviews ---

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
