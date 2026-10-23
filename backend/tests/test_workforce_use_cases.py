import io
import zipfile
from pathlib import Path
import pytest

from fastapi.testclient import TestClient

from costopt.api.app import create_app
from costopt.pipeline.workforce_uploads import TEMPLATE_COLUMNS, _workbook_bytes, _xlsx_rows


def test_source_country_is_exposed_and_validated(isolated_db):
    client = TestClient(create_app())
    context = client.get("/api/v1/workforce/context/scn-001")
    assert context.status_code == 200
    assert context.json()["source_locations"] == [
        {"location_id": "loc-germany", "country": "Germany", "resource_count": 15}
    ]
    request = {"case_id": "right_shoring", "scenario_id": "scn-001",
               "source_ids": ["fieldglass"], "offshore_location_ids": ["loc-india"]}
    valid = client.post("/api/v1/workforce/analyze", json={**request,
        "source_location_id": "loc-germany"})
    assert valid.status_code == 200, valid.text
    assert valid.json()["input"]["source_location_id"] == "loc-germany"
    assert valid.json()["project_title"] == "Optimized shoring: Germany to India"
    assert all(detail["current_location_id"] == "loc-germany"
               for detail in valid.json()["options"][0]["resource_details"])
    invalid = client.post("/api/v1/workforce/analyze", json={**request,
        "source_location_id": "loc-india"})
    assert invalid.status_code == 400


def test_optimized_shoring_withholds_destination_when_evidence_is_missing(isolated_db):
    client = TestClient(create_app())
    response = client.post("/api/v1/workforce/analyze", json={
        "case_id": "right_shoring", "scenario_id": "scn-001",
        "source_ids": ["fieldglass"], "source_location_id": "loc-germany",
        "offshore_location_ids": ["loc-india", "loc-philippines"],
    })
    assert response.status_code == 200, response.text
    analysis = response.json()
    assert analysis["decision_status"] == "insufficient_evidence"
    assert analysis["recommended_option_id"] is None
    assert analysis["blocking_reasons"]
    assert all(option["status"] != "eligible" for option in analysis["options"])
    assert all(option["resource_details"] for option in analysis["options"])
    assert all(len(option["agent_stages"]) == 10 for option in analysis["options"])
    assert all(
        {stage["name"] for stage in option["agent_stages"]}
        >= {"planner", "retriever", "contract", "optimization", "reporting", "approval"}
        for option in analysis["options"]
    )
    review = client.post(f"/api/v1/workforce/analyses/{analysis['analysis_id']}/reviews", json={
        "reviewer_name": "Demo reviewer", "decision": "ready_for_approval",
        "selected_option_id": analysis["options"][0]["option_id"],
        "edited_recommendation": "Do not move until evidence is verified.",
        "rationale": "Target skill capacity and regulatory checks are missing.",
    })
    assert review.status_code == 400
    approval = client.post(f"/api/v1/workforce/analyses/{analysis['analysis_id']}/reviews", json={
        "reviewer_name": "Demo reviewer", "decision": "approved",
        "selected_option_id": analysis["options"][0]["option_id"],
        "edited_recommendation": "Do not move until evidence is verified.",
        "rationale": "Final approval is blocked by the same missing evidence.",
    })
    assert approval.status_code == 400


def test_analysis_title_and_review_downtime_are_saved(isolated_db):
    client = TestClient(create_app())
    response = client.post("/api/v1/workforce/analyze", json={
        "case_id": "right_shoring", "scenario_id": "scn-001",
        "project_title": "Payments · Germany to India",
        "source_ids": ["fieldglass"], "source_location_id": "loc-germany",
        "offshore_location_ids": ["loc-india"],
    })
    assert response.status_code == 200, response.text
    analysis = response.json()
    assert analysis["project_title"] == "Payments · Germany to India"
    analysis_id = analysis["analysis_id"]
    updated = client.patch(f"/api/v1/workforce/analyses/{analysis_id}/title", json={
        "project_title": "Payments India assessment",
    })
    assert updated.status_code == 200, updated.text
    assert client.get(f"/api/v1/workforce/analyses/{analysis_id}").json()["project_title"] == "Payments India assessment"
    review = client.post(f"/api/v1/workforce/analyses/{analysis_id}/reviews", json={
        "reviewer_name": "Demo reviewer", "decision": "request_changes",
        "edited_recommendation": "Confirm staffing and legal evidence first.",
        "rationale": "The transition plan needs a downtime estimate.",
        "downtime_hours": 2.5,
    })
    assert review.status_code == 200, review.text
    assert review.json()["downtime_hours"] == 2.5


@pytest.mark.parametrize("source_id", ["excel", "fieldglass"])
def test_custom_sow_overview_is_reference_evidence_not_a_rate_override(isolated_db, source_id):
    client = TestClient(create_app())
    workbook = Path(__file__).parents[2] / "docs" / "SAP_Aggr_RFI SOW Overview.xlsx"
    try:
        workbook_content = workbook.read_bytes()
    except (FileNotFoundError, PermissionError):
        pytest.skip("The optional OneDrive SOW workbook is unavailable or open in Excel.")
    response = client.post(
        f"/api/v1/workforce/upload-custom/{source_id}?scenario_id=scn-001&filename=sow.xlsx",
        content=workbook_content, headers={"Content-Type": "application/octet-stream"},
    )
    assert response.status_code == 200, response.text
    upload = response.json()
    if source_id == "excel":
        assert upload["data_kind"] == "proposal_workbook"
        assert upload["cleaning_status"] == "pending"
        assert upload["rows"] == []
        assert upload["preview_rows"]
        proposal = client.post(f"/api/v1/workforce/cleaning/{upload['upload_id']}/propose", json={"scenario_id": "scn-001"})
        assert proposal.status_code == 200, proposal.text
        assert not proposal.json()["ready"]  # This overview has no rate/annual-value column.
        blocked = client.post("/api/v1/workforce/analyze", json={
            "case_id": "right_shoring", "scenario_id": "scn-001", "source_ids": ["excel"],
            "source_modes": {"excel": "manual"}, "source_upload_ids": {"excel": upload["upload_id"]},
            "offshore_location_ids": ["loc-india"],
        })
        assert blocked.status_code == 400
        assert "cleaning approval" in blocked.json()["detail"]
        return
    assert upload["data_kind"] == "sow_overview"
    expected_sows = sum(row.get("sow reference", "").startswith("AS-") for row in
                        _xlsx_rows(workbook_content, "xl/worksheets/sheet5.xml", True))
    expected_workers = sum(row.get("worker reference", "").startswith("W-") for row in
                           _xlsx_rows(workbook_content, "xl/worksheets/sheet7.xml", True))
    assert upload["row_count"] == expected_sows
    assert upload["worker_count"] == expected_workers
    assert len(upload["columns"]) >= 17
    assert upload["columns"][0] == "SOW Reference"
    assert "Delivery Countries" in upload["columns"]
    assert len(upload["rows"]) == expected_sows
    assert list(upload["rows"][0]) == upload["columns"]
    request = {"case_id": "right_shoring", "scenario_id": "scn-001",
               "source_ids": [source_id], "offshore_location_ids": ["loc-india"]}
    custom = client.post("/api/v1/workforce/analyze", json={**request,
        "source_modes": {source_id: "manual"},
        "source_upload_ids": {source_id: upload["upload_id"]}})
    assert custom.status_code == 200, custom.text
    assert custom.json()["options"] == []
    assert custom.json()["decision_status"] == "insufficient_evidence"
    assert "no resource-level workforce rows" in custom.json()["recommendation"]
    assert custom.json()["sources"][0]["rows"] == upload["rows"]
    assert custom.json()["sources"][0]["workforce_rows_used"] == 0
    assert custom.json()["sources"][0]["evidence_rows_used"] == expected_sows
    if source_id == "excel":
        combined = client.post("/api/v1/workforce/analyze", json={
            **request, "source_ids": ["excel", "fieldglass"],
            "source_modes": {"excel": "manual", "fieldglass": "auto"},
            "source_upload_ids": {"excel": upload["upload_id"]},
        })
        assert combined.status_code == 200, combined.text
        assert len(combined.json()["options"][0]["resource_details"]) == 15
        assert [source["workforce_rows_used"] for source in combined.json()["sources"]] == [0, 15]
        assert combined.json()["sources"][0]["evidence_rows_used"] == expected_sows


def test_freeform_csv_is_profiled_without_changing_savings(isolated_db):
    client = TestClient(create_app())
    response = client.post(
        "/api/v1/workforce/upload-custom/excel?scenario_id=scn-001&filename=delivery.csv",
        content=b"role,country,comment\nDeveloper,India,Available\nArchitect,Germany,Retain\n",
        headers={"Content-Type": "application/octet-stream"},
    )
    assert response.status_code == 200, response.text
    upload = response.json()
    assert upload["data_kind"] == "freeform_evidence"
    assert upload["country_counts"] == {"India": 1, "Germany": 1}
    request = {"case_id": "right_shoring", "scenario_id": "scn-001", "source_ids": ["excel"],
               "offshore_location_ids": ["loc-india"]}
    custom = client.post("/api/v1/workforce/analyze", json={**request,
        "source_modes": {"excel": "manual"}, "source_upload_ids": {"excel": upload["upload_id"]}})
    assert custom.status_code == 200, custom.text
    assert custom.json()["options"] == []
    assert custom.json()["decision_status"] == "insufficient_evidence"


def test_freeform_xlsx_uses_headers_without_template(isolated_db):
    client = TestClient(create_app())
    workbook = _workbook_bytes(("role", "country", "comment"),
                               [{"role": "Developer", "country": "India", "comment": "Available"}])
    response = client.post(
        "/api/v1/workforce/upload-custom/excel?scenario_id=scn-001&filename=roles.xlsx",
        content=workbook, headers={"Content-Type": "application/octet-stream"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["data_kind"] == "freeform_evidence"
    assert response.json()["country_counts"] == {"India": 1}


def test_source_previews_expose_provenance_without_live_claim(isolated_db):
    client = TestClient(create_app())
    excel = client.get("/api/v1/workforce/data-preview/excel")
    fieldglass = client.get("/api/v1/workforce/data-preview/fieldglass")
    assert excel.status_code == 200
    assert excel.json()["status"] == "synthetic_fixture"
    assert excel.json()["rows"]
    assert fieldglass.status_code == 200
    assert fieldglass.json()["live_connected"] is False


def test_source_previews_are_limited_to_selected_team_with_counts(isolated_db):
    client = TestClient(create_app())
    excel = client.get("/api/v1/workforce/data-preview/excel?scenario_id=scn-001").json()
    fieldglass = client.get("/api/v1/workforce/data-preview/fieldglass?scenario_id=scn-001").json()
    ariba = client.get("/api/v1/workforce/data-preview/ariba?scenario_id=scn-001").json()
    assert excel["row_count"] == 4
    assert all(row["scenario_id"] == "scn-001" for row in excel["rows"])
    assert fieldglass["row_count"] == 15
    assert all(row["resource_id"].startswith("res-") for row in fieldglass["rows"])
    assert ariba["row_count"] == 1
    assert ariba["rows"][0]["supplier_id"] == "sup-acme-global"


def test_csv_upload_is_previewed_for_team_and_changes_cost_baseline(isolated_db):
    client = TestClient(create_app())
    baseline = client.post("/api/v1/workforce/analyze", json={
        "case_id": "right_shoring", "scenario_id": "scn-001", "source_ids": ["fieldglass"],
        "offshore_location_ids": ["loc-india"], "planned_downtime_hours": 2,
    }).json()
    body = b"resource_id,scenario_id,current_rate_eur,role,skill\nres-001,scn-001,1500,Architect,Platform architecture\nres-016,scn-002,999,Architect,Other\n"
    response = client.post("/api/v1/workforce/upload-preview?scenario_id=scn-001&filename=team.csv",
                           content=body, headers={"Content-Type": "application/octet-stream"})
    assert response.status_code == 200, response.text
    upload = response.json()
    assert upload["row_count"] == 2
    assert upload["matched_count"] == 1
    assert upload["ignored_count"] == 1
    preview = client.get(f"/api/v1/workforce/data-preview/excel?scenario_id=scn-001&upload_id={upload['upload_id']}").json()
    assert preview["rows"][0]["current_rate_eur"] == "1500"
    result = client.post("/api/v1/workforce/analyze", json={
        "case_id": "right_shoring", "scenario_id": "scn-001", "source_ids": ["excel"],
        "offshore_location_ids": ["loc-india"], "planned_downtime_hours": 2,
        "upload_id": upload["upload_id"],
    })
    assert result.status_code == 200, result.text
    assert len(result.json()["options"][0]["resource_details"]) == 1
    assert result.json()["options"][0]["resource_details"][0]["current_rate_eur"] == 1500
    assert result.json()["options"][0]["baseline_cost"] < baseline["options"][0]["baseline_cost"]
    wrong_team = client.get(f"/api/v1/workforce/data-preview/excel?scenario_id=scn-002&upload_id={upload['upload_id']}")
    assert wrong_team.status_code == 400


def test_uploaded_workforce_filter_limits_agent_population(isolated_db):
    client = TestClient(create_app())
    body = (b"resource_id,role,skill,current_rate_eur\n"
            b"res-001,Architect,Platform architecture,1200\n"
            b"res-004,Developer,Java payments,900\n")
    uploaded = client.post(
        "/api/v1/workforce/upload-preview?scenario_id=scn-001&filename=team.csv",
        content=body, headers={"Content-Type": "application/octet-stream"},
    )
    assert uploaded.status_code == 200, uploaded.text
    response = client.post("/api/v1/workforce/analyze", json={
        "case_id": "right_shoring", "scenario_id": "scn-001",
        "source_ids": ["excel"], "source_location_id": "loc-germany",
        "offshore_location_ids": ["loc-india"],
        "upload_id": uploaded.json()["upload_id"],
        "source_filters": {"excel": {"column": "role", "contains": "Developer"}},
    })
    assert response.status_code == 200, response.text
    assert [row["resource_id"] for row in response.json()["options"][0]["resource_details"]] == ["res-004"]
    assert any("workforce filter applied" in line for line in response.json()["data_gaps"])


def test_only_selected_workforce_sources_supply_agent_resources(isolated_db):
    client = TestClient(create_app())
    excel = client.post(
        "/api/v1/workforce/upload-custom/excel?scenario_id=scn-001&filename=workers.csv",
        content=b"resource_id,scenario_id,role,skill,current_rate_eur\nres-001,scn-001,Architect,Platform architecture,1500\n",
        headers={"Content-Type": "application/octet-stream"},
    )
    assert excel.status_code == 200, excel.text
    assert excel.json()["matched_count"] == 1
    fieldglass_file = _workbook_bytes(TEMPLATE_COLUMNS["fieldglass"], [{
        "resource_id": "res-004", "scenario_id": "scn-001", "role": "Developer",
        "skill": "Java payments", "current_rate_eur": "875", "availability": "active",
    }])
    fieldglass = client.post(
        "/api/v1/workforce/upload-custom/fieldglass?scenario_id=scn-001&filename=workers.xlsx",
        content=fieldglass_file, headers={"Content-Type": "application/octet-stream"},
    )
    assert fieldglass.status_code == 200, fieldglass.text
    common = {"case_id": "right_shoring", "scenario_id": "scn-001",
              "source_location_id": "loc-germany", "offshore_location_ids": ["loc-india"]}

    def analysis(**selection):
        response = client.post("/api/v1/workforce/analyze", json={**common, **selection})
        assert response.status_code == 200, response.text
        return response.json()

    excel_result = analysis(source_ids=["excel"], source_modes={"excel": "manual"},
                            source_upload_ids={"excel": excel.json()["upload_id"]})
    fieldglass_result = analysis(source_ids=["fieldglass"], source_modes={"fieldglass": "manual"},
                                 source_upload_ids={"fieldglass": fieldglass.json()["upload_id"]})
    both_result = analysis(source_ids=["excel", "fieldglass"],
                           source_modes={"excel": "manual", "fieldglass": "manual"},
                           source_upload_ids={"excel": excel.json()["upload_id"],
                                              "fieldglass": fieldglass.json()["upload_id"]})
    backend_result = analysis(source_ids=["fieldglass"], source_modes={"fieldglass": "auto"})
    excel_only = excel_result["options"][0]["resource_details"]
    fieldglass_only = fieldglass_result["options"][0]["resource_details"]
    both = both_result["options"][0]["resource_details"]
    backend_only = backend_result["options"][0]["resource_details"]
    assert {row["resource_id"] for row in excel_only} == {"res-001"}
    assert {row["resource_id"] for row in fieldglass_only} == {"res-004"}
    assert {row["resource_id"] for row in both} == {"res-001", "res-004"}
    assert len(backend_only) == 15
    assert excel_result["sources"][0]["workforce_rows_used"] == 1
    assert fieldglass_result["sources"][0]["workforce_rows_used"] == 1
    assert [source["workforce_rows_used"] for source in both_result["sources"]] == [1, 1]
    assert backend_result["sources"][0]["workforce_rows_used"] == 15
    relocated = client.post("/api/v1/workforce/analyze", json={
        **common, "source_location_id": "loc-india", "offshore_location_ids": ["loc-philippines"],
        "source_ids": ["excel"], "source_modes": {"excel": "manual"},
        "source_upload_ids": {"excel": excel.json()["upload_id"]},
    })
    assert relocated.status_code == 200, relocated.text
    assert {row["current_location_id"] for row in relocated.json()["options"][0]["resource_details"]} == {"loc-india"}


def test_xlsx_upload_preview_without_external_excel_dependency(isolated_db):
    client = TestClient(create_app())
    worksheet = ('<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                 '<sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>resource_id</t></is></c>'
                 '<c r="B1" t="inlineStr"><is><t>current_rate_eur</t></is></c>'
                 '<c r="C1" t="inlineStr"><is><t>role</t></is></c>'
                 '<c r="D1" t="inlineStr"><is><t>skill</t></is></c></row>'
                 '<row r="2"><c r="A2" t="inlineStr"><is><t>res-001</t></is></c>'
                 '<c r="B2"><v>1300</v></c>'
                 '<c r="C2" t="inlineStr"><is><t>Architect</t></is></c>'
                 '<c r="D2" t="inlineStr"><is><t>Platform architecture</t></is></c>'
                 '</row></sheetData></worksheet>')
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("xl/worksheets/sheet1.xml", worksheet)
    response = client.post("/api/v1/workforce/upload-preview?scenario_id=scn-001&filename=team.xlsx",
                           content=stream.getvalue(), headers={"Content-Type": "application/octet-stream"})
    assert response.status_code == 200, response.text
    assert response.json()["rows"][0]["current_rate_eur"] == "1300"


def test_source_specific_excel_templates_and_manual_auto_switch(isolated_db):
    client = TestClient(create_app())
    uploads = {}
    for source in ("excel", "fieldglass", "ariba"):
        template = client.get(f"/api/v1/workforce/template/{source}?scenario_id=scn-001")
        assert template.status_code == 200
        rows = _xlsx_rows(template.content)
        assert tuple(rows[0]) == TEMPLATE_COLUMNS[source]
        assert len(rows) == {"excel": 15, "fieldglass": 15, "ariba": 1}[source]
        assert all(row["scenario_id"] == "scn-001" for row in rows)
        assert rows[0]["contract_id" if source == "ariba" else "resource_id"] == (
            "ctr-001" if source == "ariba" else "res-001"
        )
        if source == "fieldglass":
            rows[0]["current_rate_eur"] = "1600"
        if source == "ariba":
            rows[0]["offshore_permitted"] = "FALSE"
        workbook = _workbook_bytes(TEMPLATE_COLUMNS[source], rows)
        response = client.post(
            f"/api/v1/workforce/upload-template/{source}?scenario_id=scn-001&filename=team.xlsx",
            content=workbook, headers={"Content-Type": "application/octet-stream"},
        )
        assert response.status_code == 200, response.text
        uploads[source] = response.json()["upload_id"]
        preview = client.get(
            f"/api/v1/workforce/data-preview/{source}?scenario_id=scn-001&upload_id={uploads[source]}"
        )
        assert preview.status_code == 200
        assert preview.json()["row_count"] == len(rows)
    common = {"case_id": "right_shoring", "scenario_id": "scn-001",
              "source_ids": ["fieldglass", "ariba"],
              "offshore_location_ids": ["loc-india"], "planned_downtime_hours": 2}
    auto = client.post("/api/v1/workforce/analyze", json={**common,
        "source_modes": {"fieldglass": "auto", "ariba": "auto"}})
    assert auto.status_code == 200, auto.text
    manual = client.post("/api/v1/workforce/analyze", json={**common,
        "source_modes": {"fieldglass": "manual", "ariba": "manual"},
        "source_upload_ids": {"fieldglass": uploads["fieldglass"], "ariba": uploads["ariba"]}})
    assert manual.status_code == 200, manual.text
    assert manual.json()["sources"][0]["status"] == "uploaded"
    assert manual.json()["options"][0]["annual_savings"] <= auto.json()["options"][0]["annual_savings"]
    missing = client.post("/api/v1/workforce/analyze", json={**common,
        "source_modes": {"fieldglass": "manual"}})
    assert missing.status_code == 400


def test_wrong_excel_template_is_rejected(isolated_db):
    client = TestClient(create_app())
    workbook = _workbook_bytes(("resource_id", "current_rate_eur"),
                               [{"resource_id": "res-001", "current_rate_eur": "1200"}])
    response = client.post(
        "/api/v1/workforce/upload-template/fieldglass?scenario_id=scn-001&filename=wrong.xlsx",
        content=workbook, headers={"Content-Type": "application/octet-stream"},
    )
    assert response.status_code == 400
    assert "Template columns" in response.json()["detail"]


def test_five_workforce_cases_generate_options_and_persist_review(isolated_db):
    client = TestClient(create_app())
    common = {
        "scenario_id": "scn-001",
        "offshore_location_ids": ["loc-india", "loc-philippines"],
        "source_ids": ["fieldglass"],
    }
    cases = [
        ("right_shoring", {"planned_downtime_hours": 2}),
        ("skill_based", {"skill": "Java payments"}),
        ("multi_vendor", {"role": "Developer", "max_suppliers": 2}),
        ("timezone", {"required_overlap_hours": 2}),
        ("capacity_gap", {"role": "Developer", "demand_roles": 5,
                          "available_roles": 3, "horizon_months": 3}),
    ]
    for case_id, extra in cases:
        response = client.post("/api/v1/workforce/analyze", json={**common, "case_id": case_id, **extra})
        assert response.status_code == 200, response.text
        result = response.json()
        assert len(result["options"]) == 2
        assert result["human_review_required"] is True
        if case_id == "right_shoring":
            assert result["case_name"] == "Optimized shoring"
            assert len(result["options"][0]["resource_details"]) == 15
            assert any("cutover downtime" in check for check in result["options"][0]["checks"])
            assert any("GDPR" in gap for gap in result["options"][0]["gaps"])
        assert {option["location_id"] for option in result["options"]} == set(common["offshore_location_ids"])
        assert client.get(f"/api/v1/workforce/analyses/{result['analysis_id']}").status_code == 200

    option_id = result["options"][0]["option_id"]
    review = client.post(
        f"/api/v1/workforce/analyses/{result['analysis_id']}/reviews",
        json={"reviewer_name": "Demo reviewer", "decision": "request_changes",
              "selected_option_id": option_id,
              "edited_recommendation": "Confirm supplier capacity before deciding on this location.",
              "rationale": "The available source preview does not prove future capacity."},
    )
    assert review.status_code == 200, review.text
    saved = client.get(f"/api/v1/workforce/analyses/{result['analysis_id']}/reviews")
    assert saved.json()[0]["edited_recommendation"] == "Confirm supplier capacity before deciding on this location."


def test_inland_target_and_unrelated_review_option_are_rejected(isolated_db):
    client = TestClient(create_app())
    body = {"case_id": "right_shoring", "scenario_id": "scn-001",
            "offshore_location_ids": ["loc-germany"], "source_ids": ["fieldglass"],
            "planned_downtime_hours": 2}
    response = client.post("/api/v1/workforce/analyze", json=body)
    assert response.status_code == 400
    body["offshore_location_ids"] = ["loc-india"]
    analysis = client.post("/api/v1/workforce/analyze", json=body).json()
    response = client.post(f"/api/v1/workforce/analyses/{analysis['analysis_id']}/reviews",
                           json={"reviewer_name": "Demo reviewer", "decision": "reject",
                                 "selected_option_id": "other-option",
                                 "edited_recommendation": "Do not move these roles until evidence is verified.",
                                 "rationale": "This option was not generated for the current analysis."})
    assert response.status_code == 400


def test_case_specific_inputs_change_the_screening_result(isolated_db):
    client = TestClient(create_app())
    common = {"scenario_id": "scn-001", "offshore_location_ids": ["loc-india"],
              "source_ids": ["fieldglass"]}
    one = client.post("/api/v1/workforce/analyze", json={**common, "case_id": "multi_vendor",
                       "role": "Developer", "max_suppliers": 1}).json()["options"][0]
    two = client.post("/api/v1/workforce/analyze", json={**common, "case_id": "multi_vendor",
                       "role": "Developer", "max_suppliers": 2}).json()["options"][0]
    assert one["supplier_name"] != two["supplier_name"]
    short = client.post("/api/v1/workforce/analyze", json={**common, "case_id": "capacity_gap",
                         "role": "Developer", "demand_roles": 5, "available_roles": 3,
                         "horizon_months": 3}).json()["options"][0]
    long = client.post("/api/v1/workforce/analyze", json={**common, "case_id": "capacity_gap",
                        "role": "Developer", "demand_roles": 5, "available_roles": 3,
                        "horizon_months": 6}).json()["options"][0]
    assert short["period_label"] == "over 3 months"
    assert long["period_savings"] == short["period_savings"] * 2


def test_human_review_cannot_forward_an_indicative_option(isolated_db):
    client = TestClient(create_app())
    analysis = client.post("/api/v1/workforce/analyze", json={
        "case_id": "capacity_gap", "scenario_id": "scn-001",
        "offshore_location_ids": ["loc-india"], "source_ids": ["fieldglass"],
        "role": "Developer", "demand_roles": 5, "available_roles": 3,
        "horizon_months": 3,
    }).json()
    response = client.post(f"/api/v1/workforce/analyses/{analysis['analysis_id']}/reviews",
                           json={"reviewer_name": "Demo reviewer", "decision": "ready_for_approval",
                                 "selected_option_id": analysis["options"][0]["option_id"],
                                 "edited_recommendation": "Confirm sourcing capacity before moving forward.",
                                 "rationale": "The option is only an indicative rate-card screen."})
    assert response.status_code == 400


def test_agent_ranks_only_selected_countries_and_requires_selection(isolated_db):
    client = TestClient(create_app())
    cases = [
        ("right_shoring", {"planned_downtime_hours": 2}),
        ("skill_based", {"skill": "Java payments"}),
        ("multi_vendor", {"role": "Developer", "max_suppliers": 2}),
        ("timezone", {"required_overlap_hours": 2}),
        ("capacity_gap", {"role": "Developer", "demand_roles": 5,
                          "available_roles": 3, "horizon_months": 3}),
    ]
    for case_id, extra in cases:
        response = client.post("/api/v1/workforce/analyze", json={
            "case_id": case_id, "scenario_id": "scn-001", "source_ids": ["fieldglass"],
            "offshore_location_ids": ["loc-india", "loc-philippines", "loc-vietnam"], **extra
        })
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["input"]["offshore_location_ids"] == ["loc-india", "loc-philippines", "loc-vietnam"]
        assert result["locations_evaluated"] == 3
        assert len(result["options"]) == 3
        if result["recommended_option_id"]:
            assert result["recommended_option_id"] == result["options"][0]["option_id"]
            assert result["options"][0]["rationale"]
            assert result["options"][0]["checks"]
    missing = client.post("/api/v1/workforce/analyze", json={
        "case_id": "right_shoring", "scenario_id": "scn-001", "source_ids": ["fieldglass"],
        "planned_downtime_hours": 2,
    })
    assert missing.status_code == 400
    assert "Select at least one country" in missing.json()["detail"]
    without_downtime = client.post("/api/v1/workforce/analyze", json={
        "case_id": "right_shoring", "scenario_id": "scn-001", "source_ids": ["fieldglass"],
        "offshore_location_ids": ["loc-india"],
    })
    assert without_downtime.status_code == 200, without_downtime.text


def test_single_visible_use_case_and_fieldglass_entity_previews(isolated_db):
    client = TestClient(create_app())
    cases = client.get("/api/v1/workforce/use-cases")
    assert cases.status_code == 200
    assert cases.json() == [{"case_id": "right_shoring", "name": "Optimized shoring"}]
    catalogue = client.get("/api/v1/workforce/fieldglass/entities")
    assert catalogue.status_code == 200
    assert catalogue.json()["live_connected"] is False
    assert {item["name"] for item in catalogue.json()["entities"]} == {
        "workers", "timesheets", "work_orders", "sow", "invoices", "suppliers", "job_postings"
    }
    for entity in catalogue.json()["entities"]:
        response = client.get(f"{entity['endpoint']}?scenario_id=scn-001")
        assert response.status_code == 200, response.text
        assert response.json()["live_connected"] is False
        assert response.json()["columns"]
    workers = client.get("/api/v1/workforce/fieldglass/entities/workers?scenario_id=scn-001").json()
    assert workers["row_count"] == 15
    assert all(row["resource_id"].startswith("res-") for row in workers["rows"])
    for name in ("timesheets", "work_orders", "sow", "invoices", "suppliers", "job_postings"):
        preview = client.get(f"/api/v1/workforce/fieldglass/entities/{name}?scenario_id=scn-001").json()
        assert preview["row_count"] > 0, name
        assert preview["rows"], name
    timesheets = client.get("/api/v1/workforce/fieldglass/entities/timesheets?scenario_id=scn-001").json()
    assert timesheets["status"] == "synthetic_demo"
    assert timesheets["extraction_active"] is False


def test_review_summary_round_trip(isolated_db):
    client = TestClient(create_app())
    analysis = client.post("/api/v1/workforce/analyze", json={
        "case_id": "right_shoring", "scenario_id": "scn-001",
        "offshore_location_ids": ["loc-india"], "source_ids": ["fieldglass"],
    }).json()
    url = f"/api/v1/workforce/analyses/{analysis['analysis_id']}/reviews"
    payload = {"reviewer_name": "Test reviewer", "decision": "request_changes",
               "selected_option_id": analysis["options"][0]["option_id"],
               "edited_recommendation": "Confirm the handover before proceeding.",
               "rationale": "Check availability with the delivery team.",
               "calculation_summary": "Reviewed annual savings: EUR 12000",
               "implication_summary": {"operations": "Plan a weekend cutover.",
                                       "talent": "Keep two senior developers."},
               "downtime_hours": 3.5}
    response = client.post(url, json=payload)
    assert response.status_code == 200, response.text
    saved = client.get(url).json()[0]
    assert saved["calculation_summary"] == payload["calculation_summary"]
    assert saved["implication_summary"]["talent"] == payload["implication_summary"]["talent"]
    assert saved["implication_summary"]["operations"] == payload["implication_summary"]["operations"]
    assert saved["downtime_hours"] == 3.5
    payload["implication_summary"]["talent"] = "x" * 3001
    assert client.post(url, json=payload).status_code == 422
