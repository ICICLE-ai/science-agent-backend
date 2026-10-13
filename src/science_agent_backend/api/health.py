from fastapi import APIRouter

router = APIRouter(tags=['Health'])

@router.get("/health")
async def health_check():
    return {"status": "ok"}


@router.get('/healthcheck')
async def healthcheck():
    return {'status': 'ok', 'agent_backend': 'pod', 'framework': 'fastapi'}
