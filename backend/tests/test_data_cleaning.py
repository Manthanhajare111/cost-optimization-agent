import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from costopt.api.app import create_app
from costopt.pipeline.workforce_uploads import _workbook_bytes, get_upload

@pytest.fixture(autouse=True)
def disable_live_explanations(monkeypatch):
    from costopt.config import settings
    monkeypatch.setattr(settings, "agent_llm_enabled", False)


COLUMNS = ("SOW Reference", "Delivery Countries", "E1", "E2", "E3", "E4", "E5", "Worker Total", "Annual Value EUR")


def row(**extra):
    return {"SOW Reference": "as 010", "Delivery Countries": "de", "E1": "1.0", "E2": "1", "E3": "0", "E4": "0", "E5": "0", "Worker Total": "2", "Annual Value EUR": "EUR 120,000", **extra}


def upload(client, rows, columns=COLUMNS):
    content = _workbook_bytes(columns, rows)
    response = client.post("/api/v1/workforce/upload-custom/excel?scenario_id=scn-001&filename=proposal.xlsx", content=content)
    assert response.status_code == 200, response.text
    return response.json(), content


def propose(client, source, **extra):
    response = client.post(f"/api/v1/workforce/cleaning/{source['upload_id']}/propose", json={"scenario_id": "scn-001", **extra})
    assert response.status_code == 200, response.text
    return response.json()


def approve(client, run, **extra):
    return client.post(f"/api/v1/workforce/cleaning-runs/{run['run_id']}/approve", json={"scenario_id": "scn-001", "reviewer_name": "Data reviewer", "approved": True, **extra})


def supporting_pack(client, sow="AS-010", rate_countries=("Germany", "India"), rate_currency="EUR",
                    rate_levels=("E1", "E2")):
    columns = ("document_kind", "sow_reference", "status", "role", "level", "country", "currency", "rate_unit", "bill_rate")
    rates = [{"document_kind": "rate_card", "sow_reference": sow, "status": "APPROVED", "level": level,
              "role": "Engineer", "country": country, "currency": rate_currency, "rate_unit": "day", "bill_rate": "500"}
             for country in rate_countries for level in rate_levels]
    files = [("rates.xlsx", _workbook_bytes(columns, rates)),
             ("contract.txt", f"document_kind: contractual_evidence\nsow_reference: {sow}\nstatus: APPROVED\n".encode()),
             ("delivery.txt", f"document_kind: delivery_constraints\nsow_reference: {sow}\nstatus: APPROVED\n".encode())]
    result = []
    for filename, content in files:
        response = client.post("/api/v1/workforce/upload-custom/supporting", params={"scenario_id": "scn-001", "filename": filename}, content=content)
        assert response.status_code == 200, response.text
        result.append(response.json()["upload_id"])
    return result


def test_cleaning_approval_preserves_original_and_is_idempotent(isolated_db):
    client = TestClient(create_app())
    source, content = upload(client, [row()])
    assert source["cleaning_status"] == "pending"
    assert source["rows"] == []
    run = propose(client, source)
    assert run["ready"]
    assert run["candidate_rows"][0]["sow reference"] == "AS-010"
    assert run["candidate_rows"][0]["delivery countries"] == "Germany"
    assert run["candidate_rows"][0]["annual value eur"] == "120000"
    assert run["original_rows"][0]["SOW Reference"] == "as 010"
    assert approve(client, run, approved=False).status_code == 400
    response = approve(client, run)
    assert response.status_code == 200, response.text
    cleaned = response.json()
    assert cleaned["upload_id"] != source["upload_id"]
    assert cleaned["original_upload_id"] == source["upload_id"]
    assert cleaned["matched_count"] == 2
    assert cleaned["original_preview_rows"] == source["preview_rows"]
    assert cleaned["cleaning_audit"][-1]["reviewer"] == "Data reviewer"
    assert get_upload(source["upload_id"])["cleaning_status"] == "pending"
    assert approve(client, run).json()["upload_id"] == cleaned["upload_id"]
    with sqlite3.connect(isolated_db) as connection:
        assert connection.execute("SELECT content FROM workforce_cleaning_files WHERE upload_id=?", (source["upload_id"],)).fetchone()[0] == content


def test_consolidated_preview_joins_validated_document_pack(isolated_db):
    client = TestClient(create_app())
    source, _ = upload(client, [row()])
    cleaned = approve(client, propose(client, source)).json()
    support = supporting_pack(client)
    response = client.post("/api/v1/workforce/consolidated-preview", json={
        "scenario_id": "scn-001", "upload_id": cleaned["upload_id"],
        "supporting_upload_ids": support, "destination_country_ids": ["loc-india"],
    })
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "consolidated"
    assert result["sow_options"] == ["AS-010"]
    assert result["row_count"] == 2
    assert {item["E-Level"] for item in result["rows"]} == {"E1", "E2"}
    assert {item["Source Country"] for item in result["rows"]} == {"Germany"}
    assert {item["Destination Country"] for item in result["rows"]} == {"India"}
    assert {item["Source Rate (EUR/day)"] for item in result["rows"]} == {601.4, 679.0}
    assert all(item["Destination Rate (EUR/day)"] == 500 for item in result["rows"])
    assert all(item["Contract Evidence"] == "Available" for item in result["rows"])
    assert all(item["Delivery Constraints"] == "Available" for item in result["rows"])
    assert all(item["Recommendation Input"] == "Ready" for item in result["rows"])


def test_destination_only_rate_card_uses_governed_backend_source_rates(isolated_db):
    client = TestClient(create_app())
    source, _ = upload(client, [row(**{"Annual Value EUR": ""})])
    cleaned = approve(client, propose(client, source)).json()
    support = supporting_pack(client, rate_countries=("India",), rate_currency="GBP")
    request = {
        "scenario_id": "scn-001", "upload_id": cleaned["upload_id"],
        "source_filter": {"column": "sow reference", "contains": "AS-010"},
        "supporting_upload_ids": support, "destination_country_ids": ["loc-india"],
    }
    validation = client.post("/api/v1/workforce/validate-upload", json=request)
    assert validation.status_code == 200, validation.text
    assert validation.json()["ready"]
    preview = client.post("/api/v1/workforce/consolidated-preview", json=request)
    assert preview.status_code == 200, preview.text
    assert {item["Source Rate (EUR/day)"] for item in preview.json()["rows"]} == {601.4, 679.0}
    assert all(item["Destination Rate (GBP/day)"] == 500 for item in preview.json()["rows"])
    analysis = client.post("/api/v1/workforce/analyze", json={
        "case_id": "right_shoring", "scenario_id": "scn-001", "source_ids": ["excel"],
        "source_modes": {"excel": "manual"}, "source_upload_ids": {"excel": cleaned["upload_id"]},
        "offshore_location_ids": ["loc-india"], "supporting_upload_ids": support,
        "source_filters": {"excel": {"column": "sow reference", "contains": "AS-010"}},
    })
    assert analysis.status_code == 200, analysis.text
    details = analysis.json()["options"][0]["resource_details"]
    assert {item["current_rate_eur"] for item in details} == {601.4, 679.0}
    assert {item["projected_rate_eur"] for item in details} == {585.0}
    assert any("planning FX assumption" in gap for gap in analysis.json()["data_gaps"])


def test_as030_germany_to_india_runs_end_to_end_with_other_india_sows_in_workbook(isolated_db):
    client = TestClient(create_app())
    source, _ = upload(client, [
        row(**{"SOW Reference": "AS-030", "Delivery Countries": "Germany", "E1": "0", "E2": "1",
               "E3": "2", "Worker Total": "3", "Annual Value EUR": ""}),
        row(**{"SOW Reference": "AS-001", "Delivery Countries": "India", "E1": "0", "E2": "1",
               "E3": "0", "Worker Total": "1", "Annual Value EUR": ""}),
    ])
    cleaned = approve(client, propose(client, source)).json()
    support = supporting_pack(client, sow="AS-030", rate_countries=("India",), rate_currency="GBP",
                              rate_levels=("E2", "E3"))
    analysis = client.post("/api/v1/workforce/analyze", json={
        "case_id": "right_shoring", "scenario_id": "scn-001", "source_ids": ["excel"],
        "source_modes": {"excel": "manual"}, "source_upload_ids": {"excel": cleaned["upload_id"]},
        "offshore_location_ids": ["loc-india"], "supporting_upload_ids": support,
        "source_filters": {"excel": {"column": "sow reference", "contains": "AS-030"}},
        "move_counts_by_sow_level": {"AS-030|E2": 1, "AS-030|E3": 2},
    })
    assert analysis.status_code == 200, analysis.text
    result = analysis.json()
    assert result["options"] and result["options"][0]["location_name"] == "India"
    details = result["options"][0]["resource_details"]
    assert len(details) == 3
    assert {item["sow_reference"] for item in details} == {"AS-030"}
    assert {item["current_location_id"] for item in details} == {"loc-germany"}


def test_consolidated_preview_shows_partial_package_and_missing_evidence(isolated_db):
    client = TestClient(create_app())
    source, _ = upload(client, [row()])
    cleaned = approve(client, propose(client, source)).json()
    rate_card, contract, _delivery_constraints = supporting_pack(client)
    response = client.post("/api/v1/workforce/consolidated-preview", json={
        "scenario_id": "scn-001", "upload_id": cleaned["upload_id"],
        "supporting_upload_ids": [rate_card, contract], "destination_country_ids": ["loc-india"],
    })
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["row_count"] == 2
    assert not result["ready"]
    assert all(item["Source Rate (EUR/day)"] != "Missing" for item in result["rows"])
    assert all(item["Destination Rate (EUR/day)"] != "Missing" for item in result["rows"])
    assert all(item["Contract Evidence"] == "Available" for item in result["rows"])
    assert all(item["Delivery Constraints"] == "Missing" for item in result["rows"])
    assert all(item["Recommendation Input"] == "Needs attention" for item in result["rows"])


def test_multi_country_sow_uses_germany_and_retains_other_countries_as_context(isolated_db):
    client = TestClient(create_app())
    source, _ = upload(client, [row(**{"Delivery Countries": "Germany, Georgia, Russia"})])
    run = propose(client, source)
    assert run["ready"]
    assert not [item for item in run["issues"] if item["field"] == "delivery countries"]
    cleaned = approve(client, run).json()
    assert cleaned["projects"][0]["delivery_countries"] == "Germany, Georgia, Russia"
    assert cleaned["projects"][0]["source_country"] == "Germany"
    assert {item["current_location_id"] for item in cleaned["rows"]} == {"loc-germany"}
    support = supporting_pack(client)
    validation = client.post("/api/v1/workforce/validate-upload", json={
        "scenario_id": "scn-001", "upload_id": cleaned["upload_id"],
        "source_filter": {"column": "sow reference", "contains": "AS-010"},
        "supporting_upload_ids": support, "destination_country_ids": ["loc-india"],
    }).json()
    assert validation["ready"]
    assert any(item["category"] == "Source location" and "Germany" in item["message"] for item in validation["checks"])


def test_unapproved_upload_and_legacy_upload_cannot_recommend(isolated_db):
    client = TestClient(create_app())
    source, _ = upload(client, [row()])
    request = {"case_id": "right_shoring", "scenario_id": "scn-001", "source_ids": ["excel"],
               "source_modes": {"excel": "manual"}, "source_upload_ids": {"excel": source["upload_id"]},
               "offshore_location_ids": ["loc-india"], "source_filters": {"excel": {"column": "sow reference", "contains": "AS-010"}}}
    response = client.post("/api/v1/workforce/analyze", json=request)
    assert response.status_code == 400
    assert "cleaning approval" in response.json()["detail"]
    legacy = dict(source)
    legacy.pop("cleaning_status")
    with sqlite3.connect(isolated_db) as connection:
        connection.execute("UPDATE workforce_uploads SET payload_json=? WHERE upload_id=?", (json.dumps(legacy), source["upload_id"]))
    assert client.post("/api/v1/workforce/analyze", json=request).status_code == 400
    run = propose(client, source)
    approved = approve(client, run).json()
    request["source_upload_ids"]["excel"] = approved["upload_id"]
    support = supporting_pack(client)
    request["supporting_upload_ids"] = support
    validation = client.post("/api/v1/workforce/validate-upload", json={"scenario_id": "scn-001", "upload_id": approved["upload_id"], "source_filter": request["source_filters"]["excel"], "supporting_upload_ids": support, "destination_country_ids": ["loc-india"]}).json()
    assert all(item["category"] != "Data cleaning" for item in validation["checks"])
    assert validation["ready"]
    response = client.post("/api/v1/workforce/analyze", json=request)
    assert response.status_code == 200, response.text
    assert sum(len(option["resource_details"]) for option in response.json()["options"]) == 2
    assert response.json()["sources"][0]["cleaning"]["original_upload_id"] == source["upload_id"]


@pytest.mark.parametrize("field,value", [("E1", ""), ("E1", "-1"), ("E1", "1.5"), ("E2", "NaN"), ("Worker Total", "9"), ("Annual Value EUR", "bad")])
def test_invalid_values_are_not_silently_fixed(isolated_db, field, value):
    client = TestClient(create_app())
    source, _ = upload(client, [row(**{field:value})])
    run = propose(client, source)
    assert not run["ready"]
    assert run["counts"]["errors"] > 0
    assert approve(client, run).status_code == 400
    assert source["preview_rows"][0][field] == value


def test_summary_row_is_ignored_and_blank_sow_has_one_clear_error(isolated_db):
    client = TestClient(create_app())
    summary = row(**{"SOW Reference": "Total", "Delivery Countries": "", "E1": "2", "E2": "1", "Worker Total": "3"})
    blank = row(**{"SOW Reference": "", "Delivery Countries": "Germany"})
    source, _ = upload(client, [row(), summary, blank])
    run = propose(client, source)
    assert not run["ready"]
    assert not any(item["row"] == 2 for item in run["issues"])
    sow_issues = [item for item in run["issues"] if item["row"] == 3 and item["field"] == "sow reference"]
    assert [item["message"] for item in sow_issues] == ["Required value is blank."]
    assert run["counts"]["accepted"] == 1


def test_blank_proposal_annual_value_is_supplied_by_separate_rate_card(isolated_db):
    client = TestClient(create_app())
    source, _ = upload(client, [row(**{"Annual Value EUR": ""})])
    run = propose(client, source)
    assert run["ready"]
    assert not any(item["field"] == "annual value eur" for item in run["issues"])
    approved = approve(client, run).json()
    assert {item["current_rate_eur"] for item in approved["rows"]} == {0}
    support = supporting_pack(client)
    request = {"case_id": "right_shoring", "scenario_id": "scn-001", "source_ids": ["excel"],
               "source_modes": {"excel": "manual"}, "source_upload_ids": {"excel": approved["upload_id"]},
               "supporting_upload_ids": support, "offshore_location_ids": ["loc-india"],
               "source_filters": {"excel": {"column": "sow reference", "contains": "AS-010"}}}
    response = client.post("/api/v1/workforce/analyze", json=request)
    assert response.status_code == 200, response.text


def test_duplicate_exclusion_and_manual_edit_are_audited(isolated_db):
    client = TestClient(create_app())
    source, _ = upload(client, [row(), row(E1="", **{"Worker Total":"2"})])
    first = propose(client, source)
    assert not first["ready"]
    second = propose(client, source, base_run_id=first["run_id"], excluded_rows=[2], reason="Verified second row is a duplicate.")
    assert second["ready"]
    assert second["counts"]["excluded"] == 1
    rejected = propose(client, source, base_run_id=second["run_id"], excluded_rows=[2], edits=[{"row":1,"field":"e1","value":"-1"}], reason="Review invalid workforce count.")
    assert not rejected["ready"]
    final = propose(client, source, base_run_id=rejected["run_id"], excluded_rows=[2], edits=[{"row":1,"field":"e1","value":"1"}], reason="Workforce count confirmed from source.")
    response = approve(client, final)
    assert response.status_code == 200, response.text
    assert len(response.json()["cleaning_audit"]) == 5
    assert response.json()["matched_count"] == 2
    assert get_upload(source["upload_id"])["preview_rows"][1]["E1"] == ""


def test_missing_and_duplicate_columns_block_approval(isolated_db):
    client = TestClient(create_app())
    for columns in (tuple(key for key in COLUMNS if key != "E5"), (*COLUMNS, "e1")):
        source, _ = upload(client, [row()], columns)
        run = propose(client, source)
        assert not run["ready"]
        assert run["structural_issues"]
        assert approve(client, run).status_code == 400


def test_revision_scope_and_manual_change_reason(isolated_db):
    client = TestClient(create_app())
    first, _ = upload(client, [row()])
    other, _ = upload(client, [row()])
    run = propose(client, first)
    wrong = client.post(f"/api/v1/workforce/cleaning/{other['upload_id']}/propose", json={"scenario_id":"scn-001", "base_run_id":run["run_id"]})
    assert wrong.status_code == 400
    assert approve(client, run, scenario_id="scn-002").status_code == 400
    response = client.post(f"/api/v1/workforce/cleaning/{first['upload_id']}/propose", json={"scenario_id":"scn-001", "base_run_id":run["run_id"], "edits":[{"row":1,"field":"e1","value":"2"}]})
    assert response.status_code == 400


def test_csv_proposal_uses_same_cleaning_gate(isolated_db):
    client = TestClient(create_app())
    content = b"SOW Reference,Delivery Countries,E1,E2,E3,E4,E5,Worker Total,Daily Rate EUR\nAS-1,Germany,1,0,0,0,0,1,850\n"
    source = client.post("/api/v1/workforce/upload-custom/excel?scenario_id=scn-001&filename=proposal.csv", content=content).json()
    run = propose(client, source)
    assert run["ready"]
    cleaned = approve(client, run).json()
    assert cleaned["rows"][0]["current_rate_eur"] == 850


def test_rate_card_is_not_accepted_as_primary_workforce_workbook(isolated_db):
    client = TestClient(create_app())
    columns = ("sow_reference", "country", "level", "currency", "rate_unit", "bill_rate")
    rate = dict(zip(columns, ("AS-010", "Germany", "E1", "EUR", "day", "500")))
    response = client.post("/api/v1/workforce/upload-custom/excel?scenario_id=scn-001&filename=Rate_Card.xlsx",
                           content=_workbook_bytes(columns, [rate]))
    assert response.status_code == 400
    assert "Upload documents for validation" in response.json()["detail"]


def test_cleaning_agent_is_exposed_separately_from_calculation_plan(isolated_db):
    client = TestClient(create_app())
    agents = client.get("/api/v1/agents").json()
    assert any(item["name"] == "data_cleaning" for item in agents)
    assert any(item["name"] == "data_validation" for item in agents)
    assert len(agents) == 12


def test_hash_worker_total_alias_is_checked(isolated_db):
    client = TestClient(create_app())
    columns = tuple("# Workers" if key == "Worker Total" else key for key in COLUMNS)
    source, _ = upload(client, [row(**{"# Workers": "99"})], columns)
    run = propose(client, source)
    assert not run["ready"]
    assert any(item["field"] == "worker total" and "differs" in item["message"] for item in run["issues"])


def test_first_governed_delivery_country_drives_resource_location(isolated_db):
    client = TestClient(create_app())
    source, _ = upload(client, [row(**{"Delivery Countries": "India"})])
    run = propose(client, source)
    assert run["ready"]
    assert not any("Germany source scope" in item["message"] for item in run["issues"])
    approved = approve(client, run).json()
    assert approved["projects"][0]["delivery_countries"] == "India"
    assert approved["projects"][0]["source_country"] == "India"
    assert {item["current_location_id"] for item in approved["rows"]} == {"loc-india"}


def test_country_missing_from_location_master_is_allowed_as_scope_context(isolated_db):
    client = TestClient(create_app())
    source, _ = upload(client, [row(**{"Delivery Countries": "China"})])
    run = propose(client, source)
    assert run["ready"]
    assert not any(item["field"] == "delivery countries" for item in run["issues"])
    approved = approve(client, run).json()
    assert approved["projects"][0]["delivery_countries"] == "China"
    assert approved["projects"][0]["source_country"] == "Germany"
    assert {item["current_location_id"] for item in approved["rows"]} == {"loc-germany"}


def test_ukraine_is_a_supported_source_location(isolated_db):
    client = TestClient(create_app())
    source, _ = upload(client, [row(**{"Delivery Countries": "Ukraine"})])
    run = propose(client, source)
    assert not any(item["field"] == "delivery countries" and "location master" in item["message"] for item in run["issues"])


def test_not_applicable_delivery_country_is_missing_not_split_into_letters(isolated_db):
    client = TestClient(create_app())
    source, _ = upload(client, [row(**{"Delivery Countries": "n/a"})])
    run = propose(client, source)
    assert any(item["field"] == "delivery countries" and item["message"] == "Required value is blank." for item in run["issues"])
    assert not any("a, n" in item["message"] for item in run["issues"])
