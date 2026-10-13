"""One-time conversion of legacy encrypted credentials to DB credential columns."""
import asyncio
import json
import os
from cryptography.fernet import Fernet, InvalidToken
from . import database


async def migrate():
    async with await database.connect() as conn:
        await conn.execute('SELECT pg_advisory_xact_lock(781435902)')
        columns = {row[0] for row in await (await conn.execute('''SELECT column_name
            FROM information_schema.columns WHERE table_schema=current_schema()
            AND table_name='science_agent_s3_credentials' ''')).fetchall()}
        if 'encrypted_keys' not in columns:
            return 0
        await conn.execute('LOCK TABLE science_agent_s3_credentials IN ACCESS EXCLUSIVE MODE')
        await conn.execute('ALTER TABLE science_agent_s3_credentials ADD COLUMN IF NOT EXISTS access_key_id text')
        await conn.execute('ALTER TABLE science_agent_s3_credentials ADD COLUMN IF NOT EXISTS secret_access_key text')
        identity_column = 'id' if 'id' in columns else 'NULL'
        rows = await (await conn.execute('SELECT '+identity_column+',owner_subject,encrypted_keys FROM science_agent_s3_credentials')).fetchall()
        legacy_key = os.getenv('S3_CREDENTIAL_ENCRYPTION_KEY')
        if rows and not legacy_key:
            raise RuntimeError('The previous encryption key is required once to convert existing records. No data was changed.')
        try:
            cipher = Fernet(legacy_key.encode()) if rows else None
            for identifier, owner, encrypted in rows:
                values = json.loads(cipher.decrypt(encrypted.encode()))
                if values.get('owner_subject') != owner:
                    raise ValueError('Owner mismatch')
                if values.get('profile_id') is not None and values['profile_id'] != str(identifier):
                    raise ValueError('Credential ID mismatch')
                access, secret = values['access_key_id'], values['secret_access_key']
                if not isinstance(access, str) or not isinstance(secret, str) or not access or not secret:
                    raise ValueError('Missing credential values')
                if identifier is None:
                    await conn.execute('''UPDATE science_agent_s3_credentials SET access_key_id=%s,secret_access_key=%s
                        WHERE owner_subject=%s''', (access, secret, owner))
                else:
                    await conn.execute('''UPDATE science_agent_s3_credentials SET access_key_id=%s,secret_access_key=%s
                        WHERE id=%s AND owner_subject=%s''', (access, secret, identifier, owner))
            verified = await (await conn.execute('SELECT count(*) FROM science_agent_s3_credentials WHERE access_key_id IS NOT NULL AND secret_access_key IS NOT NULL')).fetchone()
            if verified[0] != len(rows):
                raise ValueError('Conversion verification failed')
        except (InvalidToken, ValueError, KeyError, TypeError):
            raise RuntimeError('Existing credentials could not be converted. The transaction was rolled back.') from None
        await conn.execute('ALTER TABLE science_agent_s3_credentials ALTER COLUMN access_key_id SET NOT NULL')
        await conn.execute('ALTER TABLE science_agent_s3_credentials ALTER COLUMN secret_access_key SET NOT NULL')
        await conn.execute('ALTER TABLE science_agent_s3_credentials DROP COLUMN encrypted_keys')
    return len(rows)


if __name__ == '__main__':
    async def main():
        converted = await migrate()
        await database.initialize()
        print('Converted credential records:', converted)
    asyncio.run(main())
