"""Deterministic, approval-gated cleaning of Proposal workforce workbooks.

Original files and parsed cells are immutable. Proposals never become calculation
inputs until a reviewer approves a validated revision.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
import tempfile
import zipfile
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4
from xml.etree import ElementTree as ET

from pydantic import BaseModel, Field
from costopt.storage.sqlite import get_connection
from costopt.storage.repositories import load_scenario_context, list_locations

LEVELS = ("e1", "e2", "e3", "e4", "e5")
REQUIRED = ("sow reference", "delivery countries", *LEVELS)
MAX_WORKERS = 10000


class CellEdit(BaseModel):
    row: int = Field(ge=1, le=1000)
    field: str = Field(min_length=1, max_length=160)
    value: str = Field(max_length=2000)


class CleaningRequest(BaseModel):
    scenario_id: str
    base_run_id: str | None = None
    edits: list[CellEdit] = Field(default_factory=list, max_length=10000)
    excluded_rows: list[int] = Field(default_factory=list, max_length=1000)
    reason: str = Field(default="", max_length=2000)


class CleaningApproval(BaseModel):
    scenario_id: str
    reviewer_name: str = Field(min_length=2, max_length=120)
    approved: bool


def _tables(connection):
    connection.execute("CREATE TABLE IF NOT EXISTS workforce_cleaning_files (upload_id TEXT PRIMARY KEY, content BLOB NOT NULL, sha256 TEXT NOT NULL)")
    connection.execute("CREATE TABLE IF NOT EXISTS workforce_cleaning_runs (run_id TEXT PRIMARY KEY, upload_id TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL)")
    connection.execute("CREATE TABLE IF NOT EXISTS workforce_cleaning_approvals (run_id TEXT PRIMARY KEY, approved_upload_id TEXT NOT NULL, reviewer_name TEXT NOT NULL, created_at TEXT NOT NULL)")


def _header(value):
    text = re.sub(r"[ _\-]+", " ", str(value).strip().lower())
    if re.fullmatch(r"e ?[1-5]", text):
        return text.replace(" ", "")
    aliases = {"sow ref": "sow reference", "sow id": "sow reference", "delivery country": "delivery countries",
               "# workers": "worker total", "number of workers": "worker total", "worker count": "worker total", "total workers": "worker total", "workers": "worker total",
               "total headcount": "worker total", "headcount": "worker total", "total": "worker total",
               "current rate eur": "current rate eur", "daily rate": "current rate eur", "daily rate eur": "current rate eur"}
    if "annual value" in text or "annualized" in text or "annualised" in text:
        return "annual value eur"
    return aliases.get(text, text)


def _matrix(content, suffix):
    from costopt.pipeline.workforce_uploads import MAX_UNCOMPRESSED_BYTES, XML_NS
    if suffix == ".csv":
        try:
            return [("CSV", list(csv.reader(io.StringIO(content.decode("utf-8-sig")))))]
        except (UnicodeDecodeError, csv.Error) as exc:
            raise ValueError("Upload a readable UTF-8 CSV file.") from exc
    if suffix == ".xlsb":
        from pyxlsb import open_workbook
        with tempfile.NamedTemporaryFile(suffix=".xlsb", delete=False) as stream:
            stream.write(content)
            name = Path(stream.name)
        try:
            with open_workbook(name) as book:
                result = []
                for sheet_name in book.sheets:
                    with book.get_sheet(sheet_name) as sheet:
                        rows = []
                        for row in sheet.rows():
                            rows.append(["" if cell.v is None else str(cell.v) for cell in row])
                            if len(rows) > 1025:
                                raise ValueError("Each worksheet is limited to 1000 data rows plus 25 header rows.")
                        result.append((sheet_name, rows))
                return result
        finally:
            name.unlink(missing_ok=True)
    if suffix != ".xlsx":
        return []
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            if sum(item.file_size for item in archive.infolist()) > MAX_UNCOMPRESSED_BYTES:
                raise ValueError("Workbook exceeds the 10 MB expanded size limit.")
            shared = []
            if "xl/sharedStrings.xml" in archive.namelist():
                shared = ["".join(node.itertext()) for node in ET.fromstring(archive.read("xl/sharedStrings.xml")).findall("x:si", XML_NS)]
            tables = []
            for name in archive.namelist():
                if not re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name):
                    continue
                matrix = []
                for row in ET.fromstring(archive.read(name)).findall(".//x:sheetData/x:row", XML_NS):
                    cells = {}
                    for cell in row.findall("x:c", XML_NS):
                        match = re.match("[A-Z]+", cell.get("r", ""))
                        if not match:
                            continue
                        index = 0
                        for char in match.group():
                            index = index * 26 + ord(char) - 64
                        if index > 200:
                            raise ValueError("Proposal preview supports up to 200 columns.")
                        value = cell.findtext("x:v", "", XML_NS)
                        if cell.get("t") == "s" and value:
                            value = shared[int(value)]
                        elif cell.get("t") == "inlineStr":
                            inline = cell.find("x:is", XML_NS)
                            value = "".join(inline.itertext()) if inline is not None else ""
                        if cell.find("x:f", XML_NS) is not None and not value:
                            value = "[formula has no cached value]"
                        cells[index - 1] = value
                    matrix.append([cells.get(i, "") for i in range(max(cells, default=-1) + 1)])
                    if len(matrix) > 1025:
                        raise ValueError("Each worksheet is limited to 1000 data rows plus 25 header rows.")
                tables.append((name, matrix))
            return tables
    except (zipfile.BadZipFile, ET.ParseError, IndexError, KeyError) as exc:
        raise ValueError("Upload a readable Excel workbook.") from exc


def stage_proposal(scenario_id, filename, content):
    """Return a raw Proposal upload, or None for a non-Proposal template."""
    from costopt.pipeline.workforce_uploads import MAX_FILE_BYTES, _ensure_table
    if not content or len(content) > MAX_FILE_BYTES:
        raise ValueError("Choose a non-empty file smaller than 2 MB.")
    candidates = []
    worksheet_inventory = []
    for sheet, matrix in _matrix(content, Path(filename).suffix.lower()):
        sheet_candidates = []
        for index, values in enumerate(matrix[:25]):
            names = [_header(value) for value in values]
            score = len(set(names) & set(REQUIRED))
            if "sow reference" in names or score >= 3:
                candidates.append((score, sheet, index, matrix))
                sheet_candidates.append((score, index, values))
        best = max(sheet_candidates, default=None, key=lambda item: item[0])
        worksheet_inventory.append({"sheet": sheet, "rows": len(matrix), "recognized": bool(best),
                                    "header_row": best[1] + 1 if best else None,
                                    "columns": [str(value) for value in best[2]] if best else [],
                                    "data": matrix[best[1]+1:] if best else []})
    if not candidates:
        return None
    _, sheet, index, matrix = max(candidates, key=lambda item: item[0])
    header = matrix[index]
    normalized_header = {_header(value) for value in header if str(value).strip()}
    rate_card_markers = {"bill rate", "current rate eur", "rate unit", "currency", "level", "grade"}
    if len(normalized_header & set(REQUIRED)) < 3 and len(normalized_header & rate_card_markers) >= 2:
        raise ValueError("This looks like a rate card. Upload the Proposal workforce workbook here, then add the rate card under Upload documents for validation.")
    columns = [str(value) if str(value).strip() else f"Unnamed column {i+1}" for i, value in enumerate(header)]
    # Retain duplicate header cells under distinct preview keys and flag them later.
    seen = {}
    for i, key in enumerate(columns):
        seen[key] = seen.get(key, 0) + 1
        if seen[key] > 1:
            columns[i] = f"{key} [duplicate {seen[key]}]"
    rows = [{key: str(values[i]) if i < len(values) else "" for i, key in enumerate(columns)}
            for values in matrix[index+1:] if any(str(value).strip() for value in values)]
    if not rows or len(rows) > 1000:
        raise ValueError("Upload between 1 and 1000 data rows.")
    load_scenario_context(scenario_id=scenario_id)
    record = {"upload_id": str(uuid4()), "source_id": "excel", "scenario_id": scenario_id,
              "filename": Path(filename).name, "created_at": datetime.now(UTC).isoformat(),
              "data_kind": "proposal_workbook", "cleaning_status": "pending", "row_count": len(rows),
              "matched_count": 0, "ignored_count": 0, "rows": [], "projects": [], "columns": columns,
              "preview_columns": columns, "preview_rows": rows, "original_headers": header,
              "sheet": sheet, "header_row": index + 1, "file_sha256": hashlib.sha256(content).hexdigest(),
              "worksheet_inventory": worksheet_inventory,
              "analysis_role": "Original workbook preserved. Review and approve cleaning before these rows can be used."}
    with get_connection() as connection:
        _ensure_table(connection)
        _tables(connection)
        connection.execute("INSERT INTO workforce_uploads VALUES (?, ?, ?, ?, ?)",
                           (record["upload_id"], scenario_id, record["filename"], json.dumps(record), record["created_at"]))
        connection.execute("INSERT INTO workforce_cleaning_files VALUES (?, ?, ?)", (record["upload_id"], content, record["file_sha256"]))
    return record


def _number(value):
    text = str(value).strip().replace("\u00a0", " ")
    text = re.sub(r"^(?:EUR|\u20ac)\s*", "", text, flags=re.I)
    text = re.sub(r"\s*(?:EUR|\u20ac)$", "", text, flags=re.I)
    if re.fullmatch(r"\d{1,3}(?:[ ,]\d{3})+(?:\.\d+)?", text):
        text = text.replace(" ", "").replace(",", "")
    if not re.fullmatch(r"[+-]?\d+(?:\.\d+)?", text):
        raise ValueError("Use an unambiguous number (for example 1234.50); blanks are not zero.")
    number = float(text)
    if not math.isfinite(number) or abs(number) > 1e12:
        raise ValueError("Number is outside the supported range.")
    return number


def _suggest(field, value):
    text = str(value).strip()
    if field == "sow reference":
        match = re.fullmatch(r"as[\s_-]*(\d+)", text, re.I)
        if match:
            return f"AS-{match[1]}"
        match = re.fullmatch(r"ex[.\s_-]*(\d+)", text, re.I)
        return f"Ex. {match[1]}" if match else text
    if field == "delivery countries":
        if text.casefold() in {"n/a", "na", "none", "not applicable", "unknown"}:
            return ""
        names = {location.country.casefold(): location.country for location in list_locations()}
        names.update({"de": "Germany", "deu": "Germany", "deutschland": "Germany", "in": "India", "ind": "India",
                      "uk": "United Kingdom", "gb": "United Kingdom", "gbr": "United Kingdom",
                      "us": "United States", "usa": "United States"})
        return ", ".join(dict.fromkeys(names.get(part.strip().casefold(), part.strip()) for part in re.split(r"[,;/]", text) if part.strip()))
    if field in (*LEVELS, "worker total", "annual value eur", "current rate eur"):
        try:
            return format(_number(text), ".15g")
        except ValueError:
            return text
    return text


def select_source_country(value: str = "") -> str | None:
    """Use the first governed country in the declared delivery scope as source."""
    known = {location.country for location in list_locations()}
    names = {country.casefold(): country for country in known}
    for part in re.split(r"[,;/]", str(value)):
        country = names.get(part.strip().casefold())
        if country:
            return country
    return "Germany" if "Germany" in known else None


def inspect_rows(rows, excluded, structural=(), require_rate=True):
    issues = list(deepcopy(structural))
    seen = {}
    summary_rows = set()
    workers_total = 0
    def issue(row, field, message, severity="critical"):
        issues.append({"row": row, "field": field, "severity": severity, "message": message})
    for index, row in enumerate(rows, 1):
        if index in excluded:
            continue
        sow = str(row.get("sow reference", "")).strip()
        if sow.casefold() in {"total", "grand total"}:
            summary_rows.add(index)
            continue
        for key in REQUIRED:
            if not str(row.get(key, "")).strip():
                issue(index, key, "Required value is blank.")
        if sow and not re.fullmatch(r"(?:AS-|Ex\. )\d+", sow):
            issue(index, "sow reference", "Use AS-123 or Ex. 123 format.")
        if sow and sow in seen:
            issue(index, "sow reference", f"Duplicate SOW reference also occurs in row {seen[sow]}; resolve or explicitly exclude a duplicate.")
            issue(seen[sow], "sow reference", f"Duplicate SOW reference also occurs in row {index}.")
        if sow:
            seen[sow] = index
        counts = []
        for level in LEVELS:
            try:
                value = _number(row.get(level, ""))
                if value < 0 or not value.is_integer() or value > MAX_WORKERS:
                    raise ValueError("Count must be a whole number between 0 and 10000.")
                counts.append(int(value))
            except ValueError as exc:
                issue(index, level, str(exc))
        if len(counts) == 5:
            total = sum(counts)
            workers_total += total
            if total == 0:
                issue(index, "worker total", "No workers in this row; confirm or exclude it.", "warning")
            if "worker total" in row:
                try:
                    declared = _number(row["worker total"])
                    if declared != total:
                        issue(index, "worker total", f"Declared total {declared:g} differs from E1-E5 sum {total}.")
                except ValueError as exc:
                    issue(index, "worker total", str(exc))
            else:
                issue(index, "worker total", "No independent worker-total column; total will be derived from E1-E5.", "warning")
        present = [key for key in ("annual value eur", "current rate eur")
                   if key in row and (require_rate or str(row.get(key, "")).strip())]
        if not present and require_rate:
            issue(index, "annual value eur", "Supply a positive annual value or daily EUR rate; no default rate is substituted.")
        for key in present:
            try:
                if _number(row[key]) <= 0:
                    raise ValueError("Rate or annual value must be positive.")
            except ValueError as exc:
                issue(index, key, str(exc))
        if "annual value eur" in present and "current rate eur" not in present:
            issue(index, "annual value eur", "Planning daily rates will be allocated from annual value using E-level weights and 121.68 billing units/year; these are estimates.", "warning")
    if workers_total > MAX_WORKERS:
        issue(0, "worker total", "Combined workforce exceeds the 10000-resource limit.")
    if len(excluded) >= len(rows):
        issue(0, "rows", "At least one row must remain included.")
    bad = {item["row"] for item in issues if item["severity"] == "critical"}
    accepted = [i for i in range(1, len(rows)+1)
                if i not in excluded and i not in summary_rows and i not in bad and 0 not in bad]
    return {"issues": issues, "ready": not bad, "accepted_rows": accepted,
            "counts": {"accepted": len(accepted), "excluded": len(excluded),
                       "errors": sum(item["severity"] == "critical" for item in issues),
                       "warnings": sum(item["severity"] == "warning" for item in issues)}}


def get_run(run_id):
    with get_connection() as connection:
        _tables(connection)
        row = connection.execute("SELECT payload_json FROM workforce_cleaning_runs WHERE run_id=?", (run_id,)).fetchone()
        approval = connection.execute("SELECT * FROM workforce_cleaning_approvals WHERE run_id=?", (run_id,)).fetchone()
    if row is None:
        raise ValueError("Cleaning revision not found.")
    result = json.loads(row["payload_json"])
    result["approval"] = approval
    return result


def propose(upload_id, request):
    from costopt.pipeline.workforce_uploads import get_upload
    upload = get_upload(upload_id)
    if not upload or upload["scenario_id"] != request.scenario_id or upload.get("source_id") != "excel":
        raise ValueError("Upload does not belong to this scenario.")
    if upload.get("cleaning_status") == "approved":
        upload_id = upload["original_upload_id"]
        upload = get_upload(upload_id)
    if upload.get("data_kind") != "proposal_workbook":
        raise ValueError("Use a Proposal workbook with SOW references and E1-E5 columns.")
    original = deepcopy(upload.get("preview_rows", []))
    columns = upload.get("preview_columns", [])
    canonical = [_header(key) for key in columns]
    structural = []
    if len(set(canonical)) != len(canonical) or any("[duplicate " in key for key in columns):
        structural.append({"row": 0, "field": "headers", "severity": "critical", "message": "Duplicate column headers: correct the workbook and upload it again."})
    for key in REQUIRED:
        if key not in canonical:
            structural.append({"row": 0, "field": key, "severity": "critical", "message": "Required column missing: correct the workbook and upload it again."})
    original_normalized = [{_header(key): str(value if value is not None else "") for key, value in row.items()} for row in original]
    base = get_run(request.base_run_id) if request.base_run_id else None
    if base and (base["upload_id"] != upload_id or base["scenario_id"] != request.scenario_id):
        raise ValueError("Revision does not belong to this upload and scenario.")
    if request.edits and not base:
        raise ValueError("Create a cleaning proposal before editing it.")
    candidate = deepcopy(base["candidate_rows"]) if base else [{key: _suggest(key, value) for key, value in row.items()} for row in original_normalized]
    for edit in request.edits:
        if edit.row > len(candidate) or edit.field not in canonical:
            raise ValueError("Unknown row or field in cleaning edit.")
        candidate[edit.row-1][edit.field] = edit.value
    excluded = sorted(set(request.excluded_rows))
    if any(index < 1 or index > len(candidate) for index in excluded):
        raise ValueError("Excluded row does not exist.")
    if (request.edits or excluded) and not request.reason.strip():
        raise ValueError("Give a reason for manual changes or exclusions.")
    changes = []
    for key, target in zip(columns, canonical):
        if key != target:
            changes.append({"row": 0, "field": target, "original": key, "proposed": target, "reason": "Standardize column name."})
    for index, row in enumerate(candidate, 1):
        for key, value in row.items():
            old = original_normalized[index-1].get(key, "")
            if value != old:
                changes.append({"row": index, "field": key, "original": old, "proposed": value,
                                "reason": request.reason.strip() if base else "Standardize formatting using explicit rules; no missing values inferred."})
    audit = deepcopy(base["audit"]) if base else []
    created = datetime.now(UTC).isoformat()
    run_id = str(uuid4())
    audit.append({"event": "revised" if base else "proposed", "timestamp": created, "run_id": run_id,
                  "parent_run_id": request.base_run_id, "reason": request.reason, "edits": [edit.model_dump() for edit in request.edits], "excluded_rows": excluded})
    result = {"run_id": run_id, "upload_id": upload_id, "scenario_id": request.scenario_id,
              "agent": "data_cleaning", "rules_version": "1", "original_rows": original,
              "original_columns": columns, "candidate_rows": candidate,
              "excluded_rows": excluded, "changes": changes, "structural_issues": structural, "audit": audit,
              "file_sha256": upload.get("file_sha256"), "created_at": created,
              **inspect_rows(candidate, excluded, structural, require_rate=False)}
    # Missing fields belong in the validation report, never in generated columns.
    result["columns"] = list(dict.fromkeys(canonical))
    result["column_labels"] = dict(zip(canonical, columns))
    with get_connection() as connection:
        _tables(connection)
        connection.execute("INSERT INTO workforce_cleaning_runs VALUES (?, ?, ?, ?)", (run_id, upload_id, json.dumps(result), created))
    return result


def approve(run_id, request):
    from costopt.pipeline.workforce_uploads import get_upload, PROPOSAL_LEVEL_FACTORS, _ensure_table
    run = get_run(run_id)
    if run["scenario_id"] != request.scenario_id or not request.approved or not request.reviewer_name.strip():
        raise ValueError("Explicit approval and reviewer name are required for this scenario.")
    validation = inspect_rows(run["candidate_rows"], run["excluded_rows"], run["structural_issues"], require_rate=False)
    if not validation["ready"]:
        raise ValueError("Resolve all critical cleaning issues before approval.")
    if run["approval"]:
        return get_upload(run["approval"]["approved_upload_id"])
    original = get_upload(run["upload_id"])
    context = load_scenario_context(scenario_id=request.scenario_id)
    resources, projects, accepted = [], [], []
    location_ids = {location.country: location.location_id for location in list_locations()}
    totals = {level.upper(): 0 for level in LEVELS}
    for index, row in enumerate(run["candidate_rows"], 1):
        if index in run["excluded_rows"]:
            continue
        accepted.append(row)
        country = select_source_country(row["delivery countries"])
        if not country:
            raise ValueError("Germany must be configured as the governed source location before cleaning approval.")
        current_location_id = location_ids[country]
        counts = {level.upper(): int(_number(row[level])) for level in LEVELS}
        annual_value = str(row.get("annual value eur", "")).strip()
        annual = _number(annual_value) if annual_value else 0
        weighted = sum(counts[level] * PROPOSAL_LEVEL_FACTORS[level] for level in counts)
        daily_base = annual / (12 * 10.14 * weighted) if weighted else 0
        sow = row["sow reference"]
        projects.append({"sow_reference": sow, "delivery_countries": row["delivery countries"], "source_country": country, "levels": counts,
                         "worker_count": sum(counts.values()), "declared_worker_count": row.get("worker total"), "annual_value_eur": annual})
        for level, count in counts.items():
            totals[level] += count
            daily_rate = str(row.get("current rate eur", "")).strip()
            rate = round(_number(daily_rate) if daily_rate else daily_base * PROPOSAL_LEVEL_FACTORS[level], 2)
            for ordinal in range(1, count+1):
                resources.append({"resource_id": f"proposal-{sow.lower().replace('.', '')}-{level.lower()}-{ordinal:03d}",
                                  "supplier_id": context.resources[0].supplier_id, "squad_id": context.squad.squad_id,
                                  "current_location_id": current_location_id, "role": f"{sow}-{level}", "skill": level,
                                  "level": level, "current_rate": rate, "current_rate_eur": rate,
                                  "pii_access": False, "availability": "active", "sow_reference": sow})
    if not resources:
        raise ValueError("No workforce remains after cleaning; select a workbook with eligible source rows.")
    created = datetime.now(UTC).isoformat()
    upload_id = str(uuid4())
    record = {**original, "upload_id": upload_id, "created_at": created, "cleaning_status": "approved",
              "cleaning_run_id": run_id, "original_upload_id": run["upload_id"], "approved_by": request.reviewer_name.strip(),
              "original_preview_rows": run["original_rows"], "original_preview_columns": run["original_columns"],
              "preview_rows": [{key: row.get(_header(key), "") for key in run["original_columns"]} for row in accepted],
              "preview_columns": run["original_columns"], "rows": resources, "projects": projects,
              "columns": ["resource_id", "sow_reference", "level", "current_rate_eur"],
              "row_count": len(accepted), "matched_count": len(resources), "ignored_count": len(run["excluded_rows"]),
              "level_counts": totals, "analysis_role": "Approved cleaned workbook. Germany is the governed calculation source; delivery countries are retained as unrestricted scope context. Planning resources derive from approved E1-E5 counts; estimated rates require supplier verification.",
              "cleaning_audit": [*run["audit"], {"event": "approved", "timestamp": created, "reviewer": request.reviewer_name.strip(), "run_id": run_id, "changes": run["changes"], "excluded_rows": run["excluded_rows"]}]}
    with get_connection() as connection:
        _tables(connection)
        _ensure_table(connection)
        connection.execute("BEGIN IMMEDIATE")
        previous = connection.execute("SELECT approved_upload_id FROM workforce_cleaning_approvals WHERE run_id=?", (run_id,)).fetchone()
        if previous:
            return get_upload(previous["approved_upload_id"])
        connection.execute("INSERT INTO workforce_uploads VALUES (?, ?, ?, ?, ?)", (upload_id, request.scenario_id, original["filename"], json.dumps(record), created))
        connection.execute("INSERT INTO workforce_cleaning_approvals VALUES (?, ?, ?, ?)", (run_id, upload_id, request.reviewer_name.strip(), created))
    return record
