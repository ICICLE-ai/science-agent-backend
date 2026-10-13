"""Isolated contract checks: no real DB, pod or Tapis requests."""
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from science_agent_backend import main
from science_agent_backend.api import account, dependencies, execution
from science_agent_backend.auth import TapisAuthenticationError
from science_agent_backend.runtime_state import active_sessions


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(main.database, 'initialize', AsyncMock())
    monkeypatch.setattr(main.config, 'LEGACY_UPLOAD_DIR', tmp_path)
    async def identify(connection):
        if connection.cookies.get('X-Tapis-Token') != 'test-only':
            raise TapisAuthenticationError('Missing test credential')
        return SimpleNamespace(subject='user@test', token='test-only')
    monkeypatch.setattr(dependencies, 'identity_for', identify)
    monkeypatch.setattr(account, 'identity_for', identify)
    monkeypatch.setattr(execution, 'identity_for', identify)
    with TestClient(main.app) as client:
        yield client


def test_unauthenticated(client):
    assert client.get('/api/execution/agent_sessions').status_code == 401


def test_origin_rejected(client):
    assert client.post('/api/execution/agent_session', headers={'Origin':'https://untrusted.invalid'}).status_code == 403


def test_health_routes(client):
    assert client.get('/health').json() == {'status':'ok'}
    assert client.get('/healthcheck').json()['agent_backend'] == 'pod'


def test_active_request_blocks_files_and_session_delete(client, monkeypatch):
    sid = uuid4()
    monkeypatch.setattr(main.database, 'get', AsyncMock(return_value={}))
    client.cookies.set('X-Tapis-Token', 'test-only')
    active_sessions.add(str(sid))
    try:
        assert client.post(f'/api/execution/upload/{sid}', files={'file':('cow.jpg', b'123')}).status_code == 409
        assert client.delete(f'/api/execution/agent_session/{sid}').status_code == 409
    finally:
        active_sessions.discard(str(sid))


def test_session_owner_filter(client, monkeypatch):
    listing = AsyncMock(return_value=[])
    monkeypatch.setattr(main.database, 'listing', listing)
    client.cookies.set('X-Tapis-Token', 'test-only')
    assert client.get('/api/execution/agent_sessions').json() == []
    listing.assert_awaited_once_with('user@test')


def test_credential_import_parses_upload_without_returning_secrets(client, monkeypatch):
    settings = {'configured':False, 'profile':None, 'profiles':[], 'selected_profile_id':None}
    save = AsyncMock(return_value={'id':'example-id', 'name':'Uploaded'})
    monkeypatch.setattr(account.s3_credentials, 'save_profile', save)
    monkeypatch.setattr(account.s3_credentials, 'settings', AsyncMock(return_value=settings))
    client.cookies.set('X-Tapis-Token', 'test-only')
    response = client.post('/api/account/s3/import', data={'name':'Uploaded','endpoint':'https://storage.example.org','bucket':'research-images','region':'us-east-1'},
                           files={'file':('credentials.env', b'AWS_ACCESS_KEY_ID=test-access\nAWS_SECRET_ACCESS_KEY=test-secret')})
    assert response.status_code == 201
    assert save.await_args.args[0] == 'user@test'
    assert save.await_args.args[1]['secret_access_key']=='test-secret'
    assert 'test-secret' not in response.text
    assert response.json()['selected_profile_id'] is None


def test_credential_selection_endpoint_is_not_captured_by_id_route(client, monkeypatch):
    identifier = uuid4()
    select = AsyncMock()
    monkeypatch.setattr(account.s3_credentials, 'select_profile', select)
    monkeypatch.setattr(account.s3_credentials, 'settings', AsyncMock(return_value={'selected_profile_id':str(identifier)}))
    client.cookies.set('X-Tapis-Token', 'test-only')
    response = client.put('/api/account/s3/selection', json={'profile_id':str(identifier)})
    assert response.status_code == 200
    select.assert_awaited_once_with('user@test', identifier)


def test_upload_limit(client, monkeypatch):
    monkeypatch.setattr(main.database, 'get', AsyncMock(return_value={}))
    put = AsyncMock()
    monkeypatch.setattr(main.database, 'put_attachment', put)
    monkeypatch.setattr(main.config, 'UPLOAD_LIMIT', 2)
    client.cookies.set('X-Tapis-Token', 'test-only')
    r=client.post(f'/api/execution/upload/{uuid4()}', files={'file':('sample.txt', b'123')})
    assert r.status_code == 413
    put.assert_not_awaited()
    assert not list(main.config.LEGACY_UPLOAD_DIR.iterdir())


def test_upload_stores_binary_in_database(client, monkeypatch):
    sid = uuid4()
    monkeypatch.setattr(main.database, 'get', AsyncMock(return_value={}))
    info = dict(name='cow.jpg', size=3, object_name=f'{sid}/cow.jpg', storage='postgres')
    put = AsyncMock(return_value=info)
    monkeypatch.setattr(main.database, 'put_attachment', put)
    client.cookies.set('X-Tapis-Token', 'test-only')
    response = client.post(f'/api/execution/upload/{sid}', files={'file':('cow.jpg', b'123', 'image/jpeg')})
    assert response.status_code == 200
    assert response.json()['storage'] == 'postgres'
    put.assert_awaited_once_with(sid, 'user@test', 'cow.jpg', 'image/jpeg', b'123')
    assert not list(main.config.LEGACY_UPLOAD_DIR.iterdir())


def test_download_returns_original_bytes_and_scopes_owner(client, monkeypatch):
    sid = uuid4()
    get = AsyncMock(return_value=dict(name='cow.jpg', content_type='image/jpeg', content=b'original-image'))
    monkeypatch.setattr(main.database, 'get_attachment', get)
    client.cookies.set('X-Tapis-Token', 'test-only')
    response = client.get(f'/api/execution/upload/{sid}/cow.jpg')
    assert response.content == b'original-image'
    assert response.headers['content-type'] == 'image/jpeg'
    assert response.headers['cache-control'] == 'private, no-store'
    get.assert_awaited_once_with(sid, 'user@test', 'cow.jpg')


def test_websocket_state_and_ack(client, monkeypatch):
    sid=str(uuid4())
    monkeypatch.setattr(main.database, 'get', AsyncMock(return_value={'id':sid,'history':[]}))
    mutate=AsyncMock()
    monkeypatch.setattr(main.database, 'mutate', mutate)
    client.cookies.set('X-Tapis-Token', 'test-only')
    with client.websocket_connect(f'/api/execution/ws/{sid}') as ws:
        assert ws.receive_json()['type'] == 'state'
        ws.send_json(dict(command='update_task_inputs', command_id=7, task_instruction='hello'))
        assert ws.receive_json() == {'command_id':7}
        ws.send_json(dict(command='run_program', command_id=8))
        assert ws.receive_json()['type'] == 'error'
    assert mutate.await_args.args[:2] == (sid, 'user@test')
