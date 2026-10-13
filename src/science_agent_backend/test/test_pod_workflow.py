"""Local contract checks; cloud and agent calls are mocked."""
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest
from io import BytesIO
from urllib.error import HTTPError
from science_agent_backend import config

directory = config.SKILLS_DIR / 'labeling'
sys.path.insert(0, str(directory))
spec = importlib.util.spec_from_file_location('pod_workflow', directory / 'pod_workflow.py')
workflow = importlib.util.module_from_spec(spec)
spec.loader.exec_module(workflow)


def context(tmp_path):
    path = tmp_path / 'context.json'
    path.write_text(json.dumps({'session_id':'session','run_id':'run', 's3':{}, 'tapis_token':'private-token',
        'smart_labeler_url':'https://service.invalid','tapis_base_url':'https://tapis.invalid',
        'tapis_system':'expanse-tapis-static','tapis_base_dir':'/users/example/demo','user_request':'label image'}))
    return path


def test_storage_failure_prevents_submission(tmp_path, monkeypatch):
    monkeypatch.setattr(workflow.subprocess, 'run', lambda *a,**k: SimpleNamespace(returncode=1))
    def forbidden(*args, **kwargs):
        pytest.fail('A failed storage operation must never submit a job')
    monkeypatch.setattr(workflow, 'submit_smart_labeler', forbidden)
    report=workflow.execute(context(tmp_path),'label')
    assert report['success'] is False
    assert report['stages'] == []


def test_completed_report_prevents_duplicate_submission(tmp_path, monkeypatch):
    (tmp_path/'workflow-result.json').write_text('{"success":true,"smart_labeler":{"job":{"uuid":"job-1"}}}')
    monkeypatch.setattr(workflow.subprocess, 'run', lambda *a,**k: pytest.fail('Must not run twice'))
    assert workflow.execute(context(tmp_path),'label')['smart_labeler']['job']['uuid']=='job-1'


def test_uncertain_write_is_not_retried(tmp_path):
    (tmp_path/'workflow-started').touch()
    with pytest.raises(FileExistsError):
        workflow.execute(context(tmp_path),'label')


def test_recovered_path_passed_to_staging(tmp_path, monkeypatch):
    storage={'files':[{'name':'cow.jpg','recovered_path':'/run/arraymorph-recovered/cow.jpg'}]}
    monkeypatch.setattr(workflow.subprocess,'run',lambda *a,**k:SimpleNamespace(returncode=0,stdout=json.dumps(storage)))
    observed=[]
    def stage(manifest,*args):
        observed.append(manifest['recovered_path'])
        return {'directory':'/users/example/demo/source'}
    monkeypatch.setattr(workflow,'stage_recovered_image',stage)
    monkeypatch.setattr(workflow,'submit_smart_labeler',lambda *a,**k:{'job':{'uuid':'job-1','status':'QUEUED'}})
    report=workflow.execute(context(tmp_path),'label')
    assert observed==['/run/arraymorph-recovered/cow.jpg']
    assert report['smart_labeler']['job']['status']=='QUEUED'
    assert report['success'] is True  # Submission success, not computation completion.


def test_failed_write_records_redacted_diagnostics_without_retry(tmp_path, monkeypatch):
    calls = []
    def failed(request, timeout):
        calls.append(request)
        raise HTTPError(request.full_url, 500, 'Failure', {}, BytesIO(b'private-token error'))
    monkeypatch.setattr(workflow, 'build_opener', lambda *a: SimpleNamespace(open=failed))
    client = workflow.Client(json.loads(context(tmp_path).read_text()), tmp_path)
    with pytest.raises(RuntimeError, match='HTTP 500'):
        client.post('/pipe/create', {'name':'example'})
    records = list((tmp_path/'observations').glob('*.json'))
    assert len(calls) == len(records) == 1
    text = records[0].read_text()
    assert 'private-token' not in text
    record = json.loads(text)
    assert record['http_status'] == 500
    assert record['request_body'] == {'name':'example'}
    assert record['error_body'] == '[REDACTED] error'
