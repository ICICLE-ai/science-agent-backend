from fastapi import APIRouter, Depends, HTTPException
from .dependencies import current_user

router = APIRouter(prefix='/api/storage', tags=['Storage'])


@router.api_route('/{operation}', methods=['GET', 'DELETE'])
async def storage_pending(user=Depends(current_user)):
    raise HTTPException(501, 'S3 management has not been migrated to this initial backend.')
