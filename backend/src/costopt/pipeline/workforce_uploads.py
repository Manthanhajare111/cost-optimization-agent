"""Bounded, team-scoped CSV/XLSX workforce uploads for the local MVP."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import tempfile
import zipfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import uuid4
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape as xml_escape

from costopt.storage.repositories import load_scenario_context
from costopt.storage.sqlite import get_connection


PROPOSAL_LEVELS = ("E1", "E2", "E3", "E4", "E5")
PROPOSAL_LEVEL_FACTORS = {"E1": 0.72, "E2": 0.84, "E3": 1.0, "E4": 1.14, "E5": 1.28}
DEFAULT_GERMANY_LEVEL_RATES = {"E1": 650.0, "E2": 760.0, "E3": 900.0, "E4": 1030.0, "E5": 1180.0}


MAX_FILE_BYTES = 2_000_000
MAX_UNCOMPRESSED_BYTES = 10_000_000
MAX_ROWS = 1_000
ALLOWED_COLUMNS = (
    "resource_id", "scenario_id", "squad_id", "current_location_id", "role",
    "skill", "current_rate_eur", "billing_units_per_month",
)
XML_NS = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
TEMPLATE_COLUMNS = {
    "excel": ("resource_id", "scenario_id", "role", "skill", "current_rate_eur"),
    "fieldglass": ("resource_id", "scenario_id", "role", "skill", "current_rate_eur", "availability"),
    "ariba": ("contract_id", "scenario_id", "supplier_id", "contract_type", "offshore_permitted",
              "customer_approval_required", "data_residency_restriction"),
}


def _column_name(index: int) -> str:
    result = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _workbook_bytes(columns: tuple[str, ...], rows: list[dict[str, object]]) -> bytes:
    """Write a minimal standards-compliant XLSX without a third-party dependency."""
    sheet_rows = []
    for row_number, values in enumerate([dict.fromkeys(columns, ""), *rows], start=1):
        cells = []
        for column_number, key in enumerate(columns, start=1):
            value = key if row_number == 1 else values.get(key, "")
            ref = f"{_column_name(column_number)}{row_number}"
            cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{xml_escape(str(value if value is not None else ""))}</t></is></c>')
        sheet_rows.append(f'<row r="{row_number}">{"".join(cells)}</row>')
    sheet = ('<?xml version="1.0" encoding="UTF-8"?>'
             '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
             f'<sheetData>{"".join(sheet_rows)}</sheetData></worksheet>')
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8"?>'
                         '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                         '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                         '<Default Extension="xml" ContentType="application/xml"/>'
                         '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                         '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                         '</Types>')
        archive.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8"?>'
                         '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                         '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
                         '</Relationships>')
        archive.writestr("xl/workbook.xml", '<?xml version="1.0" encoding="UTF-8"?>'
                         '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                         'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                         '<sheets><sheet name="Team data" sheetId="1" r:id="rId1"/></sheets></workbook>')
        archive.writestr("xl/_rels/workbook.xml.rels", '<?xml version="1.0" encoding="UTF-8"?>'
                         '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                         '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
                         '</Relationships>')
        archive.writestr("xl/worksheets/sheet1.xml", sheet)
    return stream.getvalue()


def source_template(source_id: str, scenario_id: str) -> bytes:
    if source_id not in TEMPLATE_COLUMNS:
        raise ValueError("Unknown source template.")
    context = load_scenario_context(scenario_id=scenario_id)
    if source_id == "ariba":
        rows = [{"contract_id": item.contract_id, "scenario_id": scenario_id,
                 "supplier_id": item.supplier_id, "contract_type": item.contract_type,
                 "offshore_permitted": str(item.offshore_permitted).upper(),
                 "customer_approval_required": str(item.customer_approval_required).upper(),
                 "data_residency_restriction": item.data_residency_restriction or ""}
                for item in context.contracts]
    else:
        rows = [{"resource_id": item.resource_id, "scenario_id": scenario_id,
                 "role": item.role, "skill": item.skill, "current_rate_eur": item.current_rate,
                 "availability": item.availability or "active"}
                for item in context.resources]
    return _workbook_bytes(TEMPLATE_COLUMNS[source_id], rows)


def _xlsx_rows(content: bytes, sheet_name: str | None = None,
               freeform: bool = False) -> list[dict[str, str]]:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            if sum(item.file_size for item in archive.infolist()) > MAX_UNCOMPRESSED_BYTES:
                raise ValueError("Excel workbook expands beyond the 10 MB safety limit.")
            names = archive.namelist()
            sheet_name = sheet_name or next((name for name in names if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name)), None)
            if sheet_name is None:
                raise ValueError("No worksheet found in the Excel workbook.")
            shared: list[str] = []
            if "xl/sharedStrings.xml" in names:
                root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
                shared = ["".join(node.itertext()) for node in root.findall("x:si", XML_NS)]
            sheet = ET.fromstring(archive.read(sheet_name))
            matrix: list[list[str]] = []
            for row in sheet.findall(".//x:sheetData/x:row", XML_NS):
                cells: dict[int, str] = {}
                for cell in row.findall("x:c", XML_NS):
                    ref = cell.get("r", "")
                    letters = re.match(r"[A-Z]+", ref)
                    if not letters:
                        continue
                    index = 0
                    for letter in letters.group():
                        index = index * 26 + ord(letter) - ord("A") + 1
                    raw = cell.findtext("x:v", default="", namespaces=XML_NS)
                    if cell.get("t") == "s" and raw:
                        raw = shared[int(raw)]
                    elif cell.get("t") == "inlineStr":
                        inline = cell.find("x:is", XML_NS)
                        raw = "".join(inline.itertext()) if inline is not None else ""
                    cells[index - 1] = raw
                if cells:
                    matrix.append([cells.get(i, "") for i in range(max(cells) + 1)])
                if len(matrix) > MAX_ROWS + 1:
                    raise ValueError(f"Upload is limited to {MAX_ROWS} data rows.")
    except (zipfile.BadZipFile, ET.ParseError, IndexError) as exc:
        raise ValueError("This is not a readable .xlsx workbook.") from exc
    if not matrix:
        return []
    if freeform:
        candidates = []
        for index, values in enumerate(matrix[:25]):
            headers = [value.strip() for value in values if value.strip()]
            if len(headers) < 2 or len(set(headers)) != len(headers):
                continue
            if any(len(header) > 80 for header in headers):
                continue
            following = sum(1 for row in matrix[index + 1:] if sum(bool(value.strip()) for value in row) >= 2)
            candidates.append((following * len(headers), index))
        if not candidates:
            return []
        matrix = matrix[max(candidates)[1]:]
    headers = [header.strip().lower() for header in matrix[0]]
    return [{headers[i]: value.strip() for i, value in enumerate(values) if i < len(headers) and headers[i]}
            for values in matrix[1:] if any(value.strip() for value in values)]


def _parse_rows(filename: str, content: bytes) -> list[dict[str, str]]:
    if not content or len(content) > MAX_FILE_BYTES:
        raise ValueError("Choose a non-empty CSV or XLSX file smaller than 2 MB.")
    suffix = Path(filename).suffix.lower()
    if suffix == ".csv":
        try:
            stream = io.StringIO(content.decode("utf-8-sig"), newline="")
            rows = list(csv.DictReader(stream))
        except (UnicodeDecodeError, csv.Error) as exc:
            raise ValueError("CSV must be UTF-8 encoded and readable.") from exc
        if len(rows) > MAX_ROWS:
            raise ValueError(f"Upload is limited to {MAX_ROWS} data rows.")
        return [{str(key).strip().lower(): str(value or "").strip() for key, value in row.items() if key}
                for row in rows]
    if suffix == ".xlsx":
        return _xlsx_rows(content)
    raise ValueError("Upload a .csv or .xlsx workforce file.")


def _proposal_workbook_upload(scenario_id: str, filename: str, content: bytes) -> dict[str, object]:
    """Convert the RFP's `2. Proposal` sheet into a Germany workforce upload.

    The workbook provides SOW-level worker-grade counts rather than named workers.
    One synthetic planning resource is therefore created for each stated worker. Its
    rate is the SOW annual value allocated across E1-E5 using transparent grade
    factors. These are planning estimates, not employee records or approved rates.
    """
    if Path(filename).suffix.lower() != ".xlsb":
        raise ValueError("Upload the SAP Aggregator Proposal workbook (.xlsb).")
    if not content or len(content) > MAX_FILE_BYTES:
        raise ValueError("Choose a non-empty .xlsb workbook smaller than 2 MB.")
    try:
        from pyxlsb import open_workbook
    except ImportError as exc:  # pragma: no cover - packaging guard
        raise ValueError("XLSB support is not installed on this CostOpt server.") from exc
    context = load_scenario_context(scenario_id=scenario_id)
    with tempfile.NamedTemporaryFile(suffix=".xlsb", delete=False) as temporary:
        temporary.write(content)
        temporary.flush()
        temporary_path = Path(temporary.name)
    try:
        try:
            with open_workbook(temporary_path) as workbook:
                if "2. Proposal" not in workbook.sheets:
                    raise ValueError("The workbook must contain the '2. Proposal' sheet.")
                with workbook.get_sheet("2. Proposal") as sheet:
                    matrix = [[cell.v for cell in row] for row in sheet.rows()]
        except Exception as exc:
            if isinstance(exc, ValueError):
                raise
            raise ValueError("The Proposal workbook could not be read.") from exc
    finally:
        temporary_path.unlink(missing_ok=True)
    if len(matrix) < 21 or [str(value or "") for value in matrix[19][1:14]] != [
        "SOW Reference", "Board Area", "L1 Category", "Sub-Category (L2)",
        "Service Classification", "Service Area(s)", "SOW Description/\nSAP product relation",
        "Delivery Countries", "E1", "E2", "E3", "E4", "E5",
    ]:
        raise ValueError("The second Proposal sheet does not have the expected SOW and E1-E5 columns.")
    # Keep the preview faithful to the uploaded Proposal sheet. Generated
    # resource rows below are analysis-only and are never used for preview.
    preview_columns = [str(value).strip() for value in matrix[19][1:] if str(value or "").strip()]
    preview_rows = [
        {column: values[index + 1] if index + 1 < len(values) else ""
         for index, column in enumerate(preview_columns)}
        for values in matrix[20:]
        if any(str(value or "").strip() for value in values[1:])
    ]
    supplier_id = context.resources[0].supplier_id
    rows: list[dict[str, object]] = []
    projects: list[dict[str, object]] = []
    level_counts = {level: 0 for level in PROPOSAL_LEVELS}
    for values in matrix[20:]:
        if len(values) < 20 or not re.fullmatch(r"AS-\d+", str(values[1] or "")):
            continue
        countries = str(values[8] or "")
        if "Germany" not in {country.strip() for country in countries.split(",")}:
            continue
        counts = {level: max(0, int(float(values[index] or 0))) for index, level in enumerate(PROPOSAL_LEVELS, start=9)}
        worker_count = sum(counts.values())
        if not worker_count:
            continue
        annual_value = float(values[19] or 0) if isinstance(values[19], (int, float)) else 0.0
        weighted_workers = sum(counts[level] * PROPOSAL_LEVEL_FACTORS[level] for level in PROPOSAL_LEVELS)
        daily_base = annual_value / (12 * 10.14 * weighted_workers) if annual_value > 0 and weighted_workers else 0.0
        sow_reference = str(values[1])
        projects.append({"sow_reference": sow_reference, "board_area": str(values[2] or ""),
                         "service_classification": str(values[5] or ""), "delivery_countries": countries,
                         "annual_value_eur": annual_value, "worker_count": worker_count, "levels": counts})
        for level, count in counts.items():
            level_counts[level] += count
            rate = round(daily_base * PROPOSAL_LEVEL_FACTORS[level], 2) if daily_base else DEFAULT_GERMANY_LEVEL_RATES[level]
            for ordinal in range(1, count + 1):
                rows.append({"resource_id": f"proposal-{sow_reference.lower()}-{level.lower()}-{ordinal:03d}",
                             "supplier_id": supplier_id, "squad_id": context.squad.squad_id,
                             "current_location_id": "loc-germany", "role": f"{sow_reference}-{level}",
                             "skill": level, "level": level, "current_rate": rate, "current_rate_eur": rate,
                             "pii_access": False, "availability": "active",
                             "sow_reference": sow_reference, "board_area": str(values[2] or ""),
                             "service_classification": str(values[5] or "")})
    if not rows:
        raise ValueError("The Proposal workbook has no Germany SOW workers with E1-E5 counts.")
    record: dict[str, object] = {
        "upload_id": str(uuid4()), "source_id": "excel", "data_kind": "proposal_workbook",
        "scenario_id": scenario_id, "filename": Path(filename).name, "created_at": datetime.now(UTC).isoformat(),
        "row_count": len(rows), "matched_count": len(rows), "ignored_count": 0, "rows": rows,
        "columns": ["sow_reference", "resource_id", "level", "current_rate_eur"], "projects": projects,
        "preview_rows": preview_rows, "preview_columns": preview_columns,
        "level_counts": level_counts, "applied_fields": ["resource", "level", "current_rate_eur"],
        "analysis_role": ("Germany workforce and E1-E5 levels were derived from the Proposal workbook's second sheet. "
                          "Individual planning rates are allocated from indicative SOW annual values; target rate cards are generated from the destination cost index."),
    }
    with get_connection() as connection:
        _ensure_table(connection)
        connection.execute("INSERT INTO workforce_uploads VALUES (?, ?, ?, ?, ?)",
                           (record["upload_id"], scenario_id, record["filename"], json.dumps(record), record["created_at"]))
    return record


def _proposal_xlsx_upload(scenario_id: str, filename: str, content: bytes) -> dict[str, object] | None:
    """Recognise an XLSX export of the Proposal sheet and apply the same model."""
    if Path(filename).suffix.lower() != ".xlsx":
        return None
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            sheets = [name for name in archive.namelist()
                      if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name)]
        tables = [_xlsx_rows(content, sheet_name=sheet, freeform=True) for sheet in sheets]
    except (zipfile.BadZipFile, ET.ParseError) as exc:
        raise ValueError("This is not a readable .xlsx workbook.") from exc
    required = {"sow reference", "delivery countries", "e1", "e2", "e3", "e4", "e5"}
    rows = next((table for table in tables if table and required <= set(table[0])), None)
    if rows is None:
        return None
    context = load_scenario_context(scenario_id=scenario_id)
    supplier_id = context.resources[0].supplier_id
    resources: list[dict[str, object]] = []
    projects: list[dict[str, object]] = []
    level_counts = {level: 0 for level in PROPOSAL_LEVELS}
    annual_key = next((key for key in rows[0] if "annual value" in key or "annualized" in key), None)
    for row in rows:
        sow_reference = row.get("sow reference", "")
        countries = row.get("delivery countries", "")
        if not re.fullmatch(r"(?:AS-|Ex\. )\d+", sow_reference) or "Germany" not in {item.strip() for item in countries.split(",")}:
            continue
        counts = {level: max(0, int(float(row.get(level.lower(), "0") or 0))) for level in PROPOSAL_LEVELS}
        workers = sum(counts.values())
        if not workers:
            continue
        try:
            annual_value = float(row.get(annual_key or "", "") or 0)
        except ValueError:
            annual_value = 0.0
        weighted = sum(counts[level] * PROPOSAL_LEVEL_FACTORS[level] for level in PROPOSAL_LEVELS)
        daily_base = annual_value / (12 * 10.14 * weighted) if annual_value and weighted else 0.0
        projects.append({"sow_reference": sow_reference, "board_area": row.get("board area", ""),
                         "service_classification": row.get("service classification", ""),
                         "delivery_countries": countries, "annual_value_eur": annual_value,
                         "worker_count": workers, "levels": counts})
        for level, count in counts.items():
            level_counts[level] += count
            rate = round(daily_base * PROPOSAL_LEVEL_FACTORS[level], 2) if daily_base else DEFAULT_GERMANY_LEVEL_RATES[level]
            for ordinal in range(1, count + 1):
                resources.append({"resource_id": f"proposal-{sow_reference.lower().replace('.', '')}-{level.lower()}-{ordinal:03d}",
                                  "supplier_id": supplier_id, "squad_id": context.squad.squad_id,
                                  "current_location_id": "loc-germany", "role": f"{sow_reference}-{level}",
                                  "skill": level, "level": level, "current_rate": rate, "current_rate_eur": rate,
                                  "pii_access": False, "availability": "active", "sow_reference": sow_reference})
    if not resources:
        raise ValueError("The Proposal XLSX has no Germany SOW workers with E1-E5 counts.")
    record = {"upload_id": str(uuid4()), "source_id": "excel", "data_kind": "proposal_workbook",
              "scenario_id": scenario_id, "filename": Path(filename).name, "created_at": datetime.now(UTC).isoformat(),
              "row_count": len(resources), "matched_count": len(resources), "ignored_count": 0, "rows": resources,
              "columns": ["sow_reference", "resource_id", "level", "current_rate_eur"], "projects": projects,
              "preview_rows": rows, "preview_columns": list(rows[0]),
              "level_counts": level_counts, "applied_fields": ["resource", "level", "current_rate_eur"],
              "analysis_role": "Germany workforce and E1-E5 levels were derived from the uploaded Proposal XLSX."}
    with get_connection() as connection:
        _ensure_table(connection)
        connection.execute("INSERT INTO workforce_uploads VALUES (?, ?, ?, ?, ?)",
                           (record["upload_id"], scenario_id, record["filename"], json.dumps(record), record["created_at"]))
    return record


def _ensure_table(connection) -> None:
    connection.execute("""CREATE TABLE IF NOT EXISTS workforce_uploads (
        upload_id TEXT PRIMARY KEY, scenario_id TEXT NOT NULL, filename TEXT NOT NULL,
        payload_json TEXT NOT NULL, created_at TEXT NOT NULL)""")


def get_upload(upload_id: str) -> dict[str, object] | None:
    with get_connection() as connection:
        _ensure_table(connection)
        row = connection.execute("SELECT payload_json FROM workforce_uploads WHERE upload_id = ?", (upload_id,)).fetchone()
    return json.loads(row["payload_json"]) if row else None


def ingest_sow_overview(scenario_id: str, filename: str, content: bytes,
                        source_id: str = "fieldglass") -> dict[str, object]:
    """Import the anonymised SAP Aggregator RFI SOW workbook as reference evidence.

    It has no validated worker rates or CostOpt resource IDs, so it must not
    overwrite the financial workforce baseline.
    """
    load_scenario_context(scenario_id=scenario_id)
    if source_id not in {"excel", "fieldglass"}:
        raise ValueError("Custom SOW data is supported for Excel / CSV and Fieldglass only.")
    if Path(filename).suffix.lower() != ".xlsx" or not content or len(content) > MAX_FILE_BYTES:
        raise ValueError("Choose a non-empty .xlsx SOW workbook smaller than 2 MB.")
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            if sum(item.file_size for item in archive.infolist()) > MAX_UNCOMPRESSED_BYTES:
                raise ValueError("Excel workbook expands beyond the 10 MB safety limit.")
            names = archive.namelist()
            if not {"xl/workbook.xml", "xl/worksheets/sheet5.xml", "xl/worksheets/sheet7.xml"} <= set(names):
                raise ValueError("This is not the SAP Aggregator RFI SOW Overview workbook.")
            workbook = ET.fromstring(archive.read("xl/workbook.xml"))
            sheet_names = [sheet.get("name") for sheet in workbook.findall(".//x:sheets/x:sheet", XML_NS)]
            if "SAP_Aggr_RFI SOW Overview" not in sheet_names or "3. SOW Roles" not in sheet_names:
                raise ValueError("The SOW listing and worker-detail sheets are required.")
            shared: list[str] = []
            if "xl/sharedStrings.xml" in names:
                strings = ET.fromstring(archive.read("xl/sharedStrings.xml"))
                shared = ["".join(node.itertext()) for node in strings.findall("x:si", XML_NS)]

            def sheet_rows(path: str) -> dict[int, dict[str, str]]:
                root = ET.fromstring(archive.read(path))
                result: dict[int, dict[str, str]] = {}
                for row in root.findall(".//x:sheetData/x:row", XML_NS):
                    cells = {}
                    for cell in row.findall("x:c", XML_NS):
                        raw = cell.findtext("x:v", default="", namespaces=XML_NS)
                        if cell.get("t") == "s" and raw:
                            raw = shared[int(raw)]
                        elif cell.get("t") == "inlineStr":
                            inline = cell.find("x:is", XML_NS)
                            raw = "".join(inline.itertext()) if inline is not None else ""
                        cells[re.sub(r"\d", "", cell.get("r", ""))] = raw.strip()
                    result[int(row.get("r", "0"))] = cells
                return result

            sow_sheet = sheet_rows("xl/worksheets/sheet5.xml")
            worker_sheet = sheet_rows("xl/worksheets/sheet7.xml")
    except (zipfile.BadZipFile, ET.ParseError, IndexError, KeyError) as exc:
        raise ValueError("This is not a readable SAP Aggregator RFI SOW workbook.") from exc
    if sow_sheet.get(10, {}).get("B") != "SOW Reference" or worker_sheet.get(19, {}).get("C") != "Worker Reference":
        raise ValueError("The SOW workbook headers do not match the expected layout.")
    # Keep the workbook's actual (non-empty) SOW headers in the preview instead
    # of projecting five fields. Only a few rows are returned to the browser.
    header_cells = sow_sheet[10]
    header_columns = [(letter, header_cells[letter]) for letter in sorted(
        header_cells, key=lambda value: (len(value), value)) if header_cells[letter]]
    sow_rows = [{header: row.get(letter, "") for letter, header in header_columns}
                for number, row in sow_sheet.items() if number > 10 and re.fullmatch(r"AS-\d+", row.get("B", ""))]
    worker_rows = [row for number, row in worker_sheet.items()
                   if number > 19 and re.fullmatch(r"W-\d+", row.get("C", ""))]
    if not sow_rows or not worker_rows or len(sow_rows) > MAX_ROWS or len(worker_rows) > MAX_ROWS:
        raise ValueError("The SOW workbook has no valid rows or exceeds the 1,000-row limit.")
    country_counts: dict[str, int] = {}
    for row in worker_rows:
        country = row.get("H", "").strip()
        if country:
            country_counts[country] = country_counts.get(country, 0) + 1
    record: dict[str, object] = {
        "upload_id": str(uuid4()), "source_id": source_id, "data_kind": "sow_overview",
        "scenario_id": scenario_id, "filename": Path(filename).name,
        "created_at": datetime.now(UTC).isoformat(), "row_count": len(sow_rows),
        "matched_count": len(sow_rows), "ignored_count": 0, "worker_count": len(worker_rows),
        "country_counts": country_counts, "rows": sow_rows,
        "columns": [header for _, header in header_columns],
        "applied_fields": [],
        "analysis_role": ("Custom SOW and worker-location evidence informs country checks only. "
                          "Anonymised SOWs cannot be matched to CostOpt resources; no validated rates are supplied, "
                          "so this workbook does not alter modeled savings."),
    }
    with get_connection() as connection:
        _ensure_table(connection)
        connection.execute("INSERT INTO workforce_uploads VALUES (?, ?, ?, ?, ?)",
                           (record["upload_id"], scenario_id, record["filename"], json.dumps(record), record["created_at"]))
    return record


def ingest_freeform_file(scenario_id: str, filename: str, content: bytes) -> dict[str, object]:
    """Accept bounded CSV/XLSX evidence without pretending arbitrary columns are rates."""
    load_scenario_context(scenario_id=scenario_id)
    if Path(filename).suffix.lower() == ".xlsx":
        if not content or len(content) > MAX_FILE_BYTES:
            raise ValueError("Choose a non-empty XLSX file smaller than 2 MB.")
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                sheets = [name for name in archive.namelist()
                          if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name)]
            tables = [_xlsx_rows(content, sheet_name=name, freeform=True) for name in sheets]
            rows = max(tables, key=lambda table: len(table) * len(table[0]) if table else 0, default=[])
        except zipfile.BadZipFile as exc:
            raise ValueError("This is not a readable .xlsx workbook.") from exc
    else:
        rows = _parse_rows(filename, content)
    if not rows:
        raise ValueError("No tabular data rows were found. Put column names in the first row, or use the SOW Overview workbook.")
    columns = list(dict.fromkeys(key for row in rows for key in row if key))[:40]
    if not columns:
        raise ValueError("The uploaded file needs a header row with column names.")
    location_key = next((key for key in ("delivery location", "delivery_location", "location", "country", "delivery country")
                         if key in columns), None)
    role_key = next((key for key in ("role", "role title", "role_title", "worker role", "worker_role")
                     if key in columns), None)
    country_counts: dict[str, int] = {}
    role_counts: dict[str, int] = {}
    for row in rows:
        if location_key and row.get(location_key):
            country = row[location_key].strip()
            country_counts[country] = country_counts.get(country, 0) + 1
        if role_key and row.get(role_key):
            role = row[role_key].strip()
            role_counts[role] = role_counts.get(role, 0) + 1
    record: dict[str, object] = {
        "upload_id": str(uuid4()), "source_id": "excel", "data_kind": "freeform_evidence",
        "scenario_id": scenario_id, "filename": Path(filename).name,
        "created_at": datetime.now(UTC).isoformat(), "row_count": len(rows),
        "matched_count": len(rows), "ignored_count": 0, "rows": rows, "columns": columns,
        "country_counts": country_counts, "role_counts": role_counts, "applied_fields": [],
        "analysis_role": ("Custom tabular evidence is profiled for locations and roles where those columns exist. "
                          "It is not linked to CostOpt resource IDs and does not change modeled savings or eligibility."),
    }
    with get_connection() as connection:
        _ensure_table(connection)
        connection.execute("INSERT INTO workforce_uploads VALUES (?, ?, ?, ?, ?)",
                           (record["upload_id"], scenario_id, record["filename"], json.dumps(record), record["created_at"]))
    return record


def ingest_workforce_file(scenario_id: str, filename: str, content: bytes) -> dict[str, object]:
    from costopt.agents.data_cleaning import stage_proposal
    staged = stage_proposal(scenario_id, filename, content)
    if staged is not None:
        return staged
    if Path(filename).suffix.lower() == ".xlsb":
        return _proposal_workbook_upload(scenario_id, filename, content)
    proposal_xlsx = _proposal_xlsx_upload(scenario_id, filename, content)
    if proposal_xlsx is not None:
        return proposal_xlsx
    context = load_scenario_context(scenario_id=scenario_id)
    raw_rows = _parse_rows(filename, content)
    if not raw_rows or "resource_id" not in raw_rows[0]:
        raise ValueError("The file needs a resource_id column and at least one data row.")
    known = {resource.resource_id for resource in context.resources}
    matched: list[dict[str, str]] = []
    ignored = 0
    seen: set[str] = set()
    for raw in raw_rows:
        resource_id = raw.get("resource_id", "")
        if resource_id not in known or (raw.get("scenario_id") and raw["scenario_id"] != scenario_id) or (
            raw.get("squad_id") and raw["squad_id"] != context.squad.squad_id
        ):
            ignored += 1
            continue
        if resource_id in seen:
            raise ValueError(f"Duplicate resource_id in upload: {resource_id}")
        seen.add(resource_id)
        if any(not raw.get(field) for field in ("role", "skill", "current_rate_eur")):
            raise ValueError(f"{resource_id} needs role, skill and current_rate_eur for a workforce analysis.")
        row = {key: raw.get(key, "") for key in ALLOWED_COLUMNS if key in raw}
        if row.get("current_rate_eur"):
            try:
                rate = float(row["current_rate_eur"])
            except ValueError as exc:
                raise ValueError(f"Invalid current_rate_eur for {resource_id}.") from exc
            if not 0 < rate <= 1_000_000:
                raise ValueError(f"current_rate_eur must be positive for {resource_id}.")
        matched.append(row)
    if not matched:
        raise ValueError("No uploaded resource_id belongs to the selected team. Select the matching team or correct the file.")
    applied_fields = [field for field in ("current_rate_eur", "role", "skill")
                      if any(row.get(field) for row in matched)]
    record: dict[str, object] = {
        "upload_id": str(uuid4()), "scenario_id": scenario_id, "filename": Path(filename).name,
        "created_at": datetime.now(UTC).isoformat(), "row_count": len(raw_rows),
        "matched_count": len(matched), "ignored_count": ignored, "rows": matched,
        "columns": [key for key in ALLOWED_COLUMNS if any(key in row for row in matched)],
        "applied_fields": applied_fields,
        "analysis_role": ("Matched role, skill and current-rate values replace local mock values for this run; "
                          "supplier, contract, PII and location rules remain governed by CostOpt."
                          if applied_fields else "Preview only: no role, skill or current-rate values are available to apply."),
    }
    with get_connection() as connection:
        _ensure_table(connection)
        connection.execute("INSERT INTO workforce_uploads VALUES (?, ?, ?, ?, ?)",
                           (record["upload_id"], scenario_id, record["filename"], json.dumps(record), record["created_at"]))
    return record


def ingest_template_file(source_id: str, scenario_id: str, filename: str, content: bytes) -> dict[str, object]:
    """Accept only a selected team's source-specific XLSX template schema."""
    if source_id not in TEMPLATE_COLUMNS:
        raise ValueError("Unknown source template.")
    if Path(filename).suffix.lower() != ".xlsx":
        raise ValueError("Upload the downloaded .xlsx template for this source.")
    rows = _parse_rows(filename, content)
    columns = TEMPLATE_COLUMNS[source_id]
    if not rows or tuple(rows[0]) != columns or any(tuple(row) != columns for row in rows):
        raise ValueError(f"Template columns must be exactly: {', '.join(columns)}")
    context = load_scenario_context(scenario_id=scenario_id)
    if source_id == "ariba":
        known = {item.contract_id: item for item in context.contracts}
        key = "contract_id"
    else:
        known = {item.resource_id: item for item in context.resources}
        key = "resource_id"
    seen: set[str] = set()
    for row in rows:
        identifier = row[key]
        if row["scenario_id"] != scenario_id or identifier not in known:
            raise ValueError(f"{identifier or 'A row'} does not belong to the selected team.")
        if identifier in seen:
            raise ValueError(f"Duplicate {key}: {identifier}")
        seen.add(identifier)
        if source_id == "ariba":
            if row["supplier_id"] != known[identifier].supplier_id:
                raise ValueError(f"Supplier ID cannot be changed for {identifier}.")
            for field in ("offshore_permitted", "customer_approval_required"):
                if row[field].upper() not in {"TRUE", "FALSE"}:
                    raise ValueError(f"{field} must be TRUE or FALSE for {identifier}.")
            if len(row["data_residency_restriction"]) > 500:
                raise ValueError("Data-residency restriction is too long.")
        else:
            try:
                rate = float(row["current_rate_eur"])
            except ValueError as exc:
                raise ValueError(f"Invalid current_rate_eur for {identifier}.") from exc
            if not 0 < rate <= 1_000_000:
                raise ValueError(f"current_rate_eur must be positive for {identifier}.")
            if not row["role"] or not row["skill"] or len(row["role"]) > 120 or len(row["skill"]) > 120:
                raise ValueError(f"Role and skill are required (120 characters max) for {identifier}.")
            if source_id == "fieldglass" and row["availability"].lower() not in {"active", "inactive", "on_leave"}:
                raise ValueError(f"Availability must be active, inactive, or on_leave for {identifier}.")
    record: dict[str, object] = {
        "upload_id": str(uuid4()), "source_id": source_id, "scenario_id": scenario_id,
        "filename": Path(filename).name, "created_at": datetime.now(UTC).isoformat(),
        "row_count": len(rows), "matched_count": len(rows), "ignored_count": 0,
        "rows": rows, "columns": list(columns),
        "applied_fields": (["role", "skill", "current_rate_eur", "availability"] if source_id == "fieldglass"
                           else ["role", "skill", "current_rate_eur"] if source_id == "excel"
                           else ["offshore_permitted", "customer_approval_required", "data_residency_restriction"]),
        "analysis_role": ("Manual workforce values are used in this run. Governed supplier, PII and location rules remain unchanged."
                          if source_id != "ariba" else
                          "Manual contract values can add restrictions or approval requirements, but cannot relax existing governed policy."),
    }
    with get_connection() as connection:
        _ensure_table(connection)
        connection.execute("INSERT INTO workforce_uploads VALUES (?, ?, ?, ?, ?)",
                           (record["upload_id"], scenario_id, record["filename"], json.dumps(record), record["created_at"]))
    return record


SUPPORTING_KINDS = {"rate_card", "contractual_evidence", "delivery_constraints"}


def ingest_supporting_file(scenario_id: str, filename: str, content: bytes, document_kind: str | None = None) -> dict[str, object]:
    """Store supporting documents for review, without granting policy approval."""
    load_scenario_context(scenario_id=scenario_id)
    if not content or len(content) > MAX_FILE_BYTES:
        raise ValueError("Choose a non-empty document smaller than 2 MB.")
    suffix = Path(filename).suffix.lower()
    if document_kind is not None and document_kind not in SUPPORTING_KINDS:
        raise ValueError("Choose rate card, contractual evidence or delivery constraints.")
    original_sheets = []
    if suffix in {".xlsx", ".csv"}:
        if suffix == ".xlsx":
            try:
                with zipfile.ZipFile(io.BytesIO(content)) as archive:
                    if sum(item.file_size for item in archive.infolist()) > MAX_UNCOMPRESSED_BYTES:
                        raise ValueError("Workbook expands beyond 10 MB.")
                    sheet_names = [name for name in archive.namelist() if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name)]
            except zipfile.BadZipFile as exc:
                raise ValueError("Document is not a readable XLSX workbook.") from exc
            rows = []
            for sheet in sheet_names:
                values = _xlsx_rows(content, sheet_name=sheet, freeform=True)
                original_sheets.append({"sheet": sheet, "rows": values, "columns": list(values[0]) if values else []})
                rows.extend(values)
            if document_kind == "rate_card":
                def rate_sheet_score(item):
                    headers = {str(value).strip().lower().replace("_", " ") for value in item.get("columns", [])}
                    groups = (
                        {"level", "grade", "e level"},
                        {"country", "delivery country"},
                        {"rate unit", "unit"},
                        {"bill rate", "daily rate", "daily rate eur", "net rate gbp", "net day rate gbp", "standard rate gbp"},
                    )
                    return sum(bool(headers & group) for group in groups)
                selected_sheet = max(original_sheets, key=rate_sheet_score, default=None)
                if selected_sheet and rate_sheet_score(selected_sheet) >= 3:
                    rows = list(selected_sheet["rows"])
        else:
            rows = _parse_rows(filename, content)
            original_sheets.append({"sheet": "CSV", "rows": rows, "columns": list(rows[0]) if rows else []})
        if not rows or len(rows) > MAX_ROWS:
            raise ValueError("Supporting documents must contain between 1 and 1000 data rows.")
        # Map existing headers internally; do not require metadata columns in Excel.
        aliases = {"sow reference": "sow_reference", "sow ref": "sow_reference", "e level": "level", "grade": "level",
                   "delivery country": "country", "daily rate eur": "bill_rate", "daily rate": "bill_rate",
                   "bill rate": "bill_rate", "net rate gbp": "net_rate", "net day rate gbp": "net_rate",
                   "standard rate gbp": "standard_rate", "rate unit": "rate_unit", "unit": "rate_unit"}
        original_rows = rows
        mapped_rows = []
        for row in rows:
            mapped = {aliases.get(key.strip().lower().replace("_", " "), key): value for key, value in row.items()}
            if document_kind == "rate_card" and not str(mapped.get("bill_rate", "")).strip():
                mapped["bill_rate"] = mapped.get("net_rate") or mapped.get("standard_rate") or ""
            if document_kind == "rate_card" and not str(mapped.get("currency", "")).strip():
                currencies = {match.group(1).upper() for key in row for match in [re.search(r"(?:^|_)(eur|gbp|usd|cad|aud|inr|pln)$", key.lower())] if match}
                if len(currencies) == 1:
                    mapped["currency"] = next(iter(currencies))
            mapped_rows.append(mapped)
        rows = mapped_rows
        kinds = {row.get("document_kind", "") for row in rows}
        if document_kind is None and (len(kinds) != 1 or not kinds <= SUPPORTING_KINDS):
            raise ValueError("Every row needs the same document_kind: rate_card, contractual_evidence or delivery_constraints.")
        kind = document_kind or next(iter(kinds))
        required = {"sow_reference", "status"}
        if kind == "rate_card":
            required |= {"level", "country", "currency", "rate_unit", "bill_rate"}
        if document_kind is None and any(not required <= row.keys() or any(not row[k] for k in required) for row in rows):
            raise ValueError("Missing required supporting-document fields: " + ", ".join(sorted(required)))
        if kind == "rate_card":
            for row in rows:
                try:
                    valid = 0 < float(row.get("bill_rate", "")) <= 1000000
                except ValueError:
                    valid = False
                if not valid and document_kind is None:
                    raise ValueError("Each bill_rate must be a positive finite number up to 1000000.")
        columns = list(rows[0])
    elif suffix in {".docx", ".txt"}:
        if document_kind == "rate_card":
            raise ValueError("Upload the rate card as XLSX or CSV so every rate can be checked.")
        try:
            if suffix == ".docx":
                with zipfile.ZipFile(io.BytesIO(content)) as archive:
                    if sum(item.file_size for item in archive.infolist()) > MAX_UNCOMPRESSED_BYTES:
                        raise ValueError("Document expands beyond 10 MB.")
                    root = ET.fromstring(archive.read("word/document.xml"))
                    paragraphs = ["".join(node.itertext()) for node in root.findall(".//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p")]
                    document = "\n".join(paragraphs)
            else:
                document = content.decode("utf-8-sig")
        except (zipfile.BadZipFile, KeyError, ET.ParseError, UnicodeDecodeError) as exc:
            raise ValueError("Document is not readable DOCX or UTF-8 text.") from exc
        match = re.search(r"^document_kind: (contractual_evidence|delivery_constraints)$", document, re.M)
        if document_kind is None and (not match or not re.search(r"^sow_reference: \S+", document, re.M)):
            raise ValueError("Document requires document_kind: contractual_evidence or delivery_constraints, and sow_reference: on separate lines.")
        kind = document_kind or match[1]
        rows = [{"text": line} for line in document.splitlines() if line.strip()]
        if len(rows) > MAX_ROWS:
            raise ValueError("Document is limited to 1000 paragraphs.")
        columns = ["text"]
        original_rows = rows
        original_sheets = [{"sheet": "Document", "columns": columns, "rows": rows}]
    else:
        raise ValueError("Supporting documents must be XLSX, CSV, DOCX or TXT.")
    sow_references = sorted({
        (row.get("sow_reference", "") if "sow_reference" in row else
         re.sub(r"^sow_reference:\s*", "", row.get("text", ""), flags=re.I).strip())
        for row in rows
        if row.get("sow_reference", "") or re.match(r"^sow_reference:\s*\S+", row.get("text", ""), re.I)
    })
    if suffix in {".docx", ".txt"} and document_kind:
        # Recognize explicit references in ordinary prose without requiring
        # metadata lines or changing the preserved document.
        sow_references = sorted(set(sow_references) | {
            match.upper().replace(" ", "") for match in
            re.findall(r"\b(?:AS|EX)\s*-\s*\d+(?:\.\d+)?\b", document, re.I)
        })
    statuses = sorted({
        (row.get("status", "") if "status" in row else
         re.sub(r"^status:\s*", "", row.get("text", ""), flags=re.I).strip())
        for row in rows
        if row.get("status", "") or re.match(r"^status:\s*\S+", row.get("text", ""), re.I)
    })
    record = {"upload_id": str(uuid4()), "scenario_id": scenario_id,
              "source_id": "supporting", "data_kind": kind, "filename": Path(filename).name,
              "created_at": datetime.now(UTC).isoformat(), "row_count": len(rows),
              "rows": rows, "columns": columns, "applied_fields": [],
              "original_rows": original_rows, "original_sheets": original_sheets,
              "file_sha256": hashlib.sha256(content).hexdigest(),
              "sow_references": sow_references, "statuses": statuses,
              "analysis_role": "Supporting evidence for human review only; does not override calculation rates or governed policy."}
    with get_connection() as connection:
        _ensure_table(connection)
        from costopt.agents.data_cleaning import _tables
        _tables(connection)
        connection.execute("INSERT INTO workforce_uploads VALUES (?, ?, ?, ?, ?)",
                           (record["upload_id"], scenario_id, record["filename"], json.dumps(record), record["created_at"]))
        connection.execute("INSERT INTO workforce_cleaning_files VALUES (?, ?, ?)", (record["upload_id"], content, record["file_sha256"]))
    return record


def validate_supporting_uploads(scenario_id: str, upload_ids: list[str]) -> None:
    if len(upload_ids) > 3 or len(set(upload_ids)) != len(upload_ids):
        raise ValueError("Attach at most three distinct supporting documents.")
    kinds = set()
    for upload_id in upload_ids:
        record = get_upload(upload_id)
        if not record or record.get("scenario_id") != scenario_id or record.get("source_id") != "supporting":
            raise ValueError("Supporting document does not belong to this scenario.")
        if record["data_kind"] in kinds:
            raise ValueError("Attach only one document of each supporting type.")
        kinds.add(record["data_kind"])


def inspect_supporting_uploads(scenario_id: str, upload_ids: list[str], selected_sow: str | None,
                               destination_countries: list[str] | None = None,
                               required_levels: list[str] | None = None,
                               source_countries: list[str] | None = None) -> dict[str, object]:
    """Cross-check supporting evidence without changing or applying uploaded values."""
    validate_supporting_uploads(scenario_id, upload_ids)
    records = [get_upload(upload_id) for upload_id in upload_ids]
    by_kind = {record["data_kind"]: record for record in records if record}
    checks: list[dict[str, str]] = []
    missing: list[str] = []

    def add(category: str, status: str, message: str) -> None:
        checks.append({"category": category, "status": status, "message": message})

    labels = {"rate_card": "rate card", "contractual_evidence": "contractual evidence",
              "delivery_constraints": "delivery constraints"}
    def sow_key(value: object) -> str:
        return "".join(character for character in str(value or "").casefold() if character.isalnum())

    def references(record: dict[str, object]) -> list[str]:
        saved = record.get("sow_references") or []
        if saved:
            return [str(value) for value in saved]
        result = []
        for row in record.get("rows", []):
            value = row.get("sow_reference", "")
            if not value:
                match = re.match(r"^sow_reference:\s*(\S+)", row.get("text", ""), re.I)
                value = match[1] if match else ""
            if value:
                result.append(str(value))
        return result

    def statuses(record: dict[str, object]) -> list[str]:
        saved = record.get("statuses") or []
        if saved:
            return [str(value) for value in saved]
        result = []
        for row in record.get("rows", []):
            value = row.get("status", "")
            if not value:
                match = re.match(r"^status:\s*(\S+)", row.get("text", ""), re.I)
                value = match[1] if match else ""
            if value:
                result.append(str(value))
        return sorted(set(result))

    def rate_date(value: object) -> date | None:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            number = float(text)
            return (datetime(1899, 12, 30) + timedelta(days=number)).date()
        except ValueError:
            pass
        for pattern in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%b-%Y"):
            try:
                return datetime.strptime(text, pattern).date()
            except ValueError:
                continue
        return None

    absent = [labels[kind] for kind in SUPPORTING_KINDS if kind not in by_kind]
    if absent:
        missing.extend(absent)
        add("Required documents", "critical", "Upload: " + ", ".join(sorted(absent)) + ".")
    else:
        add("Required documents", "pass", "Rate card, contractual evidence and delivery constraints are uploaded.")

    if selected_sow:
        mismatches = []
        for kind, record in by_kind.items():
            document_references = {sow_key(value) for value in references(record)}
            if document_references and sow_key(selected_sow) not in document_references:
                mismatches.append(labels[kind])
        if mismatches:
            missing.append(f"documents for {selected_sow}")
            add("SOW consistency", "critical",
                f"{selected_sow} is not referenced by: {', '.join(sorted(mismatches))}. Upload matching documents.")
        elif by_kind:
            add("SOW consistency", "pass", f"All uploaded supporting documents reference {selected_sow}.")

    # Inspect document values even before a SOW is selected. These checks do not
    # grant approval or copy supporting rates into the recommendation model.
    for kind, record in by_kind.items():
        document_references = references(record)
        commercial_rows: list[dict[str, object]] = []
        if kind == "rate_card":
            commercial_sheet = next((sheet for sheet in record.get("original_sheets", [])
                                     if {"standard_rate_gbp", "net_rate_gbp", "project_discount_pct"}
                                     & set(sheet.get("columns", []))), None)
            if commercial_sheet and len(commercial_sheet.get("rows", [])) == len(record.get("rows", [])):
                commercial_rows = commercial_sheet["rows"]
        for index, row in enumerate(record.get("rows", []), 1):
            if "text" in row:
                continue
            required = {"sow_reference"} if document_references else set()
            if kind == "rate_card":
                required |= {"role", "level", "country", "currency", "rate_unit", "bill_rate"}
            empty = sorted(key for key in required if not str(row.get(key, "")).strip())
            if empty:
                add("Missing information", "critical", f"{record['filename']}, data row {index}: supply {', '.join(empty)} in the source document and re-upload.")
            if kind == "rate_card":
                from costopt.agents.data_cleaning import _number
                try:
                    valid = 0 < _number(row.get("bill_rate", "")) <= 1000000
                except ValueError:
                    valid = False
                if not valid:
                    add("Rate values", "critical", f"{record['filename']}, data row {index}: a valid positive daily rate is required.")
                supported_daily_units = {"day", "daily", "person_day", "person-day", "person day",
                                         "person_day_8_hours", "person-day-8-hours", "person day 8 hours"}
                currency = str(row.get("currency", "")).upper()
                if not re.fullmatch(r"[A-Z]{3}", currency) or str(row.get("rate_unit", "")).strip().lower() not in supported_daily_units:
                    add("Rate units", "critical", f"{record['filename']}, data row {index}: use a declared three-letter currency and a daily billing unit.")
                if str(row.get("level", "")).upper() not in {"E1", "E2", "E3", "E4", "E5"}:
                    add("E-level", "critical", f"{record['filename']}, data row {index}: use an E1-E5 level.")
                commercial = commercial_rows[index - 1] if commercial_rows else row
                standard_value = row.get("standard_rate", commercial.get("standard_rate_gbp", ""))
                discount_value = row.get("project_discount_pct", commercial.get("project_discount_pct", ""))
                net_value = row.get("net_rate", commercial.get("net_rate_gbp", commercial.get("net_day_rate_gbp", "")))
                has_pricing_breakdown = any(str(value).strip() for value in (standard_value, discount_value, net_value))
                if has_pricing_breakdown:
                    try:
                        standard_rate = _number(standard_value)
                        discount = _number(discount_value)
                        net_rate = _number(net_value)
                        discount_fraction = discount / 100 if discount > 1 else discount
                        pricing_valid = (standard_rate > 0 and 0 <= discount_fraction <= 1 and net_rate > 0
                                         and abs(net_rate - standard_rate * (1 - discount_fraction)) <= 0.01)
                    except ValueError:
                        pricing_valid = False
                    if not pricing_valid:
                        add("Rate discount and net rate", "critical",
                            f"{record['filename']}, data row {index}: standard rate must be positive, discount must be 0-100%, and net rate must equal standard rate less discount.")
                effective_from_value = row.get("rate_effective_from", commercial.get("rate_effective_from", ""))
                effective_to_value = row.get("rate_effective_to", commercial.get("rate_effective_to", ""))
                if str(effective_from_value).strip() or str(effective_to_value).strip():
                    effective_from = rate_date(effective_from_value)
                    effective_to = rate_date(effective_to_value)
                    if not effective_from or not effective_to or effective_from > effective_to:
                        add("Rate effective dates", "critical",
                            f"{record['filename']}, data row {index}: provide valid effective-from and effective-to dates in chronological order.")
                    elif effective_to < datetime.now(UTC).date():
                        add("Rate expiry", "critical",
                            f"{record['filename']}, data row {index}: rate expired on {effective_to.isoformat()}.")
                    elif effective_to <= datetime.now(UTC).date() + timedelta(days=90):
                        add("Rate expiry", "warning",
                            f"{record['filename']}, data row {index}: rate expires on {effective_to.isoformat()}, within 90 days.")

        if kind == "rate_card":
            new_checks = [check for check in checks if record["filename"] in check["message"]]
            if not any(check["category"] in {"Missing information", "E-level"} for check in new_checks):
                add("Rate grade, role and country", "pass", "Every rate row has a valid E1-E5 grade, role and delivery country.")
            if not any(check["category"] in {"Rate values", "Rate discount and net rate"} for check in new_checks):
                add("Rate discount and net rate", "pass", "Standard rates, discounts and net rates are positive and reconcile.")
            if not any(check["category"] in {"Rate effective dates", "Rate expiry"} for check in new_checks):
                add("Rate effective dates", "pass", "Rate effective dates are valid and no rate is expired.")

    rate_card = by_kind.get("rate_card")
    if rate_card and selected_sow:
        rate_rows = [row for row in rate_card.get("rows", [])
                     if not sow_key(row.get("sow_reference")) or sow_key(row.get("sow_reference")) == sow_key(selected_sow)]
        rate_currencies = {str(row.get("currency", "")).upper() for row in rate_rows if str(row.get("currency", "")).strip()}
        if len(rate_currencies) > 1:
            add("Rate units", "critical", "Rate card contains multiple currencies: " + ", ".join(sorted(rate_currencies)) + ".")
        levels = set(required_levels or ("E1", "E2", "E3", "E4", "E5"))
        # Uploaded rate cards provide destination pricing. Current-country
        # baseline rates are governed reference data and are checked by the
        # recommendation workflow, so they must not be required in this file.
        countries = set(destination_countries or [])
        missing_pairs = sorted(
            f"{country}/{level}" for country in countries for level in levels
            if not any(row.get("country") == country and str(row.get("level", "")).upper() == level for row in rate_rows)
        )
        if not countries:
            add("Rate coverage", "pass", "Destination rate coverage will be checked after destination countries are selected.")
        elif missing_pairs:
            missing.append("rate rows: " + ", ".join(missing_pairs))
            add("Rate coverage", "critical", "Missing selected-SOW rate rows: " + ", ".join(missing_pairs) + ".")
        else:
            add("Rate coverage", "pass", f"Destination E-level rates are present for {', '.join(sorted(countries))}.")
        duplicate_pairs = sorted({
            f"{row.get('country')}/{str(row.get('level', '')).upper()}/{row.get('role', '')}"
            for row in rate_rows
            if sum(other.get("country") == row.get("country")
                   and str(other.get("level", "")).upper() == str(row.get("level", "")).upper()
                   and str(other.get("role", "")).casefold() == str(row.get("role", "")).casefold()
                   for other in rate_rows) > 1
        })
        if duplicate_pairs:
            add("Rate duplicates", "critical", "Duplicate country/E-level/role rates: " + ", ".join(duplicate_pairs) + ".")
        else:
            add("Rate duplicates", "pass", "No duplicate country/E-level/role rates were found.")

    for kind, record in by_kind.items():
        evidence_statuses = statuses(record)
        if not evidence_statuses:
            if kind != "rate_card":
                add("Contract evidence status" if kind == "contractual_evidence" else "Delivery constraints status",
                    "warning", f"Review before implementation: {labels[kind]} has no approval status.")
        elif any(any(marker in status.upper() for marker in ("UNAPPROVED", "PENDING", "SAMPLE", "SYNTHETIC")) for status in evidence_statuses):
            category = {"rate_card": "Rate evidence status", "contractual_evidence": "Contract evidence status",
                        "delivery_constraints": "Delivery constraints status"}[kind]
            add(category, "warning", f"Review before implementation: {labels[kind]}: {', '.join(evidence_statuses)}.")

    gap_markers = ("NOT PROVIDED", "TO BE PROVIDED", "PENDING", "UNVERIFIED", "NOT SIGNED", "NOT APPROVED")
    evidence_gaps = []
    for kind, record in by_kind.items():
        document_gaps = []
        for row in record.get("rows", []):
            text = str(row.get("text") or row.get("basis") or "").strip()
            if text and any(marker in text.upper() for marker in gap_markers):
                document_gaps.append(f"{labels[kind]}: {text}")
        document_gaps = list(dict.fromkeys(document_gaps))
        evidence_gaps.extend(document_gaps)
        if document_gaps:
            category = {"rate_card": "Rate information to provide", "contractual_evidence": "Contract evidence gaps",
                        "delivery_constraints": "Delivery constraints gaps"}[kind]
            add(category, "warning", " | ".join(document_gaps[:8]))
    evidence_gaps = list(dict.fromkeys(evidence_gaps))

    missing.extend(check["message"] for check in checks if check["status"] == "critical")

    return {"ready": not any(check["status"] == "critical" for check in checks),
            "checks": checks, "missing_information": list(dict.fromkeys(missing)),
            "evidence_gaps": evidence_gaps,
            "document_types": sorted(by_kind)}
