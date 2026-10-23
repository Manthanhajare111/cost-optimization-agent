"""Add one clearly synthetic SOW and three role rows to the local test workbook.

The original is backed up beside the workbook before an atomic replacement.
This is a one-time fixture edit, not a production-data migration.
"""

from __future__ import annotations

import copy
import io
import re
import shutil
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS = {"x": MAIN}
Q = lambda name: f"{{{MAIN}}}{name}"
ROOT = Path(__file__).resolve().parents[2]
WORKBOOK = ROOT / "docs" / "SAP_Aggr_RFI SOW Overview.xlsx"
BACKUP = ROOT / "docs" / "SAP_Aggr_RFI SOW Overview.before-AS-220.xlsx"


def _row(root: ET.Element, number: int) -> ET.Element:
    return next(row for row in root.findall(".//x:sheetData/x:row", NS) if row.get("r") == str(number))


def _renumber(row: ET.Element, number: int) -> None:
    row.set("r", str(number))
    for cell in row.findall("x:c", NS):
        cell.set("r", re.sub(r"\d+$", str(number), cell.get("r", "")))


def _write_row(row: ET.Element, number: int, values: dict[str, str | int | float]) -> None:
    _renumber(row, number)
    for cell in row.findall("x:c", NS):
        letter = re.match(r"[A-Z]+", cell.get("r", ""))
        key = letter.group() if letter else ""
        for child in list(cell):
            cell.remove(child)
        cell.attrib.pop("t", None)
        value = values.get(key)
        if value is None or value == "":
            continue
        if isinstance(value, (int, float)):
            ET.SubElement(cell, Q("v")).text = str(value)
        else:
            cell.set("t", "inlineStr")
            ET.SubElement(ET.SubElement(cell, Q("is")), Q("t")).text = value


def _add_sow(root: ET.Element) -> bytes:
    data = root.find("x:sheetData", NS)
    assert data is not None
    existing = _row(root, 229)
    summary = _row(root, 230)
    blank = _row(root, 231)
    new = copy.deepcopy(existing)
    _write_row(new, 230, {
        "B": "AS-220", "C": "Product & Engineering", "D": "Synthetic test project",
        "E": "Application Services", "F": "Application Consulting",
        "G": "SYNTHETIC TEST ONLY: three Germany-based workers; proposed destination Romania. No verified worker rates or migration approval.",
        "H": "Germany", "I": 0, "J": 1, "K": 2, "L": 0, "M": 0,
        "N": 3, "O": 2.67, "P": "E2/E3", "Q": "Time & Material",
    })
    data.insert(list(data).index(summary), new)
    _renumber(summary, 231)
    for formula in summary.findall(".//x:f", NS):
        if formula.text:
            formula.text = formula.text.replace("229", "230")
    _renumber(blank, 232)
    dimension = root.find("x:dimension", NS)
    if dimension is not None:
        dimension.set("ref", "A1:AP232")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _add_workers(root: ET.Element) -> bytes:
    data = root.find("x:sheetData", NS)
    assert data is not None
    template = _row(root, 574)
    trailing = _row(root, 575)
    for offset, (role, grade) in enumerate((
        ("Developer", "E3"), ("QA Tester", "E2"), ("Business Analyst", "E3"),
    )):
        new = copy.deepcopy(template)
        _write_row(new, 575 + offset, {
            "B": "AS-220", "C": f"W-{555 + offset}", "D": "Synthetic test project",
            "E": "Application Consulting", "F": role, "G": grade,
            "H": "Germany", "I": "HC", "J": "Germany", "K": "No",
            "L": "Time & Material",
        })
        data.insert(list(data).index(trailing), new)
    _renumber(trailing, 578)
    dimension = root.find("x:dimension", NS)
    if dimension is not None:
        dimension.set("ref", "A1:AM578")
    auto_filter = root.find("x:autoFilter", NS)
    if auto_filter is not None:
        auto_filter.set("ref", "B19:L577")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    if BACKUP.exists() and not dry_run:
        raise SystemExit(f"Backup already exists; refusing to overwrite: {BACKUP}")
    original = WORKBOOK.read_bytes()
    with zipfile.ZipFile(io.BytesIO(original)) as archive:
        source_entries = [(item, archive.read(item.filename)) for item in archive.infolist()]
        sow = ET.fromstring(archive.read("xl/worksheets/sheet5.xml"))
        workers = ET.fromstring(archive.read("xl/worksheets/sheet7.xml"))
    if b"AS-220" in original or b"W-555" in original:
        raise SystemExit("The proposed synthetic SOW/worker reference already exists.")
    replacements = {
        "xl/worksheets/sheet5.xml": _add_sow(sow),
        "xl/worksheets/sheet7.xml": _add_workers(workers),
    }
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as target:
        for info, content in source_entries:
            target.writestr(info, replacements.get(info.filename, content))
    with zipfile.ZipFile(io.BytesIO(payload.getvalue())) as check:
        if check.testzip() is not None:
            raise RuntimeError("The updated workbook failed its ZIP integrity check.")
        from costopt.pipeline.workforce_uploads import _xlsx_rows
        sow_rows = _xlsx_rows(payload.getvalue(), "xl/worksheets/sheet5.xml", True)
        worker_rows = _xlsx_rows(payload.getvalue(), "xl/worksheets/sheet7.xml", True)
        if not any(row.get("sow reference") == "AS-220" for row in sow_rows):
            raise RuntimeError("The new SOW row was not found after workbook serialization.")
        if sum(row.get("sow reference") == "AS-220" for row in worker_rows) != 3:
            raise RuntimeError("The three new worker rows were not found after workbook serialization.")
    if dry_run:
        print(f"Dry run valid: {len(sow_rows)} SOW rows and {len(worker_rows)} worker rows.")
        return
    output = WORKBOOK.with_name("SAP_Aggr_RFI SOW Overview.AS-220-writing.xlsx")
    try:
        output.write_bytes(payload.getvalue())
        shutil.copy2(WORKBOOK, BACKUP)
        output.replace(WORKBOOK)
    finally:
        if output.exists():
            output.unlink()
    print(f"Added synthetic AS-220 and W-555–W-557. Backup: {BACKUP.name}")


if __name__ == "__main__":
    main()
