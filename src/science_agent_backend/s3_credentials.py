"""User-owned named S3 credentials stored in PostgreSQL and selected explicitly."""
import configparser
import io
import json
import os
import re
from urllib.parse import urlsplit
from uuid import uuid4

from dotenv import dotenv_values
from psycopg.errors import UniqueViolation
from .database import connect


def validate_profile(data):
    name = str(data.get('name') or '').strip()
    if not name or len(name) > 120 or any(c in name for c in '\r\n\0'):
        raise ValueError('Enter a credential name (up to 120 characters).')
    endpoint = str(data.get('endpoint') or '').strip().rstrip('/')
    url = urlsplit(endpoint)
    approved = {host.strip().lower() for host in os.getenv('S3_ALLOWED_ENDPOINT_HOSTS', '').split(',') if host.strip()}
    try:
        port = url.port
    except ValueError:
        raise ValueError('Invalid S3 endpoint port.') from None
    if (url.scheme != 'https' or not url.hostname or url.username or url.password
            or port not in (None, 443) or url.path or url.query or url.fragment
            or len(endpoint) > 2048 or any(c.isspace() for c in endpoint)):
        raise ValueError('Enter an HTTPS S3 endpoint without a path or embedded credentials.')
    if approved and url.hostname.lower() not in approved:
        raise ValueError('This S3 endpoint is not allowed by the server.')
    bucket = str(data.get('bucket') or '').strip()
    region = str(data.get('region') or '').strip()
    if not re.fullmatch(r'[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]', bucket) or '..' in bucket:
        raise ValueError('Enter a valid S3 bucket name.')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', region):
        raise ValueError('Enter a valid S3 region.')
    return dict(name=name, endpoint=endpoint, bucket=bucket, region=region)


def public_profile(row):
    return dict(id=str(row[0]), name=row[1], endpoint=row[2], bucket=row[3],
                region=row[4], selected=row[5])


async def list_profiles(subject):
    async with await connect() as conn:
        rows = await (await conn.execute('''SELECT id,name,endpoint,bucket,region,is_selected
            FROM science_agent_s3_credentials WHERE owner_subject=%s ORDER BY created_at,id''',
            (subject,))).fetchall()
    return [public_profile(row) for row in rows]


async def settings(subject):
    profiles = await list_profiles(subject)
    selected = next((profile for profile in profiles if profile['selected']), None)
    return dict(configured=selected is not None, profile=selected, profiles=profiles,
                selected_profile_id=selected['id'] if selected else None)


async def load_profile(subject, profile_id=None, *, include_secrets=False):
    condition = 'id=%s' if profile_id is not None else 'is_selected'
    values = (subject, profile_id) if profile_id is not None else (subject,)
    async with await connect() as conn:
        row = await (await conn.execute('''SELECT id,name,endpoint,bucket,region,is_selected,access_key_id,secret_access_key
            FROM science_agent_s3_credentials WHERE owner_subject=%s AND ''' + condition,
            values)).fetchone()
    if not row:
        if profile_id is not None:
            raise FileNotFoundError('S3 credentials not found.')
        return None
    profile = public_profile(row)
    if include_secrets:
        profile.update(access_key_id=row[6], secret_access_key=row[7])
    return profile


async def save_profile(subject, data, profile_id=None):
    profile = validate_profile(data)
    access = str(data.get('access_key_id') or '').strip()
    secret = str(data.get('secret_access_key') or '').strip()
    if profile_id is not None:
        existing = await load_profile(subject, profile_id, include_secrets=True)
        if not access and not secret:
            access, secret = existing['access_key_id'], existing['secret_access_key']
    if not access or not secret:
        raise ValueError('Both S3 access key and secret key are required.')
    if len(access) > 512 or len(secret) > 4096 or any(c in access + secret for c in '\r\n\0'):
        raise ValueError('Invalid S3 credentials.')
    identifier = str(profile_id or uuid4())
    try:
        async with await connect() as conn:
            if profile_id is None:
                await conn.execute('''INSERT INTO science_agent_s3_credentials
                    (id,owner_subject,name,endpoint,bucket,region,access_key_id,secret_access_key)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)''',
                    (identifier,subject,profile['name'],profile['endpoint'],profile['bucket'],profile['region'],access,secret))
            else:
                result = await conn.execute('''UPDATE science_agent_s3_credentials SET
                    name=%s,endpoint=%s,bucket=%s,region=%s,access_key_id=%s,secret_access_key=%s,updated_at=now()
                    WHERE id=%s AND owner_subject=%s''',
                    (profile['name'],profile['endpoint'],profile['bucket'],profile['region'],access,secret,identifier,subject))
                if not result.rowcount:
                    raise FileNotFoundError('S3 credentials not found.')
    except UniqueViolation:
        raise ValueError('A credential with this name already exists.') from None
    return await load_profile(subject, identifier)


async def select_profile(subject, profile_id):
    async with await connect() as conn:
        # Serialize selection changes for this account before replacing its selected row.
        user = await (await conn.execute('SELECT subject FROM science_agent_users WHERE subject=%s FOR UPDATE',
                                        (subject,))).fetchone()
        if not user:
            raise FileNotFoundError('Account not found.')
        if profile_id is not None:
            owned = await (await conn.execute('SELECT id FROM science_agent_s3_credentials WHERE id=%s AND owner_subject=%s',
                                             (profile_id, subject))).fetchone()
            if not owned:
                raise FileNotFoundError('S3 credentials not found.')
        await conn.execute('UPDATE science_agent_s3_credentials SET is_selected=false WHERE owner_subject=%s AND is_selected',
                           (subject,))
        if profile_id is not None:
            result = await conn.execute('UPDATE science_agent_s3_credentials SET is_selected=true,updated_at=now() WHERE id=%s AND owner_subject=%s',
                                       (profile_id, subject))
            if not result.rowcount:
                raise FileNotFoundError('S3 credentials not found.')


async def delete_profile(subject, profile_id):
    async with await connect() as conn:
        result = await conn.execute('DELETE FROM science_agent_s3_credentials WHERE owner_subject=%s AND id=%s',
                                    (subject, profile_id))
        if not result.rowcount:
            raise FileNotFoundError('S3 credentials not found.')


def parse_credential_file(raw):
    try:
        text = raw.decode('utf-8-sig').strip()
        if text.startswith('{'):
            data = json.loads(text)
            if not isinstance(data, dict):
                raise ValueError()
        elif text.startswith('['):
            parser = configparser.ConfigParser(interpolation=None)
            parser.read_string(text)
            sections = parser.sections()
            if len(sections) > 1:
                raise ValueError('Upload one credential profile per file.')
            data = dict(parser[sections[0]]) if sections else dict(parser.defaults())
        else:
            data = dict(dotenv_values(stream=io.StringIO(text), interpolate=False))
    except (UnicodeError, json.JSONDecodeError, configparser.Error):
        raise ValueError('Upload a UTF-8 JSON, .env, or single-profile INI credential file.') from None
    lowered = {str(key).lower(): value for key, value in data.items()}
    aliases = dict(name=('name','profile_name'), endpoint=('endpoint','aws_endpoint_url_s3','aws_endpoint_url','s3_endpoint'),
        bucket=('bucket','bucket_name','s3_bucket'), region=('region','aws_region','aws_default_region'),
        access_key_id=('access_key_id','aws_access_key_id'), secret_access_key=('secret_access_key','aws_secret_access_key'))
    return {field: next((lowered[key] for key in keys if lowered.get(key)), '')
            for field, keys in aliases.items()}
