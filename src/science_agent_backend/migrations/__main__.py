"""Apply pending migrations using the configured DATABASE_URL."""
import asyncio
from .. import database


async def main():
    applied = await database.initialize()
    print('Applied migrations:', ', '.join(f'{version:04d}' for version in applied) or 'none (up to date)')
    async with await database.connect() as conn:
        rows = await (await conn.execute('SELECT version,name,applied_at FROM science_agent_migration_history ORDER BY version')).fetchall()
    for version, name, timestamp in rows:
        print(f'{version:04d} {name} {timestamp.isoformat()}')


if __name__ == '__main__':
    asyncio.run(main())
