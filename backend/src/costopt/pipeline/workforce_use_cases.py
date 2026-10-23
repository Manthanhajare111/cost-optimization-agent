"""Governed screening workflows for the documented workforce use cases.

The right-shoring and skill cases use the existing compliance/optimization preview.
Other cases are explicitly indicative where supplier transfer, coverage, or future
capacity evidence is unavailable in the local fixture.
"""

from __future__ import annotations

import csv
import json
import sqlite3
from math import ceil
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator

from costopt.config import settings
from costopt.agents.compliance import assess_contracts
from costopt.models.domain import RateCard, Resource, ScenarioAnalysisRequest
from costopt.pipeline.workforce_graph import run_workforce_graph
from costopt.pipeline.workforce_uploads import get_upload, inspect_supporting_uploads, validate_supporting_uploads
from costopt.storage.repositories import list_locations, load_scenario_context
from costopt.storage.sqlite import get_connection


CaseId = Literal["right_shoring", "skill_based", "multi_vendor", "timezone", "capacity_gap"]
SourceId = Literal["excel", "ariba", "fieldglass"]
ReviewDecision = Literal["request_changes", "ready_for_approval", "reject", "approved"]


class SourceFilter(BaseModel):
    column: str = Field(min_length=1, max_length=80)
    contains: str = Field(min_length=1, max_length=160)


class UploadValidationRequest(BaseModel):
    scenario_id: str = Field(min_length=1)
    upload_id: str = Field(min_length=1)
    source_filter: SourceFilter | None = None
    supporting_upload_ids: list[str] = Field(default_factory=list, max_length=3)
    destination_country_ids: list[str] = Field(default_factory=list, max_length=20)


def _uploaded_daily_rates(scenario_id: str, upload_ids: list[str]) -> dict[tuple[str, str, str], float]:
    """Return positive daily rates keyed by SOW (or generic), country and E-level.

    A blank SOW reference makes a rate card package-wide.  Some governed cards
    contain several role rates for the same country/E-level; their arithmetic
    mean is the deterministic E-level rate used by the recommendation workflow.
    """
    from costopt.agents.data_cleaning import _number

    daily_units = {"day", "daily", "person_day", "person-day", "person day",
                   "person_day_8_hours", "person-day-8-hours", "person day 8 hours"}
    buckets: dict[tuple[str, str, str], list[float]] = {}
    for upload_id in upload_ids:
        record = get_upload(upload_id)
        if not record or record.get("scenario_id") != scenario_id or record.get("data_kind") != "rate_card":
            continue
        for row in record.get("rows", []):
            currency = str(row.get("currency", "")).strip().upper()
            if len(currency) != 3 or not currency.isalpha() or str(row.get("rate_unit", "")).strip().lower() not in daily_units:
                continue
            try:
                value = _number(row.get("bill_rate", ""))
            except ValueError:
                continue
            if value > 0:
                key = (str(row.get("sow_reference", "")).strip().casefold() or "*",
                       str(row.get("country", "")).casefold(), str(row.get("level", "")).upper())
                buckets.setdefault(key, []).append(value)
    return {key: round(sum(values) / len(values), 2) for key, values in buckets.items()}


def _uploaded_rate_currency(scenario_id: str, upload_ids: list[str]) -> str | None:
    currencies: set[str] = set()
    for upload_id in upload_ids:
        record = get_upload(upload_id)
        if not record or record.get("scenario_id") != scenario_id or record.get("data_kind") != "rate_card":
            continue
        currencies.update(str(row.get("currency", "")).strip().upper() for row in record.get("rows", [])
                          if str(row.get("currency", "")).strip())
    return next(iter(currencies)) if len(currencies) == 1 else None


def _uploaded_rate(rates: dict[tuple[str, str, str], float], sow: object,
                   country: object, level: object) -> float | None:
    country_key = str(country or "").strip().casefold()
    level_key = str(level or "").strip().upper()
    sow_key = str(sow or "").strip().casefold()
    return rates.get((sow_key, country_key, level_key), rates.get(("*", country_key, level_key)))


GOVERNED_LEVEL_ROLES = {
    "E1": "Support Engineer",
    "E2": "QA Engineer",
    "E3": "Developer",
    "E4": "Delivery Lead",
    "E5": "Architect",
}
PLANNING_FX_TO_EUR = {"EUR": 1.0, "GBP": 1.17}


def _convert_planning_rate(value: float, source_currency: str, target_currency: str) -> float:
    source = source_currency.upper()
    target = target_currency.upper()
    if source == target:
        return round(value, 2)
    if source not in PLANNING_FX_TO_EUR or target not in PLANNING_FX_TO_EUR:
        raise ValueError(f"No governed planning FX rate is configured for {source} to {target}.")
    return round(value * PLANNING_FX_TO_EUR[source] / PLANNING_FX_TO_EUR[target], 2)


def _governed_source_rates(scenario_id: str, country: object) -> dict[str, tuple[float, str]]:
    """Return scenario-supplier baseline rates from the governed backend table."""
    country_name = str(country or "").strip()
    location = next((item for item in list_locations() if item.country.casefold() == country_name.casefold()), None)
    if not location:
        return {}
    context = load_scenario_context(scenario_id=scenario_id)
    supplier_ids = list(dict.fromkeys(resource.supplier_id for resource in context.resources))
    if not supplier_ids:
        return {}
    placeholders = ", ".join("?" for _ in supplier_ids)
    with get_connection() as connection:
        rows = connection.execute(
            f"""SELECT supplier_id, role, bill_rate, currency FROM rate_cards
                WHERE location_id = ? AND supplier_id IN ({placeholders})""",
            (location.location_id, *supplier_ids),
        ).fetchall()
    by_role: dict[str, list[tuple[float, str]]] = {}
    for row in rows:
        by_role.setdefault(str(row["role"]), []).append((float(row["bill_rate"]), str(row["currency"]).upper()))
    result: dict[str, tuple[float, str]] = {}
    for level, role in GOVERNED_LEVEL_ROLES.items():
        matches = by_role.get(role, [])
        currencies = {currency for _, currency in matches}
        if matches and len(currencies) == 1:
            result[level] = (round(sum(rate for rate, _ in matches) / len(matches), 2), next(iter(currencies)))
    return result


def validate_workforce_upload(request: UploadValidationRequest) -> dict[str, object]:
    """Validate the selected Proposal SOW before a recommendation is allowed."""
    upload = get_upload(request.upload_id)
    if upload is None or upload.get("scenario_id") != request.scenario_id or upload.get("source_id") != "excel":
        raise ValueError("The uploaded workbook does not belong to this analysis.")
    checks: list[dict[str, str]] = []
    def add(category: str, status: str, message: str) -> None:
        checks.append({"category": category, "status": status, "message": message})
    if upload.get("data_kind") != "proposal_workbook":
        add("Workbook", "critical", "Upload a Proposal workbook with SOW Reference, Delivery Countries, and E1-E5 columns.")
        return {"ready": False, "checks": checks, "selected_sow": None}
    if upload.get("cleaning_status") != "approved":
        add("Workbook review", "critical", "Review the uploaded workbook, resolve critical issues, and approve the reviewed values before validation.")
        return {"ready": False, "checks": checks, "selected_sow": None}
    from costopt.agents.data_cleaning import _header, select_source_country
    columns = {_header(column) for column in upload.get("preview_columns", [])}
    required = {"sow reference", "delivery countries", "e1", "e2", "e3", "e4", "e5"}
    missing = sorted(required - columns)
    add("Workbook structure", "pass" if not missing else "critical",
        "Required Proposal columns are present." if not missing else f"Missing required columns: {', '.join(missing)}.")
    source_filter = request.source_filter
    if source_filter is None or source_filter.column.strip().lower().replace("_", " ") != "sow reference":
        add("SOW scope", "critical", "Search for a SOW Reference in the workbook preview before continuing.")
        selected_projects: list[dict[str, object]] = []
    else:
        search_term = source_filter.contains.casefold()
        normalized_search = "".join(character for character in search_term if character.isalnum())
        selected_projects = [project for project in upload.get("projects", [])
                             if search_term in str(project.get("sow_reference", "")).casefold()
                             or (normalized_search and normalized_search in "".join(character for character in str(project.get("sow_reference", "")).casefold() if character.isalnum()))]
        add("SOW scope", "pass" if len(selected_projects) == 1 else "critical",
            f"Selected SOW: {selected_projects[0]['sow_reference']}." if len(selected_projects) == 1
            else "Refine the SOW search until it returns one SOW.")
    project = selected_projects[0] if len(selected_projects) == 1 else None
    if project:
        known_countries = {location.country for location in list_locations()}
        source_country = str(select_source_country(str(project.get("delivery_countries", "")))
                             or project.get("source_country") or "")
        valid_source = bool(source_country and source_country in known_countries)
        add("Source location", "pass" if valid_source else "critical",
            f"Governed calculation source: {source_country}. Delivery-country values remain unrestricted scope context." if valid_source
            else "The first delivery country must be configured as a governed source location.")
        levels = project.get("levels", {})
        worker_count = int(project.get("worker_count", 0) or 0)
        calculated_workers = sum(int(levels.get(level, 0) or 0) for level in ("E1", "E2", "E3", "E4", "E5"))
        add("Workforce levels", "pass" if worker_count > 0 and worker_count == calculated_workers else "critical",
            f"E1-E5 totals reconcile to {worker_count} worker(s)." if worker_count > 0 and worker_count == calculated_workers else "E1-E5 worker totals are missing or inconsistent.")
        required_levels = [level for level in ("E1", "E2", "E3", "E4", "E5") if int(levels.get(level, 0) or 0) > 0]
        location_names = {location.location_id: location.country for location in list_locations()}
        destinations = [location_names[location_id] for location_id in request.destination_country_ids if location_id in location_names]
        evidence = inspect_supporting_uploads(request.scenario_id, request.supporting_upload_ids,
                                              str(project.get("sow_reference")), destinations, required_levels,
                                              [source_country] if source_country else [])
        checks.extend(evidence["checks"])
        from costopt.agents.document_validation import DocumentValidationRequest, validate_documents
        report = validate_documents(DocumentValidationRequest(
            scenario_id=request.scenario_id, upload_id=request.upload_id,
            supporting_upload_ids=request.supporting_upload_ids,
            destination_country_ids=request.destination_country_ids, use_llm=False))
        selected = [item for item in report["sows"] if item["sow_reference"] == project.get("sow_reference")]
        if not selected or not all(item["ready"] for item in selected):
            add("Document validation", "critical", "Resolve the selected SOW's missing information and workbook-wide errors in Validate all documents before recommendation.")
    resources = [row for row in upload.get("rows", []) if not project or row.get("sow_reference") == project.get("sow_reference")]
    uploaded_rates = _uploaded_daily_rates(request.scenario_id, request.supporting_upload_ids)
    rate_currency = _uploaded_rate_currency(request.scenario_id, request.supporting_upload_ids) or "EUR"
    if rate_currency not in PLANNING_FX_TO_EUR:
        add("Rate currency", "critical", f"No governed planning FX rate is configured for {rate_currency}.")
    if project:
        sow_key = str(project.get("sow_reference", ""))
        source_key = source_country
        required_source_levels = {str(row.get("level", "")).upper() for row in resources}
        governed_source_rates = _governed_source_rates(request.scenario_id, source_key)
        missing_source_levels = sorted(level for level in required_source_levels
                                       if level not in governed_source_rates
                                       and _uploaded_rate(uploaded_rates, sow_key, source_key, level) is None)
    else:
        missing_source_levels = []
    source_rates_ready = bool(resources) and project is not None and not missing_source_levels
    add("Source rate cards", "pass" if source_rates_ready else "critical",
        f"Governed backend source rates are available for {len(required_source_levels)} required E-level(s)." if source_rates_ready
        else "The governed backend is missing a valid source-country rate for one or more required E-levels.")
    destination_names = [location_names[location_id] for location_id in request.destination_country_ids if location_id in location_names] if project else []
    missing_destination_rates = sorted(
        f"{country}/{level}" for country in destination_names for level in required_source_levels
        if _uploaded_rate(uploaded_rates, project.get("sow_reference", ""), country, level) is None
    ) if project else []
    add("Destination rate cards", "critical" if missing_destination_rates else "pass",
        f"Missing uploaded {rate_currency}/day destination rates: " + ", ".join(missing_destination_rates) + "."
        if missing_destination_rates else f"Uploaded {rate_currency}/day destination rates cover the selected countries and E-levels.")
    context = load_scenario_context(scenario_id=request.scenario_id)
    compliance = assess_contracts(context.contracts, context.clauses, target_is_offshore=True)
    contract_status = "critical" if compliance.outcome == "blocked" or not compliance.evidence_complete else "warning" if compliance.requires_human_review else "pass"
    add("Contractual constraints", contract_status,
        compliance.result.summary or "Contract evidence was checked.")
    if compliance.missing_evidence:
        add("Contract evidence", "critical", f"Missing clause evidence: {', '.join(compliance.missing_evidence)}.")
    if compliance.evidence_conflicts:
        add("Contract evidence", "critical", f"Conflicting clause evidence: {', '.join(compliance.evidence_conflicts)}.")
    if compliance.result.customer_approval_required:
        add("Customer approval", "warning", "Written customer approval is required before any country move.")
    package_summary_categories = {"Workbook structure", "Required documents", "SOW consistency", "Document validation"}
    checks = [check for check in checks if check["category"] not in package_summary_categories]
    return {"ready": not any(check["status"] == "critical" for check in checks), "checks": checks,
            "selected_sow": project.get("sow_reference") if project else None}


def consolidated_upload_preview(request: UploadValidationRequest) -> dict[str, object]:
    """Build the row-level inputs that the recommendation workflow will use."""
    upload = get_upload(request.upload_id)
    if upload is None or upload.get("scenario_id") != request.scenario_id or upload.get("source_id") != "excel":
        raise ValueError("The uploaded workbook does not belong to this analysis.")
    if upload.get("data_kind") != "proposal_workbook" or upload.get("cleaning_status") != "approved":
        raise ValueError("Approve the cleaned Proposal workbook before creating the consolidated preview.")
    validate_supporting_uploads(request.scenario_id, request.supporting_upload_ids)
    from costopt.agents.data_cleaning import _header, _number, _suggest, select_source_country
    from costopt.agents.document_validation import DocumentValidationRequest, validate_documents

    primary = [{_header(key): _suggest(_header(key), value) for key, value in row.items()}
               for row in upload.get("preview_rows", [])]
    supporting = [get_upload(identifier) for identifier in request.supporting_upload_ids]
    by_kind = {str(record.get("data_kind")): record for record in supporting if record}
    rates = by_kind.get("rate_card", {}).get("rows", [])
    uploaded_rates = _uploaded_daily_rates(request.scenario_id, request.supporting_upload_ids)
    rate_currency = _uploaded_rate_currency(request.scenario_id, request.supporting_upload_ids) or "EUR"
    source_currency = load_scenario_context(scenario_id=request.scenario_id).currency
    projects = {str(project.get("sow_reference", "")).casefold(): project for project in upload.get("projects", [])}
    location_names = {location.location_id: location.country for location in list_locations()}
    selected_destinations = [location_names[item] for item in request.destination_country_ids if item in location_names]
    report = validate_documents(DocumentValidationRequest(
        scenario_id=request.scenario_id, upload_id=request.upload_id,
        supporting_upload_ids=request.supporting_upload_ids,
        destination_country_ids=request.destination_country_ids, use_llm=False))
    sow_readiness = {str(item["sow_reference"]): bool(item["ready"]) for item in report["sows"]}
    evidence_labels = {
        "contractual_evidence": "Contract Evidence",
        "delivery_constraints": "Delivery Constraints",
    }
    rows: list[dict[str, object]] = []
    for source in primary:
        sow = str(source.get("sow reference", "")).strip()
        if not sow:
            continue
        delivery_scope = str(source.get("delivery countries", "")).strip()
        project = projects.get(sow.casefold(), {})
        source_country = str(select_source_country(delivery_scope) or project.get("source_country", ""))
        for level in ("e1", "e2", "e3", "e4", "e5"):
            try:
                headcount = int(_number(source.get(level, "")))
            except ValueError:
                headcount = 0
            if headcount <= 0:
                continue
            matching_rates = [row for row in rates if (not str(row.get("sow_reference", "")).strip()
                                                               or str(row.get("sow_reference", "")).casefold() == sow.casefold())
                              and str(row.get("level", "")).casefold() == level.casefold()]
            available_countries = sorted({str(row.get("country", "")).strip() for row in matching_rates
                                          if str(row.get("country", "")).strip()})
            governed_source = _governed_source_rates(request.scenario_id, source_country).get(level.upper())
            uploaded_source_rate = _uploaded_rate(uploaded_rates, sow, source_country, level)
            source_rate = (governed_source[0] if governed_source else
                           _convert_planning_rate(uploaded_source_rate, rate_currency, source_currency)
                           if uploaded_source_rate is not None else "Missing")
            candidates = selected_destinations or [country for country in available_countries
                                                    if country.casefold() != source_country.casefold()]
            if not candidates:
                candidates = ["Not selected"]
            evidence: dict[str, str] = {}
            for kind, label in evidence_labels.items():
                record = by_kind.get(kind)
                references = {str(value).casefold() for value in (record or {}).get("sow_references", [])}
                evidence[label] = "Available" if record and (not references or sow.casefold() in references) else "Missing"
            for destination in candidates:
                destination_rate = _uploaded_rate(uploaded_rates, sow, destination, level) or "Missing"
                ready = bool(sow_readiness.get(sow) and source_rate != "Missing" and destination_rate != "Missing"
                             and all(value == "Available" for value in evidence.values()))
                rows.append({
                    "SOW Reference": sow,
                    "E-Level": level.upper(),
                    "Headcount": headcount,
                    "SOW Delivery Scope": delivery_scope,
                    "Source Country": source_country,
                    f"Source Rate ({source_currency}/day)": source_rate,
                    "Destination Country": destination,
                    f"Destination Rate ({rate_currency}/day)": destination_rate,
                    **evidence,
                    "Recommendation Input": "Ready" if ready else "Needs attention",
                })
    columns = ["SOW Reference", "E-Level", "Headcount", "SOW Delivery Scope", "Source Country",
               f"Source Rate ({source_currency}/day)", "Destination Country", f"Destination Rate ({rate_currency}/day)",
               "Contract Evidence", "Delivery Constraints", "Recommendation Input"]
    return {"status": "consolidated", "ready": bool(rows) and all(row["Recommendation Input"] == "Ready" for row in rows),
            "row_count": len(rows), "columns": columns, "rows": rows,
            "sow_options": sorted(sow_readiness), "documents": report["documents"],
            "finding_groups": report["finding_groups"]}

CASE_NAMES = {
    "right_shoring": "Optimized shoring",
    "skill_based": "Skill-based optimized shoring",
    "multi_vendor": "Multi-vendor workforce consolidation",
    "timezone": "Time-zone coverage optimization",
    "capacity_gap": "Capacity gap forecasting",
}

# Standard local working-hour offsets are illustrative; daylight-saving and
# actual team rosters are not in the fixture and must be confirmed by a reviewer.
UTC_OFFSETS = {
    "loc-germany": 1, "loc-uk": 0, "loc-usa": -5, "loc-canada": -5,
    "loc-poland": 1, "loc-romania": 2, "loc-portugal": 0,
    "loc-india": 5.5, "loc-philippines": 8, "loc-vietnam": 7,
    "loc-mexico": -6, "loc-brazil": -3, "loc-south-africa": 2,
    "loc-egypt": 2, "loc-malaysia": 8, "loc-uae": 4,
    "loc-singapore": 8, "loc-australia": 10, "loc-ireland": 0,
    "loc-netherlands": 1,
}
EEA_COUNTRIES = {
    "Austria", "Belgium", "Bulgaria", "Croatia", "Cyprus", "Czech Republic",
    "Denmark", "Estonia", "Finland", "France", "Germany", "Greece",
    "Hungary", "Iceland", "Ireland", "Italy", "Latvia", "Liechtenstein",
    "Lithuania", "Luxembourg", "Malta", "Netherlands", "Norway", "Poland",
    "Portugal", "Romania", "Slovakia", "Slovenia", "Spain", "Sweden",
}


class CaseRequest(BaseModel):
    supporting_upload_ids: list[str] = Field(default_factory=list, max_length=3)
    case_id: CaseId
    scenario_id: str = Field(min_length=1)
    project_title: str | None = Field(default=None, max_length=160)
    source_location_id: str | None = None
    offshore_location_ids: list[str] = Field(default_factory=list, max_length=20)
    source_ids: list[SourceId] = Field(min_length=1)
    upload_id: str | None = None
    source_modes: dict[SourceId, Literal["auto", "manual"]] = Field(default_factory=dict)
    source_upload_ids: dict[SourceId, str] = Field(default_factory=dict)
    source_filters: dict[SourceId, SourceFilter] = Field(default_factory=dict)
    skill: str | None = None
    role: str | None = None
    max_suppliers: int | None = Field(default=None, ge=1, le=2)
    required_overlap_hours: float | None = Field(default=None, ge=0, le=8)
    demand_roles: int | None = Field(default=None, ge=1, le=1000)
    available_roles: int | None = Field(default=None, ge=0, le=1000)
    horizon_months: int | None = Field(default=None, ge=1, le=36)
    planned_downtime_hours: float | None = Field(default=None, ge=0, le=720)
    move_counts_by_level: dict[str, int] = Field(default_factory=dict)
    move_counts_by_sow_level: dict[str, int] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_case_inputs(self) -> "CaseRequest":
        required = {
            "skill_based": ("skill",),
            "multi_vendor": ("role", "max_suppliers"),
            "timezone": ("required_overlap_hours",),
            "capacity_gap": ("role", "demand_roles", "available_roles", "horizon_months"),
        }
        missing = [name for name in required.get(self.case_id, ()) if getattr(self, name) is None or getattr(self, name) == ""]
        if missing:
            raise ValueError(f"{self.case_id} requires: {', '.join(missing)}")
        if len(set(self.offshore_location_ids)) != len(self.offshore_location_ids):
            raise ValueError("Select each offshore location only once.")
        invalid_levels = set(self.move_counts_by_level) - {"E1", "E2", "E3", "E4", "E5"}
        if invalid_levels or any(value < 0 for value in self.move_counts_by_level.values()):
            raise ValueError("Move counts must be non-negative values for E1, E2, E3, E4 or E5.")
        if any(value < 0 for value in self.move_counts_by_sow_level.values()):
            raise ValueError("Move counts must be non-negative values.")
        return self


class CaseOption(BaseModel):
    option_id: str
    location_id: str
    location_name: str
    supplier_id: str | None = None
    supplier_name: str | None = None
    monthly_savings: float
    annual_savings: float
    period_savings: float | None = None
    period_label: str = "per year"
    moved_roles: int
    status: Literal["eligible", "indicative", "blocked"]
    summary: str
    rationale: str = ""
    confidence_score: float | None = None
    baseline_cost: float | None = None
    future_cost: float | None = None
    retained_roles: int | None = None
    coverage_hours: float | None = None
    timezone_difference_hours: float | None = None
    next_actions: list[str] = Field(default_factory=list)
    checks: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    resource_details: list[dict[str, object]] = Field(default_factory=list)
    agent_stages: list[dict[str, str]] = Field(default_factory=list)
    talent_levels: list[dict[str, object]] = Field(default_factory=list)
    talent_rows: list[dict[str, object]] = Field(default_factory=list)
    estimated_downtime_hours: float | None = None
    transition_duration_weeks: int | None = None
    knowledge_transfer_hours: float | None = None
    onboarding_hours: float | None = None
    downtime_justification: str = ""


class CaseAnalysis(BaseModel):
    analysis_id: str
    project_title: str = ""
    case_id: CaseId
    case_name: str
    scenario_id: str
    squad_name: str
    created_at: str
    input: CaseRequest
    sources: list[dict[str, object]]
    options: list[CaseOption]
    recommendation: str
    recommended_option_id: str | None = None
    decision_status: Literal["recommendation", "insufficient_evidence"] = "recommendation"
    blocking_reasons: list[str] = Field(default_factory=list)
    locations_evaluated: int = 0
    human_review_required: bool = True
    data_gaps: list[str] = Field(default_factory=list)


class ImplicationSummary(BaseModel):
    operations: str = Field(default="", max_length=3000)
    talent: str = Field(default="", max_length=3000)
    compliance: str = Field(default="", max_length=3000)
    regulatory: str = Field(default="", max_length=3000)


class ReviewRequest(BaseModel):
    reviewer_name: str = Field(min_length=2, max_length=120)
    decision: ReviewDecision
    selected_option_id: str | None = None
    calculation_summary: str = Field(default="", max_length=3000)
    implication_summary: ImplicationSummary = Field(default_factory=ImplicationSummary)
    edited_recommendation: str = Field(min_length=10, max_length=3000)
    rationale: str = Field(min_length=10, max_length=3000)
    downtime_hours: float | None = Field(default=None, ge=0, le=720)


class AnalysisTitleUpdate(BaseModel):
    project_title: str = Field(min_length=3, max_length=160)


def list_cases() -> list[dict[str, str]]:
    return [{"case_id": "right_shoring", "name": CASE_NAMES["right_shoring"]}]


def case_context(scenario_id: str) -> dict[str, object]:
    context = load_scenario_context(scenario_id=scenario_id)
    location_names = {location.location_id: location.country for location in list_locations()}
    return {
        "scenario_id": context.scenario_id,
        "squad_name": context.squad.name,
        "current_location_ids": context.current_location_ids,
        "source_locations": [
            {"location_id": location_id, "country": location_names.get(location_id, location_id),
             "resource_count": sum(resource.current_location_id == location_id for resource in context.resources)}
            for location_id in context.current_location_ids
        ],
        "skills": sorted({r.skill for r in context.resources}),
        "roles": sorted({r.role for r in context.resources}),
        "suppliers": sorted({r.supplier_id for r in context.resources}),
        "resource_count": len(context.resources),
        "offshore_locations": [
            {"location_id": loc.location_id, "country": loc.country}
            for loc in list_locations() if loc.is_offshore
        ],
    }


def source_preview(source: SourceId, scenario_id: str | None = None, upload_id: str | None = None) -> dict[str, object]:
    """Expose bounded, non-PII local samples and their provenance."""
    if scenario_id:
        context = load_scenario_context(scenario_id=scenario_id)
        if upload_id:
            upload = get_upload(upload_id)
            if upload is None or upload["scenario_id"] != scenario_id or upload.get("source_id", "excel") != source:
                raise ValueError("The uploaded file does not belong to this source and team.")
            return {"source_id": source, "label": ("Proposal workbook · Germany workforce" if upload.get("data_kind") == "proposal_workbook"
                                                    else "Custom SOW overview" if upload.get("data_kind") == "sow_overview"
                                                    else "Custom Excel / CSV evidence" if upload.get("data_kind") == "freeform_evidence"
                                                    else f"Uploaded {source.title()} template"), "status": "uploaded",
                    "origin": upload["filename"], "live_connected": False,
                    "row_count": upload["matched_count"], "file_row_count": upload["row_count"],
                    "ignored_count": upload["ignored_count"], "team_resource_count": len(context.resources),
                    "columns": upload.get("preview_columns", upload["columns"]),
                    "rows": upload.get("preview_rows", upload["rows"]),
                    "analysis_role": upload["analysis_role"]}
        if source == "fieldglass":
            rows = [{"resource_id": resource.resource_id, "role": resource.role,
                     "skill": resource.skill, "location": resource.current_location_id,
                     "supplier_id": resource.supplier_id, "current_rate_eur": resource.current_rate}
                    for resource in context.resources]
            return {"source_id": source, "label": "Fieldglass-style workforce mock", "status": "team_mock",
                    "origin": "CostOpt local workforce table (synthetic)", "live_connected": False,
                    "row_count": len(rows), "team_resource_count": len(rows),
                    "columns": list(rows[0]) if rows else [], "rows": rows,
                    "analysis_role": "These team workforce rows are the canonical local baseline used by the agent; no live Fieldglass connection."}
        if source == "ariba":
            rows = [{"contract_id": contract.contract_id, "supplier_id": contract.supplier_id,
                     "contract_type": contract.contract_type, "offshore_permitted": contract.offshore_permitted,
                     "data_residency_restriction": contract.data_residency_restriction or "None",
                     "customer_approval_required": contract.customer_approval_required}
                    for contract in context.contracts]
            return {"source_id": source, "label": "Ariba-style contract mock", "status": "team_mock",
                    "origin": "CostOpt local contract table (synthetic)", "live_connected": False,
                    "row_count": len(rows), "team_resource_count": len(context.resources),
                    "columns": list(rows[0]) if rows else [], "rows": rows,
                    "analysis_role": "These supplier contracts are the canonical local policy inputs used by the agent; no live Ariba connection."}
    if source == "excel":
        path = settings.data_dir / "source_samples" / "excel" / "workforce_extract.csv"
        with path.open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        if scenario_id:
            rows = [row for row in rows if row.get("scenario_id") == scenario_id]
        return {"source_id": source, "label": "Excel / CSV extract", "status": "synthetic_fixture",
                "origin": "local workforce_extract.csv", "live_connected": False,
                "row_count": len(rows), "team_resource_count": len(context.resources) if scenario_id else None,
                "columns": list(rows[0]) if rows else [], "rows": rows[:20],
                "analysis_role": "This bundled file is a partial sample. Canonical team workforce rows drive calculations unless you upload a matching CSV/XLSX file."}
    with get_connection() as connection:
        if source == "fieldglass":
            try:
                rows = connection.execute("SELECT source_worker_id, worker_role, country, data_origin FROM sap_fieldglass_workers LIMIT 8").fetchall()
                count = connection.execute("SELECT COUNT(*) AS n FROM sap_fieldglass_workers").fetchone()["n"]
            except sqlite3.OperationalError:
                rows, count = [], 0
            columns = ["source_worker_id", "worker_role", "country", "data_origin"]
        else:
            try:
                rows = connection.execute("SELECT source_contract_id, title, contract_status, currency, data_origin FROM sap_ariba_contract_workspaces LIMIT 8").fetchall()
                count = connection.execute("SELECT COUNT(*) AS n FROM sap_ariba_contract_workspaces").fetchone()["n"]
            except sqlite3.OperationalError:
                rows, count = [], 0
            columns = ["source_contract_id", "title", "contract_status", "currency", "data_origin"]
    if count:
        return {"source_id": source, "label": source.title(), "status": "local_staging",
                "origin": "sanitized/imported staging", "live_connected": False,
                "row_count": count, "columns": columns, "rows": rows,
                "analysis_role": "Preview and lineage; canonical workforce tables drive calculations."}
    # The captured response is shown only as a sample, never as an analysis row.
    sample = (settings.data_dir / "source_samples" / "sap" /
              ("fieldglass/worker/response.sample.json" if source == "fieldglass" else "ariba/contract_workspace/response.sample.json"))
    payload = json.loads(sample.read_text(encoding="utf-8"))
    if source == "fieldglass":
        preview_rows = [{"worker_role": payload.get("role"), "country": payload.get("country"), "source_worker_id": payload.get("username")}]
    else:
        preview_rows = [{"source_contract_id": row.get("contractId"), "title": row.get("title"), "contract_status": row.get("contractStatus")}
                        for row in payload.get("value", [])[:5]]
    return {"source_id": source, "label": source.title(), "status": "sample_only",
            "origin": str(sample.relative_to(settings.data_dir)), "live_connected": False,
            "row_count": 0, "columns": list(preview_rows[0]) if preview_rows else [], "rows": preview_rows,
            "analysis_role": "Illustrative sample only; not used in calculations."}


def analyze_case(request: CaseRequest) -> CaseAnalysis:
    validate_supporting_uploads(request.scenario_id, request.supporting_upload_ids)
    if not request.offshore_location_ids:
        raise ValueError("Select at least one country before running the analysis.")
    context = load_scenario_context(scenario_id=request.scenario_id)
    baseline_resources = {resource.resource_id: resource for resource in context.resources}
    location_countries = {location.location_id: location.country for location in list_locations()}
    uploaded_rates = _uploaded_daily_rates(request.scenario_id, request.supporting_upload_ids)
    uploaded_currency = _uploaded_rate_currency(request.scenario_id, request.supporting_upload_ids)
    upload_ids = dict(request.source_upload_ids)
    if request.upload_id:
        upload_ids.setdefault("excel", request.upload_id)
    selected_uploads = {}
    for source in request.source_ids:
        mode = request.source_modes.get(source, "manual" if source in upload_ids else "auto")
        if source == "excel" and mode != "manual":
            raise ValueError("Excel / CSV requires an uploaded file; it cannot use the demo workforce.")
        if mode == "manual":
            upload_id = upload_ids.get(source)
            upload = get_upload(upload_id) if upload_id else None
            if upload is None or upload["scenario_id"] != request.scenario_id or upload.get("source_id", "excel") != source:
                raise ValueError(f"Upload the {source.title()} template for the selected team before running analysis.")
            if source == "excel" and upload.get("data_kind") == "proposal_workbook" and upload.get("cleaning_status") != "approved":
                raise ValueError("Data cleaning approval is required before recommendation.")
            selected_uploads[source] = upload
    # Build the working population exclusively from selected workforce sources.
    # The seeded scenario supplies governed reference attributes for matching IDs,
    # but never contributes unselected workforce rows.
    selected_resources = {}
    source_resource_ids: dict[str, set[str]] = {source: set() for source in request.source_ids}
    if "fieldglass" in request.source_ids and "fieldglass" not in selected_uploads:
        selected_resources.update(baseline_resources)
        source_resource_ids["fieldglass"].update(baseline_resources)
    for source in ("excel", "fieldglass"):
        upload = selected_uploads.get(source)
        if not upload or upload.get("data_kind") in {"sow_overview", "freeform_evidence"}:
            continue
        if upload.get("data_kind") == "proposal_workbook":
            for row in upload["rows"]:
                resource_row = dict(row)
                if float(resource_row.get("current_rate_eur", 0) or 0) <= 0:
                    source_country = location_countries.get(str(resource_row.get("current_location_id", "")), "")
                    governed_rate = _governed_source_rates(request.scenario_id, source_country).get(
                        str(resource_row.get("level", "")).upper()
                    )
                    if governed_rate:
                        resource_row["current_rate"] = governed_rate[0]
                        resource_row["current_rate_eur"] = governed_rate[0]
                    else:
                        uploaded_rate = _uploaded_rate(
                            uploaded_rates, resource_row.get("sow_reference", ""), source_country,
                            resource_row.get("level", ""),
                        )
                        if uploaded_rate is not None:
                            converted_rate = _convert_planning_rate(uploaded_rate, uploaded_currency or context.currency, context.currency)
                            resource_row["current_rate"] = converted_rate
                            resource_row["current_rate_eur"] = converted_rate
                resource = Resource.model_validate(resource_row)
                source_resource_ids[source].add(resource.resource_id)
                selected_resources[resource.resource_id] = resource
            continue
        for row in upload["rows"]:
            original = baseline_resources.get(row.get("resource_id"))
            if original is None:
                continue
            source_resource_ids[source].add(original.resource_id)
            selected_resources[original.resource_id] = original.model_copy(update={
                "current_location_id": row.get("current_location_id") or request.source_location_id or original.current_location_id,
                **({"current_rate": float(row["current_rate_eur"])} if row.get("current_rate_eur") else {}),
                **({"role": row["role"]} if row.get("role") else {}),
                **({"skill": row["skill"]} if row.get("skill") else {}),
                **({"availability": row["availability"]} if source == "fieldglass" and row.get("availability") else {}),
            })
    context.resources = list(selected_resources.values())
    if request.source_location_id:
        context.resources = [resource for resource in context.resources
                             if resource.current_location_id == request.source_location_id]
        if not context.resources:
            raise ValueError("The selected source country has no workforce rows in the chosen data source.")
        context.current_location_ids = [request.source_location_id]
    else:
        context.current_location_ids = sorted({resource.current_location_id for resource in context.resources})
    for source, filter_spec in request.source_filters.items():
        upload = selected_uploads.get(source)
        if (source not in {"excel", "fieldglass"} or upload is None
                or upload.get("data_kind") in {"sow_overview", "freeform_evidence"}
                or "resource_id" not in upload["columns"]):
            raise ValueError("Analysis filtering requires an uploaded workforce file with matched resource IDs.")
        resource_column = filter_spec.column.strip().lower().replace(" ", "_")
        if filter_spec.column not in upload.get("preview_columns", upload["columns"]) and resource_column not in upload["columns"]:
            raise ValueError(f"The {source} upload has no {filter_spec.column} column.")
        search_term = filter_spec.contains.casefold()
        normalized_search = "".join(character for character in search_term if character.isalnum())
        matching_ids = {
            row["resource_id"] for row in upload["rows"]
            if search_term in str(row.get(resource_column, row.get(filter_spec.column, ""))).casefold()
            or (normalized_search and normalized_search in "".join(character for character in str(row.get(resource_column, row.get(filter_spec.column, ""))).casefold() if character.isalnum()))
        }
        if not matching_ids:
            raise ValueError("The analysis filter has no matching workforce rows.")
        context.resources = [resource for resource in context.resources if resource.resource_id in matching_ids]
        if not context.resources:
            raise ValueError("The analysis filter has no resources in the selected source country.")
    # Source locations must describe the filtered SOW population, not every
    # country that happened to appear elsewhere in the uploaded workbook.
    # Otherwise an India row in another SOW incorrectly prevents a selected
    # Germany SOW from evaluating India as its destination.
    context.current_location_ids = sorted({resource.current_location_id for resource in context.resources})
    proposal_upload = selected_uploads.get("excel")
    if proposal_upload and proposal_upload.get("data_kind") == "proposal_workbook":
        validation = validate_workforce_upload(UploadValidationRequest(
            scenario_id=request.scenario_id, upload_id=str(proposal_upload["upload_id"]),
            source_filter=request.source_filters.get("excel"),
            supporting_upload_ids=request.supporting_upload_ids,
            destination_country_ids=request.offshore_location_ids,
        ))
        if not validation["ready"]:
            critical = [check["message"] for check in validation["checks"] if check["status"] == "critical"]
            raise ValueError(f"Data validation must be resolved before recommendation: {' '.join(critical)}")
    ariba_upload = selected_uploads.get("ariba")
    if ariba_upload:
        restrictions = {row["contract_id"]: row for row in ariba_upload["rows"]}
        context.contracts = [contract.model_copy(update={
            "offshore_permitted": contract.offshore_permitted and restrictions[contract.contract_id]["offshore_permitted"].upper() == "TRUE",
            "customer_approval_required": contract.customer_approval_required or restrictions[contract.contract_id]["customer_approval_required"].upper() == "TRUE",
            "data_residency_restriction": contract.data_residency_restriction or restrictions[contract.contract_id]["data_residency_restriction"] or None,
        }) if contract.contract_id in restrictions else contract for contract in context.contracts]
    locations = {loc.location_id: loc for loc in list_locations()}
    requested_candidate_ids = request.offshore_location_ids
    for loc_id in requested_candidate_ids:
        if loc_id not in locations or not locations[loc_id].is_offshore:
            raise ValueError(f"Select a valid offshore location: {loc_id}")
    candidate_ids = [loc_id for loc_id in requested_candidate_ids if loc_id not in context.current_location_ids]
    if not candidate_ids:
        raise ValueError("The destination country must differ from the selected SOW's source country.")
    if request.skill and request.skill not in {r.skill for r in context.resources}:
        raise ValueError("Selected skill is not present in this team.")
    sources = [source_preview(source, request.scenario_id, selected_uploads[source]["upload_id"] if source in selected_uploads else None)
               for source in request.source_ids]
    active_resource_ids = {resource.resource_id for resource in context.resources}
    for source in sources:
        source_id = source["source_id"]
        source["workforce_rows_used"] = len(source_resource_ids.get(source_id, set()) & active_resource_ids)
        upload = selected_uploads.get(source_id)
        if upload and upload.get("cleaning_status") == "approved":
            source["cleaning"] = {key: upload.get(key) for key in ("upload_id", "original_upload_id", "cleaning_run_id", "approved_by", "file_sha256")}
        source["evidence_rows_used"] = (upload["row_count"] if upload and upload.get("data_kind") in
                                        {"sow_overview", "freeform_evidence"} else 0)
    gaps = [f"{source['label']} has sample data only; it is not a live analysis feed."
            for source in sources if source["status"] == "sample_only"]
    if uploaded_currency and uploaded_currency != context.currency:
        gaps.append(
            f"Uploaded {uploaded_currency}/day destination rates were converted to {context.currency} "
            f"with the governed planning FX assumption: 1 {uploaded_currency} = "
            f"{PLANNING_FX_TO_EUR[uploaded_currency] / PLANNING_FX_TO_EUR[context.currency]:.4g} {context.currency}."
        )
    for source, filter_spec in request.source_filters.items():
        gaps.append(
            f"{source.title()} workforce filter applied: {filter_spec.column} contains "
            f"'{filter_spec.contains}'. The agent analysed {len(context.resources)} matched resource(s)."
        )
    sow_upload = next((upload for upload in selected_uploads.values()
                       if upload.get("data_kind") == "sow_overview"), None)
    if sow_upload:
        gaps.append(f"Custom SOW workbook contains {sow_upload['row_count']} anonymised SOWs and "
                    f"{sow_upload['worker_count']} worker references. It has no validated rates or "
                    "CostOpt resource IDs, so modeled savings still use the local workforce baseline.")
    freeform_upload = next((upload for upload in selected_uploads.values()
                            if upload.get("data_kind") == "freeform_evidence"), None)
    if freeform_upload:
        gaps.append(f"Custom {freeform_upload['filename']} contains {freeform_upload['row_count']} rows. "
                    "Its columns are profiled as reference evidence; unmatched rows do not change modeled savings or eligibility.")
    if "excel" in selected_uploads and "fieldglass" in selected_uploads:
        gaps.append("Fieldglass manual workforce values take precedence over Excel manual values for matching resource IDs.")
    if not context.resources:
        reason = ("The selected upload has no resource-level workforce rows for the chosen source country. "
                  "SOW and free-form evidence cannot be turned into a verified project roster or rates. "
                  "Upload workforce rows with matching resource IDs, or select Fieldglass backend data explicitly.")
        source_country = locations[request.source_location_id].country if request.source_location_id in locations else None
        destination_countries = [locations[loc_id].country for loc_id in candidate_ids]
        default_title = (f"Optimized shoring: {source_country} to "
                         f"{destination_countries[0] if len(destination_countries) == 1 else 'selected countries'}"
                         if source_country else "Optimized shoring")
        analysis = CaseAnalysis(
            analysis_id=str(uuid4()), case_id=request.case_id, case_name=CASE_NAMES[request.case_id],
            project_title=(request.project_title or default_title).strip(), scenario_id=request.scenario_id,
            squad_name=context.squad.name, created_at=datetime.now(UTC).isoformat(), input=request,
            sources=sources, options=[], recommendation=f"No recommendation: {reason}",
            decision_status="insufficient_evidence", blocking_reasons=[reason],
            locations_evaluated=0, data_gaps=[*gaps, reason],
        )
        _save_analysis(analysis)
        return analysis
    options = []
    for loc_id in candidate_ids:
        location_context = load_scenario_context(scenario_id=request.scenario_id, target_location_id=loc_id)
        location_context.currency = context.currency
        if selected_uploads or request.source_location_id:
            location_context.resources = context.resources
            location_context.contracts = context.contracts
            location_context.current_location_ids = context.current_location_ids
        if any(upload.get("data_kind") == "proposal_workbook" for upload in selected_uploads.values()):
            proposal_rows = next(upload["rows"] for upload in selected_uploads.values()
                                 if upload.get("data_kind") == "proposal_workbook")
            proposal_by_resource = {str(row.get("resource_id")): row for row in proposal_rows}
            target_country = locations[loc_id].country
            target_cards = []
            for resource in context.resources:
                source_row = proposal_by_resource.get(resource.resource_id, {})
                uploaded_rate = _uploaded_rate(uploaded_rates, source_row.get("sow_reference", ""),
                                               target_country, source_row.get("level", resource.skill))
                if uploaded_rate is not None:
                    converted_rate = _convert_planning_rate(
                        uploaded_rate, uploaded_currency or context.currency, context.currency
                    )
                    target_cards.append(
                        RateCard(rate_card_id=f"uploaded-{resource.resource_id}-{loc_id}",
                                 supplier_id=resource.supplier_id, location_id=loc_id, role=resource.role,
                                 bill_rate=converted_rate, currency=context.currency)
                    )
            location_context.rate_cards = [
                RateCard(rate_card_id=f"generated-{resource.resource_id}-{resource.current_location_id}",
                         supplier_id=resource.supplier_id, location_id=resource.current_location_id, role=resource.role,
                         bill_rate=resource.current_rate, currency=context.currency)
                for resource in context.resources
            ] + target_cards
        graph_state = run_workforce_graph(
            ScenarioAnalysisRequest(scenario_id=request.scenario_id, target_location_id=loc_id),
            context_override=location_context,
        )
        result = graph_state["recommendation"]
        option = _workforce_option(context, request, locations[loc_id], result)
        option.agent_stages = [
                {"name": stage.name, "outcome": stage.outcome,
                 "mode": "fallback" if stage.used_fallback else "llm"}
                for stage in graph_state["stages"]
            ]
        if any(locations.get(resource.current_location_id) and
               locations[resource.current_location_id].country in EEA_COUNTRIES and resource.pii_access
               for resource in context.resources) and locations[loc_id].country not in EEA_COUNTRIES:
            option.gaps.append("GDPR international-transfer review is required for EU/EEA personal-data access; the transfer mechanism and safeguards are not verified here.")
            option.next_actions.append("Have privacy/legal confirm the applicable transfer mechanism, access controls and data-residency obligations.")
            if option.status == "eligible":
                option.status = "indicative"
        option.gaps.append(f"Local privacy, employment and sector-specific requirements for {locations[loc_id].country} are not verified by this MVP.")
        if sow_upload:
            count = sow_upload["country_counts"].get(locations[loc_id].country, 0)
            option.checks.append(f"Custom SOW evidence: {count} worker reference(s) list "
                                 f"{locations[loc_id].country} as a delivery location.")
            option.gaps.append("The custom SOW population is anonymised and is not linked to this CostOpt team's resource IDs; confirm applicability before action.")
        if freeform_upload:
            count = freeform_upload["country_counts"].get(locations[loc_id].country)
            option.checks.append(f"Custom file evidence: {count} row(s) list {locations[loc_id].country} as a location."
                                 if count is not None else
                                 f"Custom file has no rows explicitly tagged to {locations[loc_id].country}; verify the location mapping.")
            top_roles = sorted(freeform_upload["role_counts"].items(), key=lambda item: (-item[1], item[0]))[:3]
            if top_roles:
                option.checks.append("Custom file role profile: " + ", ".join(
                    f"{role} ({count})" for role, count in top_roles) + ".")
        options.append(option)
    # Eligibility outranks an unverified saving; among equally governed options,
    # prefer the larger benefit and then a stable country name.
    priority = {"eligible": 0, "indicative": 1, "blocked": 2}
    options.sort(key=lambda item: (priority[item.status],
                                   -(item.coverage_hours or 0) if request.case_id == "timezone" else 0,
                                   -item.annual_savings, item.location_name))
    blocking_reasons: list[str] = []
    proposal_upload = next((upload for upload in selected_uploads.values()
                            if upload.get("data_kind") == "proposal_workbook"), None)
    if request.case_id == "right_shoring" and not proposal_upload:
        blocking_reasons = [
            "Destination skill availability and hiring capacity are not verified.",
            "Country-specific privacy, employment and regulatory requirements are not verified.",
        ]
        if not any(upload.get("data_kind") not in {"sow_overview", "freeform_evidence"}
                   for upload in selected_uploads.values()):
            blocking_reasons.insert(0, "The project workforce is a local sample, not a verified project roster.")
        if sow_upload:
            blocking_reasons.append("SOW worker references cannot be linked to the modeled project resources.")
        if any("GDPR international-transfer review" in gap for item in options for gap in item.gaps):
            blocking_reasons.append("GDPR transfer safeguards and approvals are not verified.")
        for item in options:
            if item.status == "eligible":
                item.status = "indicative"
            if item.status != "blocked":
                item.gaps.extend(reason for reason in blocking_reasons if reason not in item.gaps)
    best = next((item for item in options if item.status != "blocked"), None) if not blocking_reasons else None
    options = options[:3]
    recommendation = (
        f"Recommend {best.location_name} for {context.squad.name} as the leading {CASE_NAMES[request.case_id].lower()} option. "
        f"It is {best.status}, covers {best.moved_roles} role(s), and has estimated savings of "
        f"{context.currency} {best.monthly_savings:,.0f} per month / {context.currency} {best.annual_savings:,.0f} per year. "
        f"{best.summary} {best.rationale} "
        f"Before any action: {'; '.join(best.next_actions or best.gaps or ['complete human review'])}."
        if best else ("No destination recommendation: critical evidence is missing. The displayed role moves and savings are scenario estimates only. "
                      + " ".join(blocking_reasons) if blocking_reasons else
                      "No offshore location met the screening criteria. Review the blocked options and data gaps before changing the project location.")
    )
    if sow_upload and best:
        country_workers = sow_upload["country_counts"].get(best.location_name, 0)
        recommendation += (f" The custom SOW workbook lists {country_workers} worker reference(s) in "
                           f"{best.location_name}; this is supporting delivery-location evidence only, "
                           "not a change to the savings estimate.")
    if freeform_upload and best:
        recommendation += (f" The uploaded {freeform_upload['filename']} adds {freeform_upload['row_count']} "
                           "reference row(s); its unmatched fields did not change the financial estimate.")
    source_country = locations.get(request.source_location_id).country if request.source_location_id in locations else None
    destination_countries = [locations[loc_id].country for loc_id in candidate_ids if loc_id in locations]
    default_title = (f"Optimized shoring: {source_country} to "
                     f"{destination_countries[0] if len(destination_countries) == 1 else 'selected countries'}"
                     if source_country and destination_countries else "Optimized shoring")
    analysis = CaseAnalysis(
        analysis_id=str(uuid4()), case_id=request.case_id, case_name=CASE_NAMES[request.case_id],
        project_title=(request.project_title or default_title).strip(),
        scenario_id=request.scenario_id, squad_name=context.squad.name,
        created_at=datetime.now(UTC).isoformat(), input=request, sources=sources,
        options=options, recommendation=recommendation,
        recommended_option_id=best.option_id if best else None,
        decision_status="insufficient_evidence" if blocking_reasons else "recommendation",
        blocking_reasons=blocking_reasons,
        locations_evaluated=len(candidate_ids), data_gaps=gaps,
    )
    _save_analysis(analysis)
    return analysis


def _workforce_option(context, request, location, result) -> CaseOption:
    decisions = result.resource_decisions
    requested_counts = request.move_counts_by_level
    requested_sow_counts = request.move_counts_by_sow_level
    if requested_counts or requested_sow_counts:
        remaining = dict(requested_counts)
        remaining_sow = dict(requested_sow_counts)
        effective_decisions = []
        for decision in sorted(decisions, key=lambda item: (item.role, item.skill, -(item.current_rate - item.projected_rate), item.resource_id)):
            sow_reference = decision.role.rsplit("-", 1)[0]
            row_key = f"{sow_reference}|{decision.skill}"
            requested = remaining_sow.get(row_key) if requested_sow_counts else remaining.get(decision.skill)
            if decision.action == "move" and (requested or 0) > 0:
                if requested_sow_counts:
                    remaining_sow[row_key] -= 1
                else:
                    remaining[decision.skill] -= 1
                effective_decisions.append(decision)
            elif decision.action == "move":
                effective_decisions.append(decision.model_copy(update={"action": "retain", "target_location_id": None,
                                                                       "projected_rate": decision.current_rate,
                                                                       "reason": "Retained because the reviewer-selected level quantity has been reached."}))
            else:
                effective_decisions.append(decision)
        decisions = effective_decisions
    checks = [result.compliance.summary]
    gaps = list(result.data_quality_issues)
    moved = [d for d in decisions if d.action == "move"]
    savings = round(sum((decision.current_rate - decision.projected_rate) * context.billing_units_per_month
                        for decision in moved), 2)
    status: Literal["eligible", "indicative", "blocked"] = "eligible" if moved and savings > 0 else "blocked"
    summary = result.recommendation
    current_offset = UTC_OFFSETS.get(context.current_location_id)
    target_offset = UTC_OFFSETS.get(location.location_id)
    timezone_difference_hours = abs(current_offset - target_offset) if current_offset is not None and target_offset is not None else None
    coverage_hours = max(0.0, 8.0 - timezone_difference_hours) if timezone_difference_hours is not None else None
    if request.case_id == "skill_based":
        moved = [d for d in moved if d.skill == request.skill]
        savings = round(sum((d.current_rate - d.projected_rate) * context.billing_units_per_month for d in moved), 2)
        status = "eligible" if moved and savings > 0 else "blocked"
        summary = (f"Move {len(moved)} eligible {request.skill} role(s); retain the other skills."
                   if moved else f"No {request.skill} roles are eligible at this location.")
        checks.append(f"Skill filter: {request.skill}")
    if request.case_id == "timezone":
        if current_offset is None or target_offset is None:
            status = "blocked"
            gaps.append("Time-zone offset is unavailable for the current or target location.")
        else:
            overlap = coverage_hours or 0.0
            checks.append(f"Illustrative 09:00–17:00 overlap: {overlap:g} hours (standard UTC offsets).")
            if overlap < (request.required_overlap_hours or 0):
                status = "blocked"
                summary = f"Only {overlap:g} hours of estimated overlap; below the requested minimum."
            else:
                status = "indicative" if status == "eligible" else status
                summary = f"Estimated {overlap:g} business-hour overlap; {len(moved)} eligible role(s)."
            gaps.append("Actual schedules, demand by hour, overtime and daylight-saving changes are unavailable.")
    resource_details = []
    if request.case_id == "right_shoring":
        resources = {resource.resource_id: resource for resource in context.resources}
        resource_details = [{
            "resource_id": decision.resource_id,
            "sow_reference": decision.role.rsplit("-", 1)[0] if decision.skill in {"E1", "E2", "E3", "E4", "E5"} else decision.resource_id,
            "role": decision.role,
            "level": decision.skill,
            "supplier_id": decision.supplier_id,
            "current_location_id": decision.current_location_id,
            "current_rate_eur": decision.current_rate,
            "projected_rate_eur": decision.projected_rate,
            "availability": resources[decision.resource_id].availability or "active",
            "pii_access": resources[decision.resource_id].pii_access,
            "action": decision.action,
            "reason": decision.reason,
        } for decision in decisions]
        if request.planned_downtime_hours is not None:
            checks.append(f"Previously captured cutover downtime estimate: {request.planned_downtime_hours:g} hour(s); not included in savings.")
    level_counts = []
    for level in ("E1", "E2", "E3", "E4", "E5"):
        eligible = [decision for decision in decisions if decision.skill == level and decision.current_rate > decision.projected_rate]
        level_counts.append({"level": level, "available": len(eligible), "selected": len([decision for decision in moved if decision.skill == level])})
    talent_rows = []
    for sow_reference, level in sorted({(detail["sow_reference"], detail["level"]) for detail in resource_details}):
        eligible = [decision for decision in decisions if decision.role.rsplit("-", 1)[0] == sow_reference
                    and decision.skill == level and decision.current_rate > decision.projected_rate]
        selected = [decision for decision in moved if decision.role.rsplit("-", 1)[0] == sow_reference and decision.skill == level]
        if eligible:
            talent_rows.append({"key": f"{sow_reference}|{level}", "sow_reference": sow_reference, "level": level,
                                "available": len(eligible), "selected": len(selected),
                                "current_rate_eur": eligible[0].current_rate,
                                "projected_rate_eur": eligible[0].projected_rate})
    future_cost = round(result.costs.baseline_cost - savings, 2)
    downtime = _estimate_downtime(moved)
    return CaseOption(option_id=str(uuid4()), location_id=location.location_id,
                      location_name=location.country, monthly_savings=max(0, round(savings, 2)) if status != "blocked" else 0,
                      annual_savings=max(0, round(savings * 12, 2)) if status != "blocked" else 0,
                      moved_roles=len(moved) if status != "blocked" else 0, status=status,
                      summary=summary, checks=checks, gaps=gaps, resource_details=resource_details,
                      rationale=result.rationale, confidence_score=result.confidence_score,
                      baseline_cost=result.costs.baseline_cost, future_cost=future_cost,
                      retained_roles=len(decisions) - len(moved), talent_levels=level_counts, talent_rows=talent_rows,
                      estimated_downtime_hours=downtime["downtime_hours"],
                      transition_duration_weeks=downtime["transition_weeks"],
                      knowledge_transfer_hours=downtime["knowledge_transfer_hours"],
                      onboarding_hours=downtime["onboarding_hours"],
                      downtime_justification=downtime["justification"],
                      coverage_hours=coverage_hours,
                      timezone_difference_hours=timezone_difference_hours,
                      next_actions=(["Obtain written customer approval where required."] if result.compliance.customer_approval_required else [])
                      + ["Validate the role plan, rate card and any missing data with the project owner."],)


def _estimate_downtime(moved: list[object]) -> dict[str, object]:
    """Provide a transparent, conservative planning estimate—not a delivery commitment."""
    moved_count = len(moved)
    sow_count = len({decision.role.rsplit("-", 1)[0] for decision in moved})
    transition_weeks = max(1, ceil(moved_count / 35)) if moved_count else 0
    knowledge_transfer_hours = round(moved_count * 6.0, 1)
    onboarding_hours = round(moved_count * 4.0, 1)
    # Knowledge transfer and onboarding are planned in parallel before the change
    # window. Downtime measures only the controlled cutover and validation window.
    downtime_hours = round(min(16.0, 2.0 + sow_count * 0.25 + moved_count * 0.10), 1) if moved_count else 0.0
    return {
        "downtime_hours": downtime_hours,
        "transition_weeks": transition_weeks,
        "knowledge_transfer_hours": knowledge_transfer_hours,
        "onboarding_hours": onboarding_hours,
        "justification": (
            f"Estimated {downtime_hours:g} hours for a controlled cutover and service validation across "
            f"{sow_count} SOW(s) / {moved_count} moved resource(s). It includes a 2-hour base window, "
            "15 minutes per SOW for release coordination, and 6 minutes per moved resource for handover validation. "
            f"Knowledge transfer ({knowledge_transfer_hours:g} hours) and onboarding ({onboarding_hours:g} hours) are "
            f"planned as parallel transition effort over approximately {transition_weeks} week(s), so they are not counted as service downtime."
        ),
    }


def _ensure_tables(connection) -> None:
    connection.execute("""CREATE TABLE IF NOT EXISTS workforce_case_analyses (
        analysis_id TEXT PRIMARY KEY, case_id TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL)""")
    connection.execute("""CREATE TABLE IF NOT EXISTS workforce_case_reviews (
        review_id TEXT PRIMARY KEY, analysis_id TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL,
        FOREIGN KEY (analysis_id) REFERENCES workforce_case_analyses(analysis_id))""")


def _save_analysis(analysis: CaseAnalysis) -> None:
    with get_connection() as connection:
        _ensure_tables(connection)
        connection.execute("INSERT INTO workforce_case_analyses VALUES (?, ?, ?, ?)",
                           (analysis.analysis_id, analysis.case_id, analysis.model_dump_json(), analysis.created_at))


def get_analysis(analysis_id: str) -> CaseAnalysis | None:
    with get_connection() as connection:
        _ensure_tables(connection)
        row = connection.execute("SELECT payload_json FROM workforce_case_analyses WHERE analysis_id = ?", (analysis_id,)).fetchone()
    return CaseAnalysis.model_validate_json(row["payload_json"]) if row else None


def update_analysis_title(analysis_id: str, update: AnalysisTitleUpdate) -> CaseAnalysis:
    analysis = get_analysis(analysis_id)
    if analysis is None:
        raise LookupError("Analysis not found.")
    analysis.project_title = update.project_title.strip()
    if not analysis.project_title:
        raise ValueError("Enter a title for this analysis.")
    with get_connection() as connection:
        connection.execute(
            "UPDATE workforce_case_analyses SET payload_json = ? WHERE analysis_id = ?",
            (analysis.model_dump_json(), analysis_id),
        )
    return analysis


def list_analyses() -> list[CaseAnalysis]:
    with get_connection() as connection:
        _ensure_tables(connection)
        rows = connection.execute(
            "SELECT payload_json FROM workforce_case_analyses ORDER BY created_at DESC LIMIT 50"
        ).fetchall()
    return [CaseAnalysis.model_validate_json(row["payload_json"]) for row in rows]


def save_review(analysis_id: str, review: ReviewRequest) -> dict[str, object]:
    analysis = get_analysis(analysis_id)
    if analysis is None:
        raise LookupError("Analysis not found.")
    if review.selected_option_id and review.selected_option_id not in {option.option_id for option in analysis.options}:
        raise ValueError("Selected option does not belong to this analysis.")
    if review.decision in {"ready_for_approval", "approved"}:
        if analysis.decision_status == "insufficient_evidence":
            raise ValueError("This analysis lacks verified evidence and cannot be marked ready for approval.")
        chosen = next((option for option in analysis.options if option.option_id == review.selected_option_id), None)
        if chosen is None or chosen.status != "eligible":
            raise ValueError("Only an eligible selected option can be advanced or approved.")
    record: dict[str, object] = {"review_id": str(uuid4()), "analysis_id": analysis_id,
                                 "created_at": datetime.now(UTC).isoformat(), **review.model_dump()}
    with get_connection() as connection:
        _ensure_tables(connection)
        connection.execute("INSERT INTO workforce_case_reviews VALUES (?, ?, ?, ?)",
                           (record["review_id"], analysis_id, json.dumps(record), record["created_at"]))
    return record


def list_reviews(analysis_id: str) -> list[dict[str, object]]:
    with get_connection() as connection:
        _ensure_tables(connection)
        rows = connection.execute("SELECT payload_json FROM workforce_case_reviews WHERE analysis_id = ? ORDER BY created_at DESC", (analysis_id,)).fetchall()
    return [json.loads(row["payload_json"]) for row in rows]
