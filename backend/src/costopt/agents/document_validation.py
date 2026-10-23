"""Read-only document validation, optional Gemini review, and immutable reports."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from costopt.agents.data_cleaning import _header, _number, _suggest, inspect_rows, select_source_country
from costopt.config import settings
from costopt.pipeline.workforce_uploads import get_upload, inspect_supporting_uploads, validate_supporting_uploads
from costopt.prompts.registry import load_system_prompt
from costopt.storage.repositories import list_locations
from costopt.storage.sqlite import get_connection


class DocumentValidationRequest(BaseModel):
    scenario_id: str
    upload_id: str
    supporting_upload_ids: list[str] = Field(default_factory=list, max_length=3)
    destination_country_ids: list[str] = Field(default_factory=list, max_length=20)
    use_llm: bool = True


class ValidationAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    finding_id: str
    action: str = Field(max_length=1200)


class ValidationReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str = Field(max_length=2000)
    actions: list[ValidationAction] = Field(default_factory=list, max_length=50)


class DataValidationAgent:
    """Explain missing evidence with Gemini; validated rules own all gates."""

    def __init__(self, client=None):
        self.client = client

    def review(self, report, enabled=True):
        fallback = {"provider": "rules", "status": "not_requested", "summary":
                    "Automated checks completed. Review the detailed results and upload corrected source documents where required. No workbook columns or values were changed.", "actions": []}
        if not enabled:
            return fallback
        if not settings.data_validation_llm_enabled or not settings.gemini_api_key:
            return {**fallback, "status": "unavailable", "summary": "Automated checks completed. Review the detailed results below."}
        from google import genai
        from google.genai import types
        # All rows are checked by code. Gemini receives complete grouped counts
        # rather than a partial workbook disguised as a complete review.
        # Send complete category counts and representative rows instead of
        # thousands of repeated findings. Deterministic rules still inspect
        # every row and remain the authority for readiness.
        grouped = {}
        for item in report["findings"]:
            key = (item["severity"], item.get("field", "validation"), item["message"])
            group = grouped.setdefault(key, {"severity": item["severity"], "field": item.get("field", "validation"),
                                             "message": item["message"], "count": 0, "examples": []})
            group["count"] += 1
            if len(group["examples"]) < 3:
                group["examples"].append({name: item.get(name) for name in ("id", "document", "sheet", "row", "sow")})
        facts = {"documents": report["documents"], "sow_count": len(report["sows"]),
                 "finding_count": len(report["findings"]), "finding_groups": list(grouped.values()),
                 "rule_ready": report["ready"]}
        if len(json.dumps(facts)) > 120000:
            facts["finding_groups"] = facts["finding_groups"][:200]
        try:
            client = self.client or genai.Client(api_key=settings.gemini_api_key.get_secret_value(),
                http_options=types.HttpOptions(timeout=int(settings.llm_timeout_seconds * 1000)))
            response = client.models.generate_content(
                model=settings.gemini_model,
                contents=load_system_prompt("data_validation_review_v1") + "\n\n" + json.dumps(facts),
                config=types.GenerateContentConfig(temperature=0, max_output_tokens=4000,
                    response_mime_type="application/json", response_schema=ValidationReview))
            review = ValidationReview.model_validate_json(response.text)
            allowed = {item["id"] for item in report["findings"]}
            if any(action.finding_id not in allowed for action in review.actions):
                raise ValueError("Unknown finding reference")
            return {"provider": "gemini", "status": "completed", "model": settings.gemini_model, **review.model_dump()}
        except Exception:
            return {**fallback, "status": "failed", "summary": "Automated checks completed. An additional plain-language explanation was not available, so use the detailed results below."}


def validate_documents(request: DocumentValidationRequest, reviewer=None):
    upload = get_upload(request.upload_id)
    if not upload or upload.get("scenario_id") != request.scenario_id or upload.get("source_id") != "excel":
        raise ValueError("Workbook does not belong to this scenario.")
    validate_supporting_uploads(request.scenario_id, request.supporting_upload_ids)
    documents, findings, sows = [], [], []

    def finding(document, sheet, row, field, severity, message, sow=None):
        findings.append({"id": f"F{len(findings)+1}", "document": document, "sheet": sheet, "row": row,
                         "field": field, "severity": severity, "message": message, "sow": sow})

    primary = [{_header(key): _suggest(_header(key), value) for key, value in row.items()}
               for row in upload.get("preview_rows", [])]
    columns = [_header(key) for key in upload.get("preview_columns", [])]
    inventory = upload.get("worksheet_inventory") or [{"sheet": upload.get("sheet", "Saved preview"),
        "rows": len(primary), "columns": upload.get("preview_columns", []), "recognized": True, "data": []}]
    documents.append({"filename": upload["filename"], "upload_id": upload["upload_id"], "kind": "workforce",
                      "sha256": upload.get("file_sha256"), "worksheets": len(inventory),
                      "rows_checked": sum(int(sheet.get("rows", 0) or 0) for sheet in inventory)})
    # Workbook-wide review validates structure and workforce counts here. Rate
    # completeness is checked per SOW against the separate rate-card document,
    # avoiding one false "missing annual value" error for every overview row.
    main_checks = inspect_rows(primary, [], require_rate=False)
    for item in main_checks["issues"]:
        finding(upload["filename"], upload.get("sheet", "Workbook"), item["row"], item["field"], item["severity"], item["message"])
    for required in ("sow reference", "delivery countries", "e1", "e2", "e3", "e4", "e5"):
        if required not in columns:
            finding(upload["filename"], "Workbook", 0, required, "critical", "Required field is missing. Correct the source workbook and re-upload; no column has been inserted.")
    if upload.get("cleaning_status") != "approved":
        finding(upload["filename"], "Workbook", 0, "approval", "critical", "Review and approve proposed formatting corrections before selecting a SOW.")
    primary_sows = {row.get("sow reference") for row in primary}
    for sheet in inventory:
        if sheet["sheet"] == upload.get("sheet"):
            continue
        normalized = [_header(key) for key in sheet["columns"]]
        if not sheet["recognized"]:
            finding(upload["filename"], sheet["sheet"], 0, "coverage", "warning", "Sheet scanned; no supported workforce table was identified. Review any narrative evidence manually.")
            continue
        rows = [{key: _suggest(key, values[i] if i < len(values) else "") for i, key in enumerate(normalized) if key}
                for values in sheet.get("data", []) if any(str(value).strip() for value in values)]
        if sum(level in normalized for level in ("e1", "e2", "e3", "e4", "e5")) >= 2:
            for item in inspect_rows(rows, [])["issues"]:
                finding(upload["filename"], sheet["sheet"], item["row"], item["field"], item["severity"], item["message"])
            finding(upload["filename"], sheet["sheet"], 0, "workforce scope", "critical", "Additional workforce table found. Consolidate workforce rows into the main SOW table before recommendation so no SOW is omitted.")
        else:
            seen_workers = set()
            for index, row in enumerate(rows, 1):
                sow = row.get("sow reference")
                if sow and sow not in primary_sows:
                    finding(upload["filename"], sheet["sheet"], index, "sow reference", "warning", "SOW is absent from the main workforce table.", sow)
                worker = row.get("worker reference")
                if worker:
                    if worker in seen_workers:
                        finding(upload["filename"], sheet["sheet"], index, "worker reference", "critical", "Duplicate worker reference.", sow)
                    seen_workers.add(worker)
                for key in ("annual value eur", "current rate eur", "bill rate"):
                    if key in row:
                        try:
                            if _number(row[key]) <= 0:
                                raise ValueError()
                        except ValueError:
                            finding(upload["filename"], sheet["sheet"], index, key, "critical", "A valid positive rate or annual value is required.", sow)
    locations = {item.location_id: item.country for item in list_locations()}
    if any(key not in locations for key in request.destination_country_ids):
        raise ValueError("Unknown destination country.")
    destinations = [locations[key] for key in request.destination_country_ids]
    for identifier in request.supporting_upload_ids:
        record = get_upload(identifier)
        documents.append({"filename": record["filename"], "upload_id": identifier, "kind": record["data_kind"],
                          "sha256": record.get("file_sha256"), "worksheets": len(record.get("original_sheets", [])) or 1,
                          "rows_checked": len(record.get("rows", []))})
    global_evidence_findings = set()
    global_evidence_categories = {"Required documents", "Missing information", "Rate values", "Rate units",
                                  "E-level", "Evidence status", "Information to provide"}
    for index, row in enumerate(primary, 1):
        sow = row.get("sow reference", "")
        if not sow:
            continue
        levels = []
        for level in ("e1", "e2", "e3", "e4", "e5"):
            try:
                if _number(row.get(level, "")) > 0:
                    levels.append(level.upper())
            except ValueError:
                pass
        source_country = select_source_country(row.get("delivery countries", ""))
        sources = [source_country] if source_country else []
        evidence = inspect_supporting_uploads(request.scenario_id, request.supporting_upload_ids, sow, destinations, levels, sources)
        for check in evidence["checks"]:
            if check["status"] != "pass":
                if check["category"] in global_evidence_categories:
                    key = (check["category"], check["status"], check["message"])
                    if key in global_evidence_findings:
                        continue
                    global_evidence_findings.add(key)
                    finding("Supporting documents", "All", 0, check["category"], check["status"], check["message"])
                else:
                    finding("Supporting documents", "All", index, check["category"], check["status"], check["message"], sow)
        sows.append({"sow_reference": sow, "row": index, "ready": index in main_checks["accepted_rows"] and evidence["ready"] and upload.get("cleaning_status") == "approved",
                     "missing_information": evidence["missing_information"]})
    global_errors = any(item["severity"] == "critical" and (item["row"] == 0 or item["sheet"] != upload.get("sheet", "Workbook") and item["document"] == upload["filename"]) for item in findings)
    if global_errors:
        for sow in sows:
            sow["ready"] = False
    finding_groups = {}
    for item in findings:
        key = (item["severity"], item["field"], item["message"])
        group = finding_groups.setdefault(key, {"severity": item["severity"], "field": item["field"],
                                                "message": item["message"], "count": 0, "examples": []})
        group["count"] += 1
        if len(group["examples"]) < 5:
            group["examples"].append({name: item.get(name) for name in ("id", "document", "sheet", "row", "sow")})
    result = {"report_id": str(uuid4()), "created_at": datetime.now(UTC).isoformat(),
              "request": request.model_dump(), "documents": documents, "findings": findings, "sows": sows,
              "finding_groups": list(finding_groups.values()),
              "ready": bool(sows) and all(item["ready"] for item in sows),
              "missing_information": [item for item in findings if item["severity"] == "critical"],
              "next_step": "Correct missing information in the source documents, upload replacements, then validate again. Original columns and files are preserved."}
    result["agent_review"] = (reviewer or DataValidationAgent()).review(result, request.use_llm)
    with get_connection() as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS workforce_document_validations (report_id TEXT PRIMARY KEY, payload_json TEXT NOT NULL, created_at TEXT NOT NULL)")
        connection.execute("INSERT INTO workforce_document_validations VALUES (?, ?, ?)", (result["report_id"], json.dumps(result), result["created_at"]))
    return result
