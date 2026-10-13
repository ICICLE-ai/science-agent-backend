"""Mock regression checks only; no real pod, DB or API is contacted."""
import asyncio
from contextlib import asynccontextmanager
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from science_agent_backend import agent_runtime, pod_files, pod_terminal, s3_credentials


@pytest.mark.parametrize('token', ['', 'development-token'])
def test_transports_only_send_nonempty_gateway_token(monkeypatch, token):
    headers = []
    handshakes = []
    ws = SimpleNamespace(send_str=AsyncMock(side_effect=handshakes.append),
                         send_bytes=AsyncMock(), closed=False)

    @asynccontextmanager
    async def response():
        yield SimpleNamespace(status=200, json=AsyncMock(return_value={'token': 'ttyd-token'}))

    @asynccontextmanager
    async def websocket():
        yield ws

    class Client:
        def __init__(self, **kwargs):
            headers.append(kwargs['headers'])

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def get(self, *args, **kwargs):
            return response()

        def ws_connect(self, *args, **kwargs):
            return websocket()

    monkeypatch.setattr(pod_terminal.aiohttp, 'ClientSession', Client)
    monkeypatch.setattr(pod_terminal.asyncio, 'sleep', AsyncMock())
    monkeypatch.setattr(pod_terminal.PodTerminal, '_frame', AsyncMock(return_value=False))
    monkeypatch.setattr(pod_terminal.PodTerminal, '_idle', lambda *args: True)
    monkeypatch.setattr(pod_terminal.PodTerminal, '_answer', lambda *args: 'Agent answer')
    monkeypatch.setattr(pod_files.PodFiles, 'receive', AsyncMock(return_value={'root': '/workspace'}))

    async def scenario():
        answer = await pod_terminal.PodTerminal('https://agent.example.org', token).request('Hello')
        assert answer == 'Agent answer'
        async with pod_files.file_channel('https://agent.example.org', token) as channel:
            assert channel.info['root'] == '/workspace'

    asyncio.run(scenario())
    expected = {'X-Tapis-Token': token} if token else {}
    assert headers == [expected, expected]
    assert all(json.loads(frame)['AuthToken'] == 'ttyd-token' for frame in handshakes)


@pytest.mark.parametrize('gateway_token', ['', 'development-token'])
def test_user_token_still_reaches_private_context(monkeypatch, tmp_path, gateway_token):
    monkeypatch.setattr(agent_runtime.config, 'POD_TOKEN', gateway_token)
    monkeypatch.setattr(agent_runtime.config, 'POD_URL', 'https://agent.example.org')
    skills = tmp_path / 'skills'
    skills.mkdir()
    monkeypatch.setattr(agent_runtime.config, 'SKILLS_DIR', skills)
    monkeypatch.setattr(agent_runtime.tempfile, 'gettempdir', lambda: str(tmp_path))
    monkeypatch.setattr(agent_runtime.database, 'get', AsyncMock(return_value={
        'uploaded_files': [], 'history': [], 'execution_log': [], 'domain_knowledge': ''}))
    monkeypatch.setattr(agent_runtime.database, 'mutate', AsyncMock())
    monkeypatch.setattr(s3_credentials, 'load_profile', AsyncMock(return_value=None))
    channel = SimpleNamespace(info={'root': '/workspace'}, put=AsyncMock(),
                              command=AsyncMock(return_value={'observations': []}))
    connection_tokens = []

    @asynccontextmanager
    async def connect(url, token):
        connection_tokens.append(token)
        yield channel

    class Terminal:
        def __init__(self, url, token):
            connection_tokens.append(token)

        request = AsyncMock(return_value='Recorded result')

    monkeypatch.setattr(agent_runtime, 'file_channel', connect)
    monkeypatch.setattr(agent_runtime, 'PodTerminal', Terminal)
    identity = SimpleNamespace(subject='user@icicleai', username='user', token='user-cookie-token')
    asyncio.run(agent_runtime.run('session-1', identity, 'Label my image', AsyncMock()))
    private = json.loads(channel.put.await_args.args[1])
    assert private['tapis_token'] == identity.token
    assert private['session_id'] == 'session-1'
    assert private['tapis_base_dir'] == '/users/user/demo'
    assert connection_tokens == [gateway_token, gateway_token, gateway_token]
    agent_runtime.database.get.assert_awaited_once_with('session-1', identity.subject)
