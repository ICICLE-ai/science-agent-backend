import mimetypes
from pathlib import Path
from urllib.parse import quote
from uuid import UUID
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from .. import config, database
from ..runtime_state import active_sessions
from .dependencies import current_user

router = APIRouter(prefix='/api/execution/upload', tags=['Attachments'])


def validate_filename(name):
    if not name or Path(name).name != name or name in {'.', '..'} or '\\' in name or '\x00' in name:
        raise HTTPException(400, 'Invalid filename.')
    return name


@router.post('/{sid}')
async def upload(sid: UUID, file: UploadFile = File(...), user=Depends(current_user)):
    await database.get(sid, user.subject)
    if str(sid) in active_sessions:
        raise HTTPException(409, 'Wait for the request before changing files.')
    try:
        name = validate_filename(file.filename)
        content = bytearray()
        while chunk := await file.read(1024 * 1024):
            if len(content) + len(chunk) > config.UPLOAD_LIMIT:
                raise HTTPException(413, 'File exceeds the upload limit.')
            content.extend(chunk)
        content_type = mimetypes.guess_type(name)[0] or file.content_type or 'application/octet-stream'
        info = await database.put_attachment(sid, user.subject, name, content_type, bytes(content))
        return {**info, 'fileId': info['object_name']}
    finally:
        await file.close()


@router.get('/{sid}/{filename}')
async def download_upload(sid: UUID, filename: str, user=Depends(current_user)):
    attachment = await database.get_attachment(sid, user.subject, validate_filename(filename))
    return Response(attachment['content'], media_type=attachment['content_type'], headers={
        'Content-Disposition': "attachment; filename*=UTF-8''" + quote(attachment['name'], safe=''),
        'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff',
    })


@router.delete('/{sid}/{filename}')
async def delete_upload(sid: UUID, filename: str, user=Depends(current_user)):
    await database.get(sid, user.subject)
    if str(sid) in active_sessions:
        raise HTTPException(409, 'Wait for the request before changing files.')
    await database.delete_attachment(sid, user.subject, validate_filename(filename))
    return {'message': 'File deleted.'}
