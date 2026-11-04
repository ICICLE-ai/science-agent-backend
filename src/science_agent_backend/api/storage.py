import asyncio
from urllib.parse import quote

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask

from .. import s3_credentials
from .dependencies import current_user

router = APIRouter(prefix='/api/storage', tags=['Storage'])
ROOT_PREFIX = 'science-agent/'


def storage_key(value, *, prefix=False, deleting=False):
    if (not value or not value.startswith(ROOT_PREFIX) or '\\' in value
            or any(part in {'.', '..'} for part in value.split('/'))
            or any(ord(char) < 32 or ord(char) == 127 for char in value)
            or len(value.encode('utf-8')) > 1024):
        raise HTTPException(400, 'Storage paths must stay inside science-agent/.')
    if prefix:
        if not value.endswith('/'):
            raise HTTPException(400, 'Folder prefixes must end with /.')
        if deleting and value == ROOT_PREFIX:
            raise HTTPException(400, 'The science-agent/ root cannot be deleted.')
    elif value.endswith('/'):
        raise HTTPException(400, 'Choose an object, not a folder prefix.')
    return value


def create_client(profile):
    return boto3.client('s3', endpoint_url=profile['endpoint'], region_name=profile['region'],
        aws_access_key_id=profile['access_key_id'], aws_secret_access_key=profile['secret_access_key'],
        config=Config(signature_version='s3v4', connect_timeout=8, read_timeout=30,
            retries={'max_attempts': 1},
            s3={'addressing_style': 'path', 'payload_signing_enabled': True}))


async def selected_storage(user=Depends(current_user)):
    profile = await s3_credentials.load_profile(user.subject, include_secrets=True)
    if not profile:
        raise HTTPException(409, 'Select an S3 credential profile in Settings first.')
    try:
        s3_credentials.validate_profile(profile)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    if not profile.get('access_key_id') or not profile.get('secret_access_key'):
        raise HTTPException(409, 'Update the selected S3 credential profile in Settings.')
    client = await asyncio.to_thread(create_client, profile)
    try:
        yield profile, client
    finally:
        await asyncio.to_thread(client.close)


async def s3_call(client, operation, **kwargs):
    try:
        return await asyncio.to_thread(getattr(client, operation), **kwargs)
    except ClientError as exc:
        code = exc.response.get('Error', {}).get('Code', '')
        status = exc.response.get('ResponseMetadata', {}).get('HTTPStatusCode')
        if status == 403 or code in {'AccessDenied', 'InvalidAccessKeyId', 'SignatureDoesNotMatch',
                                     'ExpiredToken', 'InvalidToken'}:
            raise HTTPException(403, 'S3 access denied. Check the selected credentials and bucket permissions.') from None
        if status == 404 or code in {'NoSuchBucket', 'NoSuchKey', 'NotFound'}:
            raise HTTPException(404, 'The requested S3 bucket or object was not found.') from None
        raise HTTPException(502, 'S3 could not complete the request. Try refreshing before retrying.') from None
    except BotoCoreError:
        raise HTTPException(503, 'The selected S3 endpoint is unavailable. Try again later.') from None


@router.get('/objects', operation_id='storage_list_objects')
async def list_objects(prefix: str = ROOT_PREFIX,
                       continuation_token: str | None = Query(default=None, min_length=1, max_length=8192),
                       storage=Depends(selected_storage)):
    prefix = storage_key(prefix, prefix=True)
    profile, client = storage
    params = dict(Bucket=profile['bucket'], Prefix=prefix, Delimiter='/', MaxKeys=1000)
    if continuation_token:
        params['ContinuationToken'] = continuation_token
    page = await s3_call(client, 'list_objects_v2', **params)
    truncated = bool(page.get('IsTruncated'))
    token = page.get('NextContinuationToken') if truncated else None
    if truncated and (not token or token == continuation_token):
        raise HTTPException(502, 'S3 returned an incomplete object listing. Refresh and try again.')
    return dict(bucket=profile['bucket'], endpoint=profile['endpoint'], prefix=prefix,
        folders=[dict(name=item['Prefix'][len(prefix):].rstrip('/'), prefix=item['Prefix'])
                 for item in page.get('CommonPrefixes', [])],
        objects=[dict(key=item['Key'], name=item['Key'][len(prefix):], size=item['Size'],
                      last_modified=item['LastModified'].isoformat(), etag=item.get('ETag', '').strip('"'))
                 for item in page.get('Contents', []) if item['Key'] != prefix],
        is_truncated=truncated, next_continuation_token=token)


@router.get('/download', operation_id='storage_download_object')
async def download_object(key: str, storage=Depends(selected_storage)):
    key = storage_key(key)
    profile, client = storage
    result = await s3_call(client, 'get_object', Bucket=profile['bucket'], Key=key)
    body = result['Body']

    def chunks():
        try:
            yield from body.iter_chunks(chunk_size=1024 * 1024)
        finally:
            body.close()

    headers = {'Content-Disposition': f"attachment; filename*=UTF-8''{quote(key.rsplit('/', 1)[-1], safe='')}",
               'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'}
    if result.get('ContentLength') is not None:
        headers['Content-Length'] = str(result['ContentLength'])
    return StreamingResponse(chunks(), media_type='application/octet-stream', headers=headers,
                             background=BackgroundTask(body.close))


@router.delete('/object', operation_id='storage_delete_object')
async def delete_object(key: str, storage=Depends(selected_storage)):
    key = storage_key(key)
    profile, client = storage
    await s3_call(client, 'delete_object', Bucket=profile['bucket'], Key=key)
    return dict(deleted=True, deleted_count=1, key=key)


@router.delete('/prefix', operation_id='storage_delete_prefix')
async def delete_prefix(prefix: str, storage=Depends(selected_storage)):
    prefix = storage_key(prefix, prefix=True, deleting=True)
    profile, client = storage
    deleted = 0
    token = None
    seen_tokens = set()
    try:
        while True:
            params = dict(Bucket=profile['bucket'], Prefix=prefix, MaxKeys=1000)
            if token:
                params['ContinuationToken'] = token
            page = await s3_call(client, 'list_objects_v2', **params)
            keys = [item['Key'] for item in page.get('Contents', [])]
            if any(not key.startswith(prefix) for key in keys):
                raise HTTPException(502, 'S3 returned objects outside the requested folder.')
            if keys:
                result = await s3_call(client, 'delete_objects', Bucket=profile['bucket'],
                    Delete={'Objects': [{'Key': key} for key in keys], 'Quiet': True})
                errors = result.get('Errors', [])
                deleted += len(keys) - len(errors)
                if errors:
                    raise HTTPException(502, 'S3 did not delete every object in the folder.')
            if not page.get('IsTruncated'):
                break
            token = page.get('NextContinuationToken')
            if not token or token in seen_tokens:
                raise HTTPException(502, 'S3 returned an incomplete folder listing.')
            seen_tokens.add(token)
    except HTTPException as exc:
        if deleted:
            raise HTTPException(exc.status_code,
                f'Folder deletion stopped after {deleted} object(s) were deleted. Refresh to check remaining objects before retrying.') from None
        raise
    return dict(deleted=True, deleted_count=deleted, prefix=prefix)
