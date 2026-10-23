"""Generate clearly labelled synthetic Stage 1 supporting documents."""
from pathlib import Path
import sys
import zipfile
from xml.sax.saxutils import escape
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from costopt.pipeline.workforce_uploads import _workbook_bytes

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "Stage1_Upload_Pack"

def docx(path, lines):
    namespace = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body = "".join(f'<w:p><w:r><w:t xml:space="preserve">{escape(line)}</w:t></w:r></w:p>' for line in lines)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        z.writestr("_rels/.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        z.writestr("word/document.xml", f'<w:document xmlns:w="{namespace}"><w:body>{body}<w:sectPr/></w:body></w:document>')

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    columns = ("document_kind", "sow_reference", "supplier_id", "level", "country", "currency", "rate_unit", "bill_rate", "valid_from", "valid_to", "status", "basis")
    rows = []
    for country, factor in [("Germany", 1), ("India", .58), ("Poland", .74), ("Romania", .69)]:
        for level, rate in {"E1":650, "E2":760, "E3":900, "E4":1030, "E5":1180}.items():
            rows.append(dict(zip(columns, ("rate_card", "AS-220", "DEMO-SUPPLIER", level, country, "EUR", "person_day_8_hours", round(rate*factor, 2), "2026-01-01", "2026-12-31", "SYNTHETIC_UNAPPROVED", "Illustrative planning rate; excludes tax and transition cost"))))
    (OUT / "Rate_Card.xlsx").write_bytes(_workbook_bytes(columns, rows))
    common = ["SYNTHETIC DEMO - NOT SIGNED OR APPROVED", "sow_reference: AS-220", "scenario_id: scn-001", "supplier_id: DEMO-SUPPLIER", "status: SYNTHETIC_UNAPPROVED", "Version: 1.0 | Prepared: 2026-10-19", "Scope: illustrative Germany delivery transition; replace all sample terms with verified evidence."]
    docx(OUT / "Contractual_Evidence.docx", ["CostOpt - Contractual Evidence", "document_kind: contractual_evidence", *common,
        "CE-01 | Offshore delivery | Sample clause 4.2: Software engineering may be delivered offshore only after the customer approves the destination and scope in writing.",
        "CE-02 | Approval | Sample clause 7.1: No delivery relocation before written customer approval. Approval record: NOT PROVIDED. Approver/date: PENDING.",
        "CE-03 | Data residency | Sample clause 5.4: EU customer PII remains in approved EU-controlled workflows. PII access from a new location requires a separate assessment; no permission is inferred.",
        "CE-04 | Commercial basis | Rate_Card.xlsx contains illustrative EUR person-day rates for E1-E5. Rates are not contracted and require supplier confirmation.",
        "CE-05 | Evidence provenance | No executed agreement, signature or amendment is represented by this sample. Original document, page and clause reference: TO BE PROVIDED.",
        "Review owner: contract manager | Review outcome: PENDING | Signature: NOT SIGNED"])
    docx(OUT / "Delivery_Constraints.docx", ["CostOpt - Delivery Constraints", "document_kind: delivery_constraints", *common,
        "DC-01 | Source/destination | Current source: Germany. Candidate locations: India, Poland, Romania. Candidates are not approved destinations.",
        "DC-02 | Coverage | Illustrative requirement: at least 4 working hours overlap with the Germany team, Monday-Friday. Validate local calendars and daylight-saving schedules.",
        "DC-03 | Service continuity | Illustrative maximum planned downtime: 2 hours per cutover. Customer sign-off and tested rollback are required.",
        "DC-04 | Knowledge transfer | Illustrative duration: 20 business days with source and destination leads. Exit requires runbook review and successful shadow support.",
        "DC-05 | Staffing | E1-E5 counts must reconcile to the selected Proposal SOW. Destination capacity and start dates: UNVERIFIED. Do not assume availability from rate coverage.",
        "DC-06 | Retained work | Keep customer-facing leadership and restricted PII activities in approved locations pending a role-by-role assessment.",
        "DC-07 | Security | Access approval, approved devices and verified data-processing controls are required before transition.",
        "DC-08 | Dependencies | Written customer approval, confirmed rates, security assessment and capacity evidence must be completed before implementation.",
        "Review owner: delivery lead | Review outcome: PENDING | Sign-off: NOT APPROVED"])
    (OUT / "README.md").write_text("""# Stage 1 sample upload pack

All three files are synthetic, unapproved examples for AS-220 / scn-001, not real contractual evidence.

1. Upload the existing Proposal workforce workbook in Stage 1 as usual.
2. In Supporting documents, select Rate_Card.xlsx, Contractual_Evidence.docx and Delivery_Constraints.docx together.
3. Expand each document to review its contents. A new file of the same type replaces the selected attachment; Remove detaches it from the next analysis.
4. Complete workforce cleaning, select the SOW and continue analysis.

Attachments are persisted and their IDs are saved in the analysis input. They are for human review only: the current calculation does not consume their rates or enforce their delivery rules. The existing governed policy remains in effect. This pack does not make an analysis approved.

Rate workbook: 20 illustrative EUR person-day rates (8-hour days), E1-E5 across Germany, India, Poland and Romania. Replace sample scope, supplier, validity dates and prices with verified inputs before business use. Contract and delivery documents contain numbered review items and explicit pending approvals.

Supported attachments: XLSX/CSV with document_kind, sow_reference and status columns; rate cards also require level, country, currency, rate_unit and bill_rate. DOCX/TXT must include document_kind and sow_reference marker lines as shown in these samples. Maximum 2 MB per file; one attachment per type, three per analysis. PDF is not supported by this upload flow.
""", encoding="utf-8")
    print(OUT)

if __name__ == "__main__":
    main()
