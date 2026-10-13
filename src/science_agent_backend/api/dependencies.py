from fastapi import Request
from ..auth import identity_for


async def current_user(request: Request):
    return await identity_for(request)
