from uuid import UUID
from fastapi import APIRouter, Depends
from .. import database
from .dependencies import current_user

router = APIRouter(prefix='/api/tasks', tags=['Tasks'])


@router.get('/')
async def benchmarks():
    return []  # Gallery compatibility while the benchmark engine is not enabled.


@router.get('/{sid}')
async def detail(sid: UUID, user=Depends(current_user)):
    return await database.get(sid, user.subject)
