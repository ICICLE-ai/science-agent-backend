from fastapi import APIRouter, Depends, HTTPException
from .dependencies import current_user

router = APIRouter(prefix='/api/storage', tags=['Storage'])


@router.get('/{operation}', operation_id='storage_browser_get')
@router.delete('/{operation}', operation_id='storage_browser_delete')
async def storage_pending(user=Depends(current_user)):
    raise HTTPException(501, 'S3 management has not been migrated to this initial backend.')
