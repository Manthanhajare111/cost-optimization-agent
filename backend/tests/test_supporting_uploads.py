from pathlib import Path
import pytest
from costopt.pipeline.workforce_uploads import ingest_supporting_file, inspect_supporting_uploads, validate_supporting_uploads, get_upload, _workbook_bytes

PACK = Path(__file__).resolve().parents[2] / "docs" / "Stage1_Upload_Pack"
def test_generic_as001_rate_card_is_valid_without_sow_reference(isolated_db):
    columns = ("document_kind", "status", "role", "grade", "delivery_country", "currency", "unit",
               "standard_rate_gbp", "project_discount_pct", "net_rate_gbp", "rate_effective_from", "rate_effective_to")
    rows = [{"document_kind": "rate_card", "status": "APPROVED", "role": "Engineer",
             "grade": level, "delivery_country": country, "currency": "GBP", "unit": "day",
             "standard_rate_gbp": "625", "project_discount_pct": "0.2", "net_rate_gbp": "500",
             "rate_effective_from": "2026-01-01", "rate_effective_to": "2027-12-31"}
            for country in ("India", "Poland") for level in ("E2", "E3", "E4", "E5")]
    record = ingest_supporting_file("scn-001", "Fictional_Rate_Card_Skyline_CRM.xlsx",
                                    _workbook_bytes(columns, rows), "rate_card")
    assert len(record["rows"]) == 8
    assert {row["currency"] for row in record["rows"]} == {"GBP"}
    assert {row["level"] for row in record["rows"]} == {"E2", "E3", "E4", "E5"}
    assert all(not row.get("sow_reference") for row in record["rows"])
    result = inspect_supporting_uploads(
        "scn-001", [record["upload_id"]], "AS-001", ["Poland"], ["E2", "E3", "E4", "E5"], ["India"]
    )
    invalid_rate_categories = {"Missing information", "Rate values", "Rate units", "E-level", "Rate coverage", "Rate duplicates"}
    assert not [check for check in result["checks"]
                if check["status"] == "critical" and check["category"] in invalid_rate_categories]
    assert any(check["category"] == "Rate discount and net rate" and check["status"] == "pass" for check in result["checks"])
    assert any(check["category"] == "Rate effective dates" and check["status"] == "pass" for check in result["checks"])


def test_rate_card_rejects_bad_discount_net_rate_and_expired_date(isolated_db):
    columns = ("role", "grade", "delivery_country", "currency", "unit", "standard_rate_gbp",
               "project_discount_pct", "net_rate_gbp", "rate_effective_from", "rate_effective_to")
    row = {"role": "Engineer", "grade": "E3", "delivery_country": "India", "currency": "GBP", "unit": "day",
           "standard_rate_gbp": "625", "project_discount_pct": "0.2", "net_rate_gbp": "600",
           "rate_effective_from": "2025-01-01", "rate_effective_to": "2025-12-31"}
    record = ingest_supporting_file("scn-001", "expired-rate.xlsx", _workbook_bytes(columns, [row]), "rate_card")
    result = inspect_supporting_uploads("scn-001", [record["upload_id"]], "AS-001", ["India"], ["E3"], ["India"])
    assert any(check["category"] == "Rate discount and net rate" and check["status"] == "critical" for check in result["checks"])
    assert any(check["category"] == "Rate expiry" and check["status"] == "critical" for check in result["checks"])

def test_pack_persists_and_scopes_attachments(isolated_db):
    records = [ingest_supporting_file("scn-001", name, (PACK / name).read_bytes()) for name in ("Rate_Card.xlsx", "Contractual_Evidence.docx", "Delivery_Constraints.docx")]
    ids = [r["upload_id"] for r in records]
    validate_supporting_uploads("scn-001", ids)
    assert {r["data_kind"] for r in records} == {"rate_card", "contractual_evidence", "delivery_constraints"}
    assert len(records[0]["rows"]) == 20
    assert get_upload(ids[0])["applied_fields"] == []
    checks = inspect_supporting_uploads("scn-001", ids, "AS-220", ["India"], ["E1"], ["Germany"])
    assert not any(check["category"] == "Rate units" for check in checks["checks"])
    with pytest.raises(ValueError, match="scenario"):
        validate_supporting_uploads("scn-002", ids)
    with pytest.raises(ValueError, match="distinct"):
        validate_supporting_uploads("scn-001", [ids[0], ids[0]])
    second = ingest_supporting_file("scn-001", "rate.xlsx", (PACK / "Rate_Card.xlsx").read_bytes())
    with pytest.raises(ValueError, match="one document"):
        validate_supporting_uploads("scn-001", [ids[0], second["upload_id"]])

@pytest.mark.parametrize("filename,content", [("bad.docx", b"invalid"), ("bad.txt", b"no markers"), ("bad.pdf", b"pdf"), ("empty.xlsx", b""), ("large.txt", b"a"*2000001)], ids=["corrupt-docx", "missing-markers", "unsupported-pdf", "empty", "oversized"])
def test_invalid_documents_rejected(isolated_db, filename, content):
    with pytest.raises(ValueError):
        ingest_supporting_file("scn-001", filename, content)

def test_invalid_rate_rejected(isolated_db):
    row = dict(document_kind="rate_card", sow_reference="AS-220", status="sample", level="E1", country="Germany", currency="EUR", rate_unit="day", bill_rate="NaN")
    with pytest.raises(ValueError, match="bill_rate"):
        ingest_supporting_file("scn-001", "rate.xlsx", _workbook_bytes(tuple(row), [row]))


def test_cross_document_validation_reports_missing_and_selected_sow_gaps(isolated_db):
    columns = ("document_kind", "sow_reference", "status", "level", "country", "currency", "rate_unit", "bill_rate")
    rates = [{"document_kind": "rate_card", "sow_reference": "AS-220", "status": "APPROVED", "level": "E1",
              "country": "Germany", "currency": "EUR", "rate_unit": "day", "bill_rate": "500"}]
    rate = ingest_supporting_file("scn-001", "rate.xlsx", _workbook_bytes(columns, rates))
    missing = inspect_supporting_uploads("scn-001", [rate["upload_id"]], "AS-220", ["India"], ["E1"])
    assert not missing["ready"]
    assert set(missing["missing_information"]) >= {"contractual evidence", "delivery constraints"}
    assert any(check["category"] == "Rate coverage" and check["status"] == "critical" for check in missing["checks"])

    contract = ingest_supporting_file("scn-001", "contract.txt", b"document_kind: contractual_evidence\nsow_reference: AS-999\nstatus: APPROVED\n")
    delivery = ingest_supporting_file("scn-001", "delivery.txt", b"document_kind: delivery_constraints\nsow_reference: AS-220\nstatus: PENDING\n")
    result = inspect_supporting_uploads("scn-001", [rate["upload_id"], contract["upload_id"], delivery["upload_id"]], "AS-220", [], ["E1"])
    assert not result["ready"]
    assert any(check["category"] == "SOW consistency" and check["status"] == "critical" for check in result["checks"])
    assert any(check["category"] == "Delivery constraints status" and check["status"] == "warning" for check in result["checks"])


def test_supporting_upload_api(isolated_db):
    from fastapi.testclient import TestClient
    from costopt.api.app import create_app
    client = TestClient(create_app())
    response = client.post("/api/v1/workforce/upload-custom/supporting", params={"scenario_id": "scn-001", "filename": "Rate_Card.xlsx"}, content=(PACK / "Rate_Card.xlsx").read_bytes(), headers={"Content-Type": "application/octet-stream"})
    assert response.status_code == 200
    assert response.json()["data_kind"] == "rate_card"
    response = client.post("/api/v1/workforce/upload-custom/supporting", params={"scenario_id": "scn-001", "filename": "bad.docx"}, content=b"broken")
    assert response.status_code == 400
