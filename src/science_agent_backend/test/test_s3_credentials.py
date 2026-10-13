"""Credential parsing checks and opt-in PostgreSQL ownership/selection checks."""
import asyncio
import json
import os
from types import SimpleNamespace
from uuid import uuid4
import pytest
from science_agent_backend import database, s3_credentials


def profile(name='Research images'):
    return dict(name=name, endpoint='https://storage.example.org', bucket='research-images',
                region='us-east-1', access_key_id='test-access', secret_access_key='test-secret')


@pytest.mark.parametrize('raw', [
    json.dumps(profile()).encode(),
    b'PROFILE_NAME="Research images"\nAWS_ENDPOINT_URL_S3=https://storage.example.org\nBUCKET_NAME=research-images\nAWS_REGION=us-east-1\nAWS_ACCESS_KEY_ID=test-access\nAWS_SECRET_ACCESS_KEY=test-secret',
    b'[research]\nname=Research images\nendpoint=https://storage.example.org\nbucket=research-images\nregion=us-east-1\naws_access_key_id=test-access\naws_secret_access_key=test-secret',
])
def test_credential_file_formats(raw):
    assert s3_credentials.parse_credential_file(raw) == profile()


def test_import_does_not_expand_server_environment(monkeypatch):
    monkeypatch.setenv('SERVER_SECRET', 'must-not-be-imported')
    parsed = s3_credentials.parse_credential_file(b'AWS_SECRET_ACCESS_KEY=${SERVER_SECRET}')
    assert parsed['secret_access_key'] == '${SERVER_SECRET}'


def test_no_default_endpoint_or_region():
    data = profile()
    data.pop('endpoint')
    with pytest.raises(ValueError, match='HTTPS'):
        s3_credentials.validate_profile(data)
    data = profile()
    data.pop('region')
    with pytest.raises(ValueError, match='region'):
        s3_credentials.validate_profile(data)


@pytest.mark.skipif(os.getenv('SCIENCE_AGENT_TEST_DATABASE') != '1', reason='Requires an explicitly selected real PostgreSQL database')
def test_multiple_db_credentials_are_owned_and_explicitly_selected(monkeypatch):
    monkeypatch.delenv('S3_CREDENTIAL_ENCRYPTION_KEY', raising=False)
    monkeypatch.delenv('S3_CREDENTIAL_KEY_FILE', raising=False)
    async def scenario():
        await database.initialize()
        owner = f's3-test-{uuid4()}@test'
        other = f's3-test-{uuid4()}@test'
        for subject in (owner, other):
            await database.remember_identity(SimpleNamespace(subject=subject, tenant_id='test', username=subject))
        try:
            initial = await s3_credentials.settings(owner)
            assert initial['profiles'] == [] and initial['selected_profile_id'] is None
            first = await s3_credentials.save_profile(owner, profile('First'))
            second = await s3_credentials.save_profile(owner, {**profile('Second'), 'secret_access_key':'second-secret'})
            assert len(await s3_credentials.list_profiles(owner)) == 2
            assert await s3_credentials.load_profile(owner, include_secrets=True) is None
            assert (await s3_credentials.list_profiles(other)) == []
            with pytest.raises(FileNotFoundError):
                await s3_credentials.select_profile(other, first['id'])
            with pytest.raises(FileNotFoundError):
                await s3_credentials.load_profile(other, first['id'], include_secrets=True)
            with pytest.raises(FileNotFoundError):
                await s3_credentials.save_profile(other, profile('Stolen'), first['id'])
            with pytest.raises(FileNotFoundError):
                await s3_credentials.delete_profile(other, first['id'])
            await s3_credentials.select_profile(owner, second['id'])
            selected = await s3_credentials.load_profile(owner, include_secrets=True)
            assert selected['id'] == second['id'] and selected['secret_access_key']=='second-secret'
            metadata = await s3_credentials.settings(owner)
            assert 'second-secret' not in json.dumps(metadata) and 'test-access' not in json.dumps(metadata)
            async with await database.connect() as conn:
                rows = await (await conn.execute('SELECT access_key_id,secret_access_key FROM science_agent_s3_credentials WHERE owner_subject=%s', (owner,))).fetchall()
                assert {row[0] for row in rows}=={'test-access'}
                assert {row[1] for row in rows}=={'test-secret','second-secret'}
            # Saving another credential and restarting schema setup must retain the user's selection.
            await s3_credentials.save_profile(owner, profile('Third'))
            await database.initialize()
            assert (await s3_credentials.settings(owner))['selected_profile_id'] == second['id']
            await asyncio.gather(s3_credentials.select_profile(owner, first['id']),
                                 s3_credentials.select_profile(owner, second['id']))
            assert sum(p['selected'] for p in await s3_credentials.list_profiles(owner))==1
            await s3_credentials.select_profile(owner, second['id'])
            await s3_credentials.save_profile(owner, {**profile('First renamed'),'access_key_id':'','secret_access_key':''}, first['id'])
            assert (await s3_credentials.load_profile(owner, first['id'], include_secrets=True))['secret_access_key']=='test-secret'
            with pytest.raises(ValueError, match='already exists'):
                await s3_credentials.save_profile(owner, profile('Second'))
            await s3_credentials.select_profile(owner, first['id'])
            assert sum(p['selected'] for p in await s3_credentials.list_profiles(owner))==1
            await s3_credentials.select_profile(owner, None)
            assert await s3_credentials.load_profile(owner) is None
            await s3_credentials.select_profile(owner, second['id'])
            await s3_credentials.delete_profile(owner, second['id'])
            assert await s3_credentials.load_profile(owner, include_secrets=True) is None
            assert len(await s3_credentials.list_profiles(owner))==2
        finally:
            async with await database.connect() as conn:
                await conn.execute('DELETE FROM science_agent_users WHERE subject=ANY(%s)', ([owner,other],))
    asyncio.run(scenario())
