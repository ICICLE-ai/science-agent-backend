"""PostgreSQL checks opt in explicitly; mock checks never contact the pod."""
import asyncio
import hashlib
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4
import pytest
from science_agent_backend import agent_runtime, database


def test_pod_transfer_uses_database_bytes(monkeypatch):
    async def scenario():
        data = b'original-image'
        get = AsyncMock(return_value={'size':len(data), 'content':data})
        monkeypatch.setattr(database, 'get_attachment', get)
        channel = SimpleNamespace(put=AsyncMock(return_value={'size':len(data), 'sha256':hashlib.sha256(data).hexdigest()}))
        files = await agent_runtime.transfer_attachments(channel, 'run', 'session', 'owner',
                                                         [{'name':'cow.jpg'}], AsyncMock())
        get.assert_awaited_once_with('session', 'owner', 'cow.jpg')
        channel.put.assert_awaited_once_with('run/uploads/cow.jpg', data)
        assert files[0]['sha256'] == hashlib.sha256(data).hexdigest()
    asyncio.run(scenario())


@pytest.mark.skipif(os.getenv('SCIENCE_AGENT_TEST_DATABASE') != '1', reason='Requires an explicitly selected real PostgreSQL database')
def test_postgres_attachment_lifecycle():
    async def scenario():
        await database.initialize()
        subject = f'attachment-test-{uuid4()}@test'
        await database.remember_identity(SimpleNamespace(subject=subject, tenant_id='test', username=subject))
        sid = None
        try:
            sid = await database.create(subject)
            original = b'\x00\xff\x89PNG\r\n\x1a\noriginal-image'
            first = await database.put_attachment(sid, subject, 'image.png', 'image/png', original)
            stored = await database.get_attachment(sid, subject, 'image.png')
            assert stored['content'] == original
            assert stored['sha256'] == hashlib.sha256(original).hexdigest()
            assert (await database.get(sid, subject))['uploaded_files'] == [first]
            for action in (
                database.get_attachment(sid, 'different@test', 'image.png'),
                database.put_attachment(sid, 'different@test', 'image.png', 'image/png', b'changed'),
                database.delete_attachment(sid, 'different@test', 'image.png'),
            ):
                with pytest.raises(FileNotFoundError):
                    await action
            replaced = await database.put_attachment(sid, subject, 'image.png', 'image/png', b'replaced')
            assert replaced['id'] == first['id']
            assert (await database.get_attachment(sid, subject, 'image.png'))['content'] == b'replaced'
            assert len((await database.get(sid, subject))['uploaded_files']) == 1
            await database.delete_attachment(sid, subject, 'image.png')
            assert (await database.get(sid, subject))['uploaded_files'] == []
            with pytest.raises(FileNotFoundError):
                await database.get_attachment(sid, subject, 'image.png')
            await database.put_attachment(sid, subject, 'image.png', 'image/png', original)
            await database.delete(sid, subject)
            async with await database.connect() as conn:
                assert (await (await conn.execute('SELECT count(*) FROM science_agent_attachments WHERE session_id=%s', (sid,))).fetchone())[0] == 0
        finally:
            async with await database.connect() as conn:
                if sid:
                    await conn.execute('DELETE FROM science_agent_sessions WHERE id=%s', (sid,))
                await conn.execute('DELETE FROM science_agent_users WHERE subject=%s', (subject,))
    asyncio.run(scenario())
