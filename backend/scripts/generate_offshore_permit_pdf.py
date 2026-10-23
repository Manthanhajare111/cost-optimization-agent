"""Generate a lightweight, non-binding offshore-delivery validation record.

The PDF is intentionally a review template. A signed customer contract or change
order remains the authoritative evidence of permission to move delivery.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import wrap


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "docs" / "Offshore_Delivery_Permission_Validation_Record.pdf"


SECTIONS = [
    ("Document purpose", [
        "Use this record to validate whether delivery under a Statement of Work (SOW) may move from one country to another.",
        "This is a review template only. It is not a contract amendment, customer approval, or legal opinion.",
    ]),
    ("Project and contract details", [
        "SOW reference: ____________________     Contract ID: ____________________",
        "Customer: _________________________     Supplier: ______________________",
        "Current delivery country: Germany       Proposed delivery country: ____________________",
        "Service / scope affected: __________________________________________________________",
        "Planned effective date: _______________  Contract owner: ____________________________",
    ]),
    ("Required contractual validation", [
        "[ ] Offshore-delivery clause explicitly permits the proposed country or approved delivery centre.",
        "[ ] The clause permits the relevant services, roles, subcontractors, and delivery model.",
        "[ ] Customer written approval requirement has been identified and approval is attached, if required.",
        "[ ] Data residency, privacy, security, export-control, and confidentiality clauses allow the move.",
        "[ ] Supplier rate card and SOW change-control terms permit the proposed commercial change.",
        "[ ] No contractual prohibition, territorial restriction, or customer-specific exception remains unresolved.",
    ]),
    ("Evidence register", [
        "Offshore-delivery clause ID / page: _________________________________________________",
        "Customer-approval clause ID / page: _________________________________________________",
        "Data-residency / privacy clause ID / page: ___________________________________________",
        "Attached approval, change order, or email reference: __________________________________",
        "Evidence reviewer notes: _____________________________________________________________",
        "____________________________________________________________________________________",
    ]),
    ("Validation outcome", [
        "[ ] Permitted - proceed to workforce transition planning.",
        "[ ] Permitted with conditions - list conditions below and obtain required approvals.",
        "[ ] Not permitted - do not move delivery under the current contract.",
        "[ ] Evidence incomplete - retain current location until evidence is completed.",
        "Conditions / gaps: _________________________________________________________________",
        "____________________________________________________________________________________",
    ]),
    ("Sign-off", [
        "Contract owner: ________________________  Date: _______________",
        "Legal / compliance reviewer: ____________  Date: _______________",
        "Customer approval reference: _____________ Date: _______________",
        "Project owner acknowledgement: ___________ Date: _______________",
        "Retention: attach this completed record and cited evidence to the SOW / project change record.",
    ]),
]


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _lines() -> list[tuple[str, bool]]:
    lines: list[tuple[str, bool]] = [("OFFSHORE DELIVERY PERMISSION VALIDATION RECORD", True),
                                      ("Template - requires contract, legal, and customer validation", False), ("", False)]
    for heading, content in SECTIONS:
        lines.append((heading, True))
        for item in content:
            lines.extend((line, False) for line in wrap(item, width=92, subsequent_indent="   ") or [""])
        lines.append(("", False))
    return lines


def _page_stream(lines: list[tuple[str, bool]], page_number: int) -> bytes:
    commands = ["BT", "/F1 11 Tf", "50 760 Td"]
    for text, heading in lines:
        if heading:
            commands.append("/F1 12 Tf")
        commands.append(f"({_escape(text)}) Tj")
        commands.append("0 -16 Td")
        if heading:
            commands.append("/F1 11 Tf")
    commands.extend(["0 -10 Td", f"(Page {page_number}) Tj", "ET"])
    return "\n".join(commands).encode("latin-1")


def build_pdf() -> None:
    source_lines = _lines()
    per_page = 40
    pages = [source_lines[index:index + per_page] for index in range(0, len(source_lines), per_page)]
    objects: list[bytes] = []
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    page_object_ids = [4 + index * 2 for index in range(len(pages))]
    objects.append(f"<< /Type /Pages /Kids [{' '.join(f'{item} 0 R' for item in page_object_ids)}] /Count {len(pages)} >>".encode())
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for index, page in enumerate(pages):
        page_id = page_object_ids[index]
        content_id = page_id + 1
        objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> /Contents {content_id} 0 R >>".encode())
        stream = _page_stream(page, index + 1)
        objects.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{number} 0 obj\n".encode())
        output.extend(obj)
        output.extend(b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    output.extend(b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets[1:]))
    output.extend(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    OUTPUT.write_bytes(output)


if __name__ == "__main__":
    build_pdf()
    print(OUTPUT)
