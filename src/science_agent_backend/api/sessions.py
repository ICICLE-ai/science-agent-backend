from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from .. import database
from ..runtime_state import active_sessions
from .dependencies import current_user

router = APIRouter(prefix='/api/execution', tags=['Conversations'])


class ValidateSession(BaseModel):
    agent_session_id: UUID


@router.post('/agent_session')
async def create(user=Depends(current_user)):
    return {'agent_session_id': await database.create(user.subject)}


@router.post('/agent_session/validate')
async def validate(data: ValidateSession, user=Depends(current_user)):
    await database.get(data.agent_session_id, user.subject)
    return {'message': 'Valid session'}


@router.get('/agent_sessions')
async def sessions(user=Depends(current_user)):
    return await database.listing(user.subject)


@router.delete('/agent_session/{sid}')
async def delete(sid: UUID, user=Depends(current_user)):
    if str(sid) in active_sessions:
        raise HTTPException(409, 'Stop the request before deleting this conversation.')
    await database.delete(sid, user.subject)
    return {'agent_session_id': str(sid), 'external_resources_retained': True, 'message': 'Conversation deleted.'}
