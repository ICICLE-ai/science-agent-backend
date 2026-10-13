"""Migration behavior checks against isolated schemas in the configured PostgreSQL DB."""
import asyncio
from contextlib import asynccontextmanager
import hashlib
import os
import shutil
from uuid import uuid4
import psycopg
from psycopg import sql
import pytest
from science_agent_backend import database, migrations


@asynccontextmanager
async def isolated_schema():
    name = 'science_agent_migration_test_' + uuid4().hex
    async with await database.connect() as admin:
        await admin.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(name)))
        await admin.commit()
        async def open_connection():
            conn = await database.connect()
            try:
                await conn.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(name)))
                await conn.commit()
            except Exception:
                await conn.close()
                raise
            return conn
        try:
            yield open_connection
        finally:
            await admin.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(name)))
            await admin.commit()


def migration_files(tmp_path):
    first = tmp_path/'0001_initial_schema.sql'
    shutil.copyfile(migrations.DIRECTORY/first.name, first)
    return first


def test_discovery_rejects_missing_initial_version(tmp_path):
    (tmp_path/'0002_skipped_initial.sql').write_text('SELECT 1;')
    with pytest.raises(RuntimeError, match='consecutive'):
        migrations.discover(tmp_path)


requires_database = pytest.mark.skipif(os.getenv('SCIENCE_AGENT_TEST_DATABASE') != '1',
                                      reason='Requires an explicitly selected real PostgreSQL database')


@requires_database
def test_first_connection_creates_tables_and_initial_history():
    async def scenario():
        async with isolated_schema() as open_connection:
            async with await open_connection() as conn:
                assert await migrations.run_migrations(conn)==[1]
                rows = await (await conn.execute('SELECT version,name,checksum,applied_at FROM science_agent_migration_history')).fetchall()
                assert len(rows)==1 and rows[0][:2]==(1,'initial_schema')
                assert rows[0][2]==hashlib.sha256((migrations.DIRECTORY/'0001_initial_schema.sql').read_bytes()).hexdigest()
                assert rows[0][3] is not None
                for name in ('science_agent_users','science_agent_sessions','science_agent_attachments','science_agent_s3_credentials'):
                    assert (await (await conn.execute('SELECT to_regclass(%s)',(name,))).fetchone())[0] is not None
            async with await open_connection() as conn:
                assert await migrations.run_migrations(conn)==[]
                assert (await (await conn.execute('SELECT count(*) FROM science_agent_migration_history')).fetchone())[0]==1
    asyncio.run(scenario())


@requires_database
def test_existing_tables_are_adopted_without_losing_data():
    async def scenario():
        async with isolated_schema() as open_connection:
            async with await open_connection() as conn:
                await conn.execute((migrations.DIRECTORY/'0001_initial_schema.sql').read_text(),prepare=False)
                await conn.execute("INSERT INTO science_agent_users(subject,tenant_id,username) VALUES ('existing@test','test','existing')")
                await conn.execute('''INSERT INTO science_agent_s3_credentials
                    (owner_subject,name,endpoint,bucket,region,access_key_id,secret_access_key,is_selected)
                    VALUES ('existing@test','Existing S3','https://storage.example.org','test-images','us-east-1','test-access','test-secret',true)''')
                before = await (await conn.execute('SELECT * FROM science_agent_s3_credentials')).fetchall()
                await conn.commit()
                assert await migrations.run_migrations(conn)==[1]
                assert await (await conn.execute('SELECT * FROM science_agent_s3_credentials')).fetchall()==before
                assert (await (await conn.execute('SELECT count(*) FROM science_agent_users')).fetchone())[0]==1
    asyncio.run(scenario())


@requires_database
def test_new_migration_is_applied_once(tmp_path):
    migration_files(tmp_path)
    async def scenario():
        async with isolated_schema() as open_connection:
            async with await open_connection() as conn:
                assert await migrations.run_migrations(conn,tmp_path)==[1]
                (tmp_path/'0002_add_example.sql').write_text('CREATE TABLE migration_example(id integer PRIMARY KEY);')
                assert await migrations.run_migrations(conn,tmp_path)==[2]
                assert await migrations.run_migrations(conn,tmp_path)==[]
                versions = await (await conn.execute('SELECT version FROM science_agent_migration_history ORDER BY version')).fetchall()
                assert versions==[(1,),(2,)]
    asyncio.run(scenario())


@requires_database
def test_failed_initialization_rolls_back_tables_and_history(tmp_path):
    migration_files(tmp_path)
    (tmp_path/'0002_broken.sql').write_text('CREATE TABLE must_rollback(id integer); SELECT 1/0;')
    async def scenario():
        async with isolated_schema() as open_connection:
            async with await open_connection() as conn:
                with pytest.raises(psycopg.errors.DivisionByZero):
                    await migrations.run_migrations(conn,tmp_path)
                for name in ('science_agent_migration_history','science_agent_users','must_rollback'):
                    assert (await (await conn.execute('SELECT to_regclass(%s)',(name,))).fetchone())[0] is None
    asyncio.run(scenario())


@requires_database
def test_failed_upgrade_preserves_previous_history(tmp_path):
    migration_files(tmp_path)
    async def scenario():
        async with isolated_schema() as open_connection:
            async with await open_connection() as conn:
                assert await migrations.run_migrations(conn,tmp_path)==[1]
                (tmp_path/'0002_broken.sql').write_text('CREATE TABLE must_rollback(id integer); SELECT 1/0;')
                with pytest.raises(psycopg.errors.DivisionByZero):
                    await migrations.run_migrations(conn,tmp_path)
                assert (await (await conn.execute('SELECT count(*) FROM science_agent_migration_history')).fetchone())[0]==1
                assert (await (await conn.execute("SELECT to_regclass('must_rollback')")).fetchone())[0] is None
    asyncio.run(scenario())


@requires_database
def test_concurrent_first_connections_apply_initialization_once():
    async def scenario():
        async with isolated_schema() as open_connection:
            async def initialize():
                async with await open_connection() as conn:
                    return await migrations.run_migrations(conn)
            results = await asyncio.gather(initialize(),initialize())
            assert sorted(results,key=len)==[[],[1]]
            async with await open_connection() as conn:
                assert (await (await conn.execute('SELECT count(*) FROM science_agent_migration_history')).fetchone())[0]==1
    asyncio.run(scenario())


@requires_database
def test_applied_sql_changes_are_rejected(tmp_path):
    first = migration_files(tmp_path)
    async def scenario():
        async with isolated_schema() as open_connection:
            async with await open_connection() as conn:
                assert await migrations.run_migrations(conn,tmp_path)==[1]
                first.write_text(first.read_text()+'\n-- modified after application\n')
                with pytest.raises(RuntimeError,match='was modified'):
                    await migrations.run_migrations(conn,tmp_path)
                assert (await (await conn.execute('SELECT count(*) FROM science_agent_migration_history')).fetchone())[0]==1
    asyncio.run(scenario())
