from pathlib import Path
from uuid import UUID
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel
from ..auth import identity_for, TapisAuthenticationError
from .. import s3_credentials
from .dependencies import current_user

router = APIRouter(prefix='/api/account', tags=['Account'])


@router.get('/session')
async def account(request: Request):
    try:
        user = await identity_for(request)
    except TapisAuthenticationError as exc:
        return {'connected': False, 'error': str(exc)}
    return {'connected': True, 'account': user.public_dict()}


@router.get('/s3')
async def s3(user=Depends(current_user)):
    return await s3_credentials.settings(user.subject)


async def save_data(request, subject, profile_id=None):
    try:
        data = await request.json()
    except ValueError:
        raise HTTPException(400, 'S3 settings must be a JSON object.') from None
    if not isinstance(data, dict):
        raise HTTPException(400, 'S3 settings must be an object.')
    try:
        profile = await s3_credentials.save_profile(subject, data, profile_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    return {**await s3_credentials.settings(subject), 'saved_profile': profile}


@router.post('/s3', status_code=201)
async def create_s3(request: Request, user=Depends(current_user)):
    return await save_data(request, user.subject)


@router.post('/s3/import', status_code=201)
async def import_s3(file: UploadFile = File(...), name: str = Form(''),
                    endpoint: str = Form(''), bucket: str = Form(''), region: str = Form(''),
                    user=Depends(current_user)):
    try:
        raw = await file.read(64 * 1024 + 1)
        if len(raw) > 64 * 1024:
            raise HTTPException(413, 'Credential file exceeds 64 KiB.')
        data = s3_credentials.parse_credential_file(raw)
        data.update({key:value for key,value in dict(name=name,endpoint=endpoint,bucket=bucket,region=region).items() if value.strip()})
        if not data['name']:
            data['name'] = Path(file.filename or 'Uploaded S3').stem
        profile = await s3_credentials.save_profile(user.subject, data)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    finally:
        await file.close()
    return {**await s3_credentials.settings(user.subject), 'saved_profile': profile}


class S3Selection(BaseModel):
    profile_id: UUID | None


@router.put('/s3/selection')
async def select_s3(data: S3Selection, user=Depends(current_user)):
    await s3_credentials.select_profile(user.subject, data.profile_id)
    return await s3_credentials.settings(user.subject)


@router.put('/s3/{profile_id}')
async def update_s3(profile_id: UUID, request: Request, user=Depends(current_user)):
    return await save_data(request, user.subject, profile_id)


@router.delete('/s3/{profile_id}')
async def delete_s3(profile_id: UUID, user=Depends(current_user)):
    await s3_credentials.delete_profile(user.subject, profile_id)
    return await s3_credentials.settings(user.subject)
