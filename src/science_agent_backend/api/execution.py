import asyncio
from contextlib import suppress
from uuid import UUID, uuid4
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from .. import config, database
from ..agent_runtime import run
from ..auth import identity_for, TapisAuthenticationError, origin_is_allowed
from ..runtime_state import active_sessions

router = APIRouter(prefix='/api/execution', tags=['Agent'])


@router.websocket('/ws/{sid}')
async def websocket(ws: WebSocket, sid: UUID):
    if not origin_is_allowed(ws.headers.get('origin')):
        await ws.close(4403)
        return
    try:
        user = await identity_for(ws)
        state = await database.get(sid, user.subject)
    except TapisAuthenticationError:
        await ws.close(4401)
        return
    except FileNotFoundError:
        await ws.close(4404)
        return
    await ws.accept()
    sid, task = str(sid), None
    send_lock = asyncio.Lock()

    async def send(data):
        async with send_lock:
            await ws.send_json(data)

    await send(dict(type='state', state=state, has_default_llm=bool(config.POD_URL), agent_backend='pod'))

    async def execute(data):
        cid = data['command_id']
        try:
            state = await database.get(sid, user.subject)
            message = data.get('message') if data['command'] == 'follow_up' else state['task_instruction']
            if not isinstance(message, str) or not message.strip():
                raise ValueError('A message is required.')
            item = dict(id=str(uuid4()), role='user', tag='user', content=message)
            await database.mutate(sid, user.subject, lambda d: d['history'].append(item))
            await send(dict(type='response_start', id=item['id'], role='user', tag='user'))
            await send(dict(type='response_chunk', id=item['id'], text=message))
            await send(dict(type='response_end', id=item['id']))
            await run(sid, user, message, send)
            await send({'command_id': cid})
        except asyncio.CancelledError:
            with suppress(Exception):
                await send(dict(type='error', command_id=cid, message='Request cancelled. Check remote operations before retrying.'))
            raise
        except Exception as exc:
            message = str(exc) if isinstance(exc, (RuntimeError, ValueError)) else 'Request failed. Check backend service logs.'
            if user.token:
                message = message.replace(user.token, '[REDACTED]')
            await send(dict(type='error', command_id=cid, message=message))
        finally:
            active_sessions.discard(sid)

    try:
        while True:
            data = await ws.receive_json()
            if not isinstance(data, dict) or not isinstance(data.get('command_id'), int):
                await send(dict(type='error', message='Invalid command.'))
                continue
            cid, command = data['command_id'], data.get('command')
            if command in {'solve_task', 'follow_up'}:
                if sid in active_sessions:
                    await send(dict(type='error', command_id=cid, message='A request is already running.'))
                else:
                    active_sessions.add(sid)
                    task = asyncio.create_task(execute(data))
            elif command == 'cancel':
                if task and not task.done():
                    task.cancel()
                    with suppress(asyncio.CancelledError):
                        await task
                await send({'command_id': cid})
            elif command == 'update_task_inputs':
                fields = {k: data.get(k, '') for k in ('task_instruction', 'domain_knowledge', 'description')}
                if not all(isinstance(v, str) for v in fields.values()):
                    await send(dict(type='error', command_id=cid, message='Inputs must be text.'))
                    continue
                await database.mutate(sid, user.subject, lambda d: d.update(fields))
                await send({'command_id': cid})
            else:
                await send(dict(type='error', command_id=cid, message='Command not supported by the remote agent backend.'))
    except WebSocketDisconnect:
        pass
    finally:
        if task and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await task
