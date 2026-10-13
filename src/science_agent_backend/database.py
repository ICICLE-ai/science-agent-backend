import time
import hashlib
from uuid import uuid4
import psycopg
from psycopg.types.json import Jsonb
from . import config


async def connect():
    if not config.DATABASE_URL:
        raise RuntimeError('DATABASE_URL is required.')
    return await psycopg.AsyncConnection.connect(config.DATABASE_URL, connect_timeout=5)


async def initialize():
    from .migrations import run_migrations
    async with await connect() as conn:
        return await run_migrations(conn)


async def remember_identity(identity):
    async with await connect() as conn:
        await conn.execute('''INSERT INTO science_agent_users (subject, tenant_id, username, last_seen)
            VALUES (%s,%s,%s,now()) ON CONFLICT(subject) DO UPDATE SET last_seen=now()''',
            (identity.subject, identity.tenant_id, identity.username))


async def create(subject):
    sid = str(uuid4())
    state = dict(id=sid, metadata=dict(user_id=subject, source='user', created_at=int(time.time())),
                 description='', task_instruction='', domain_knowledge='', history=[],
                 uploaded_files=[], output_files=[], code_files=[], execution_log=[],
                 total_prompt_tokens=0, total_completion_tokens=0, total_cost=0)
    async with await connect() as conn:
        await conn.execute('INSERT INTO science_agent_sessions(id,owner_subject,source,data) VALUES (%s,%s,%s,%s)',
                           (sid, subject, 'user', Jsonb(state)))
    return sid


async def get(sid, subject):
    async with await connect() as conn:
        row = await (await conn.execute("SELECT data FROM science_agent_sessions WHERE id=%s AND owner_subject=%s AND source='user'",
                                       (sid, subject))).fetchone()
    if not row:
        raise FileNotFoundError('Conversation not found.')
    return row[0]


async def listing(subject):
    async with await connect() as conn:
        rows = await (await conn.execute("SELECT data FROM science_agent_sessions WHERE owner_subject=%s AND source='user' ORDER BY updated_at DESC",
                                        (subject,))).fetchall()
    return [r[0] for r in rows]


async def mutate(sid, subject, change):
    async with await connect() as conn:
        row = await (await conn.execute("SELECT data FROM science_agent_sessions WHERE id=%s AND owner_subject=%s AND source='user' FOR UPDATE",
                                       (sid, subject))).fetchone()
        if not row:
            raise FileNotFoundError('Conversation not found.')
        state = row[0]
        change(state)
        await conn.execute('UPDATE science_agent_sessions SET data=%s,updated_at=now() WHERE id=%s AND owner_subject=%s',
                           (Jsonb(state), sid, subject))


async def delete(sid, subject):
    async with await connect() as conn:
        result = await conn.execute("DELETE FROM science_agent_sessions WHERE id=%s AND owner_subject=%s AND source='user'", (sid, subject))
        if not result.rowcount:
            raise FileNotFoundError('Conversation not found.')


def attachment_info(sid, attachment_id, name, content_type, size, sha256):
    return dict(id=str(attachment_id), name=name, size=size, content_type=content_type,
                sha256=sha256, object_name=f'{sid}/{name}', source='user', storage='postgres')


async def put_attachment(sid, subject, name, content_type, content):
    digest = hashlib.sha256(content).hexdigest()
    async with await connect() as conn:
        row = await (await conn.execute("SELECT data FROM science_agent_sessions WHERE id=%s AND owner_subject=%s AND source='user' FOR UPDATE",
                                       (sid, subject))).fetchone()
        if not row:
            raise FileNotFoundError('Conversation not found.')
        inserted = await (await conn.execute('''INSERT INTO science_agent_attachments
            (id, session_id, filename, content_type, size_bytes, sha256, content)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (session_id, filename) DO UPDATE SET
                content_type=EXCLUDED.content_type, size_bytes=EXCLUDED.size_bytes,
                sha256=EXCLUDED.sha256, content=EXCLUDED.content, updated_at=now()
            RETURNING id''', (uuid4(), sid, name, content_type, len(content), digest, content))).fetchone()
        info = attachment_info(sid, inserted[0], name, content_type, len(content), digest)
        state = row[0]
        state['uploaded_files'] = [f for f in state['uploaded_files'] if f['name'] != name] + [info]
        await conn.execute('UPDATE science_agent_sessions SET data=%s,updated_at=now() WHERE id=%s',
                           (Jsonb(state), sid))
    return info


async def get_attachment(sid, subject, name):
    async with await connect() as conn:
        row = await (await conn.execute('''SELECT a.id, a.content_type, a.size_bytes, a.sha256, a.content
            FROM science_agent_attachments a JOIN science_agent_sessions s ON s.id=a.session_id
            WHERE a.session_id=%s AND a.filename=%s AND s.owner_subject=%s AND s.source='user' ''',
            (sid, name, subject))).fetchone()
    if not row:
        raise FileNotFoundError('Attachment not found.')
    content = bytes(row[4])
    if len(content) != row[2] or hashlib.sha256(content).hexdigest() != row[3]:
        raise RuntimeError('Stored attachment verification failed.')
    return {**attachment_info(sid, row[0], name, row[1], row[2], row[3]), 'content': content}


async def delete_attachment(sid, subject, name):
    async with await connect() as conn:
        row = await (await conn.execute("SELECT data FROM science_agent_sessions WHERE id=%s AND owner_subject=%s AND source='user' FOR UPDATE",
                                       (sid, subject))).fetchone()
        if not row:
            raise FileNotFoundError('Conversation not found.')
        await conn.execute('DELETE FROM science_agent_attachments WHERE session_id=%s AND filename=%s', (sid, name))
        state = row[0]
        state['uploaded_files'] = [f for f in state['uploaded_files'] if f['name'] != name]
        await conn.execute('UPDATE science_agent_sessions SET data=%s,updated_at=now() WHERE id=%s', (Jsonb(state), sid))
