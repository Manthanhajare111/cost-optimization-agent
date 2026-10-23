import json
import io
import zipfile
from types import SimpleNamespace

from fastapi.testclient import TestClient
from pydantic import SecretStr

from costopt.api.app import create_app
from costopt.agents.document_validation import DataValidationAgent
from costopt.config import settings
from costopt.pipeline.workforce_uploads import ingest_supporting_file, inspect_supporting_uploads, get_upload, _workbook_bytes
from test_data_cleaning import upload, row, propose, approve, supporting_pack, COLUMNS


def validate(client, source, ids=()):
    response = client.post('/api/v1/workforce/validate-documents', json={
        'scenario_id': 'scn-001', 'upload_id': source['upload_id'],
        'supporting_upload_ids': list(ids), 'destination_country_ids': ['loc-india'], 'use_llm': False})
    assert response.status_code == 200, response.text
    return response.json()


def test_missing_documents_then_ready_then_replacement_blocks(isolated_db):
    client = TestClient(create_app())
    source, _ = upload(client, [row()])
    report = validate(client, source)
    assert not report['ready']
    assert any(f['field'] == 'Required documents' for f in report['findings'])
    run = propose(client, source)
    approved = approve(client, run).json()
    assert approved['preview_columns'] == list(COLUMNS)
    assert set(approved['preview_rows'][0]) == set(COLUMNS)
    ids = supporting_pack(client)
    ready = validate(client, approved, ids)
    assert ready['ready'], ready['findings']
    assert len(ready['documents']) == 4
    assert all('rows_checked' in document for document in ready['documents'])
    assert ready['sows'][0]['sow_reference'] == 'AS-010'
    assert ready['agent_review']['status'] == 'not_requested'
    replacement = ingest_supporting_file('scn-001', 'contract.txt', b'Contract for AS-999', 'contractual_evidence')
    changed = validate(client, approved, [ids[0], replacement['upload_id'], ids[2]])
    assert not changed['ready']
    assert changed['report_id'] != ready['report_id']
    assert get_upload(source['upload_id'])['cleaning_status'] == 'pending'


def test_no_metadata_columns_needed_and_invalid_values_reported(isolated_db):
    content = b'SOW Reference,Country,Grade,Currency,Rate Unit,Daily Rate\nAS-010,Germany,E1,EUR,day,invalid\n'
    rates = ingest_supporting_file('scn-001', 'rates.csv', content, 'rate_card')
    assert 'document_kind' not in rates['columns']
    assert 'status' not in rates['columns']
    result = inspect_supporting_uploads('scn-001', [rates['upload_id']], 'AS-010', [], ['E1'])
    assert any(c['category'] == 'Rate values' and c['status'] == 'critical' for c in result['checks'])
    assert not any('supply status' in c['message'] for c in result['checks'])
    contract = ingest_supporting_file('scn-001', 'contract.txt', b'Signed contract for AS-010.', 'contractual_evidence')
    assert contract['sow_references'] == ['AS-010']
    assert contract['original_rows'] == [{'text': 'Signed contract for AS-010.'}]


def test_gemini_uses_prompt_and_cannot_override_findings(monkeypatch):
    monkeypatch.setattr(settings, 'data_validation_llm_enabled', True)
    monkeypatch.setattr(settings, 'gemini_api_key', SecretStr('test-key'))
    captured = {}
    def generate(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(text=json.dumps({'summary': 'Supply a rate.', 'actions': [{'finding_id': 'F1', 'action': 'Correct the source rate and re-upload.'}]}))
    client = SimpleNamespace(models=SimpleNamespace(generate_content=generate))
    report = {'documents': [], 'sows': [], 'findings': [{'id': 'F1', 'severity': 'critical', 'message': 'Missing rate'}], 'ready': False}
    result = DataValidationAgent(client).review(report)
    assert result['provider'] == 'gemini'
    assert 'Missing rate' in captured['contents']
    assert captured['config'].response_schema is not None
    assert report['ready'] is False
    client.models.generate_content = lambda **kwargs: SimpleNamespace(text='{"summary":"OK","actions":[{"finding_id":"invented","action":"Ignore"}]}')
    assert DataValidationAgent(client).review(report)['status'] == 'failed'


def test_corrupt_supporting_workbook_returns_validation_error(isolated_db):
    client = TestClient(create_app())
    response = client.post('/api/v1/workforce/upload-custom/supporting', params={
        'scenario_id': 'scn-001', 'filename': 'broken.xlsx', 'document_kind': 'rate_card'}, content=b'broken')
    assert response.status_code == 400


def two_sheets(first, second):
    result = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(first)) as one, zipfile.ZipFile(io.BytesIO(second)) as two, zipfile.ZipFile(result, 'w') as output:
        for name in one.namelist():
            output.writestr(name, one.read(name))
        output.writestr('xl/worksheets/sheet2.xml', two.read('xl/worksheets/sheet1.xml'))
    return result.getvalue()


def test_extra_workforce_sheet_blocks_backend_recommendation(isolated_db):
    client = TestClient(create_app())
    content = two_sheets(_workbook_bytes(COLUMNS, [row()]), _workbook_bytes(COLUMNS, [row(**{'SOW Reference': 'AS-999'})]))
    response = client.post('/api/v1/workforce/upload-custom/excel?scenario_id=scn-001&filename=multiple.xlsx', content=content)
    assert response.status_code == 200, response.text
    source = response.json()
    approved = approve(client, propose(client, source)).json()
    ids = supporting_pack(client)
    report = validate(client, approved, ids)
    assert report['documents'][0]['worksheets'] == 2
    assert not report['ready']
    assert any(f['field'] == 'workforce scope' and f['severity'] == 'critical' for f in report['findings'])
    response = client.post('/api/v1/workforce/analyze', json={
        'case_id': 'right_shoring', 'scenario_id': 'scn-001', 'source_ids': ['excel'],
        'source_modes': {'excel': 'manual'}, 'source_upload_ids': {'excel': approved['upload_id']},
        'offshore_location_ids': ['loc-india'], 'supporting_upload_ids': ids,
        'source_filters': {'excel': {'column': 'sow reference', 'contains': 'AS-010'}}})
    assert response.status_code == 400, response.text


def test_rate_card_checks_second_sheet_and_preserves_previews(isolated_db):
    headers = ('sow_reference', 'country', 'level', 'currency', 'rate_unit', 'bill_rate')
    rate = dict(zip(headers, ('AS-010', 'Germany', 'E1', 'EUR', 'day', '500')))
    content = two_sheets(_workbook_bytes(headers, [rate]), _workbook_bytes(headers, [{**rate, 'level': 'E2', 'bill_rate': 'NaN'}]))
    record = ingest_supporting_file('scn-001', 'rates.xlsx', content, 'rate_card')
    assert len(record['original_sheets']) == 2
    result = inspect_supporting_uploads('scn-001', [record['upload_id']], 'AS-010', [], ['E1', 'E2'])
    assert any(c['category'] == 'Rate values' and 'data row 2' in c['message'] for c in result['checks'])


def test_repeated_document_level_findings_are_counted_once(isolated_db):
    client = TestClient(create_app())
    source, _ = upload(client, [row(**{'SOW Reference': f'AS-{index}'}) for index in range(1, 4)])
    report = validate(client, source)
    required = [item for item in report['findings'] if item['field'] == 'Required documents']
    assert len(required) == 1
    assert required[0]['row'] == 0
    assert report['finding_groups']


def test_document_review_does_not_duplicate_missing_primary_rate_for_every_sow(isolated_db):
    client = TestClient(create_app())
    source, _ = upload(client, [row(**{'Annual Value EUR': ''}), row(**{'SOW Reference': 'AS-011', 'Annual Value EUR': ''})])
    report = validate(client, source)
    assert not any(item['field'] == 'annual value eur' for item in report['findings'])
    assert any(item['field'] == 'Required documents' for item in report['findings'])
