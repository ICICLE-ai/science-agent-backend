"""Apply ordered PostgreSQL migrations and record committed schema history."""
from dataclasses import dataclass
import hashlib
import logging
from pathlib import Path
import re

DIRECTORY = Path(__file__).resolve().parent
LOCK_ID = 781435902
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    checksum: str
    source: str


def discover(directory=None):
    migrations = []
    for path in sorted(Path(directory or DIRECTORY).glob('*.sql')):
        match = re.fullmatch(r'([0-9]{4})_([a-z0-9_]+)\.sql', path.name)
        if not match:
            raise RuntimeError('Migration filenames must use NNNN_name.sql.')
        data = path.read_bytes()
        migrations.append(Migration(int(match[1]), match[2], hashlib.sha256(data).hexdigest(), data.decode('utf-8')))
    if not migrations or [m.version for m in migrations] != list(range(1, len(migrations) + 1)):
        raise RuntimeError('Migrations must have unique, consecutive versions starting at 0001.')
    return migrations


async def run_migrations(conn, directory=None):
    migrations = discover(directory)
    applied = []
    async with conn.transaction():
        await conn.execute('SELECT pg_advisory_xact_lock(%s)', (LOCK_ID,))
        await conn.execute('''CREATE TABLE IF NOT EXISTS science_agent_migration_history (
            version integer PRIMARY KEY,
            name text NOT NULL,
            checksum text NOT NULL CHECK (length(checksum)=64),
            applied_at timestamptz NOT NULL DEFAULT now()
        )''')
        rows = await (await conn.execute('SELECT version,name,checksum FROM science_agent_migration_history ORDER BY version')).fetchall()
        known = {migration.version: migration for migration in migrations}
        for version, name, checksum in rows:
            if version not in known:
                raise RuntimeError('The database contains a migration not included in this backend release.')
            expected = known[version]
            if name != expected.name or checksum != expected.checksum:
                raise RuntimeError(f'Applied migration {version:04d} was modified. Add a new migration instead.')
        completed = [row[0] for row in rows]
        if completed != list(range(1, len(completed) + 1)):
            raise RuntimeError('Database migration history contains a version gap.')
        for migration in migrations[len(completed):]:
            logger.info('Applying database migration %04d_%s', migration.version, migration.name)
            await conn.execute(migration.source, prepare=False)
            await conn.execute('''INSERT INTO science_agent_migration_history(version,name,checksum)
                VALUES (%s,%s,%s)''', (migration.version, migration.name, migration.checksum))
            applied.append(migration.version)
    return applied
