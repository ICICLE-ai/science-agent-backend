from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from . import config, database
from .auth import TapisAuthenticationError, origin_is_allowed
from .api import account, execution, files, health, sessions, storage, tasks


@asynccontextmanager
async def lifespan(app):
    await database.initialize()
    yield


app = FastAPI(title='Science Agent API', lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=list(config.FRONTEND_ORIGINS),
                   allow_credentials=True, allow_methods=['GET', 'POST', 'DELETE', 'PUT'], allow_headers=['Content-Type'])


@app.middleware('http')
async def check_origin(request, call_next):
    if request.method not in {'GET', 'HEAD', 'OPTIONS'} and not origin_is_allowed(request.headers.get('origin')):
        return JSONResponse({'error': 'Origin not allowed.'}, status_code=403)
    return await call_next(request)


@app.exception_handler(TapisAuthenticationError)
async def auth_error(request, exc):
    return JSONResponse({'error': str(exc)}, status_code=401)


@app.exception_handler(FileNotFoundError)
async def missing(request, exc):
    return JSONResponse({'error': 'Requested resource not found.'}, status_code=404)


@app.exception_handler(HTTPException)
async def http_error(request, exc):
    return JSONResponse({'error': exc.detail}, status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def invalid(request, exc):
    return JSONResponse({'error': 'Invalid request.'}, status_code=422)


for router in (health.router, account.router, sessions.router, files.router,
               execution.router, tasks.router, storage.router):
    app.include_router(router)
