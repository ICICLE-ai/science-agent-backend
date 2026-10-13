"""Remote pod transport, without Docker or a local LLM runtime."""
import asyncio
import fcntl
import json
import tempfile
import time
import hashlib
from pathlib import Path
from uuid import uuid4
from . import config, database
from .pod_terminal import PodTerminal
from .pod_files import file_channel


async def transfer_attachments(channel, prefix, sid, subject, uploaded_files, progress):
    files, total = [], 0
    for info in uploaded_files:
        name = info['name']
        if Path(name).name != name or name in {'.', '..'} or '\\' in name or '\x00' in name:
            raise RuntimeError('Invalid upload filename.')
        attachment = await database.get_attachment(sid, subject, name)
        total += attachment['size']
        if total > config.UPLOAD_LIMIT:
            raise RuntimeError('Uploaded files exceed the remote transfer limit.')
        result = await channel.put(prefix + '/uploads/' + name, attachment['content'])
        files.append({'name': name, **result})
        await progress(f'Transferred and verified {name}')
    return files


async def run(sid, identity, message, send):
    if not config.POD_TOKEN:
        raise RuntimeError('Agent service credential is not configured.')
    run_id = str(uuid4())

    async def progress(detail):
        await send(dict(type='workflow_progress', run_id=run_id, step_id='agent',
                        label='Remote Science Agent', status='running', timestamp=time.time(), detail=detail))

    with (Path(tempfile.gettempdir()) / 'science-agent-pod.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('The shared agent is busy. Please try again later.') from None
        prefix = f'sessions/{sid}/runs/{run_id}'
        private = prefix + '/context.json'
        written = False
        try:
            state = await database.get(sid, identity.subject)
            from .s3_credentials import load_profile
            s3 = await load_profile(identity.subject, include_secrets=True)
            await progress('Connecting and transferring service instructions')
            async with file_channel(config.POD_URL, config.POD_TOKEN) as channel:
                root = channel.info['root']
                for path in config.SKILLS_DIR.rglob('*'):
                    if path.is_file() and '__pycache__' not in path.parts:
                        await channel.put(prefix + '/skill/' + path.relative_to(config.SKILLS_DIR).as_posix(), path.read_bytes())
                files = await transfer_attachments(channel, prefix, sid, identity.subject,
                                                   state['uploaded_files'], progress)
                written = True
                await channel.put(private, json.dumps(dict(files=files, tapis_token=identity.token,
                    smart_labeler_url=config.SMART_LABELER_BASE_URL, arraymorph_url='', s3=s3,
                    session_id=sid, run_id=run_id, user_request=message,
                    storage_namespace=hashlib.sha256(identity.subject.encode()).hexdigest(),
                    tapis_base_url=config.TAPIS_BASE_URL, tapis_system='expanse-tapis-static',
                    tapis_base_dir=f'/users/{identity.username}/demo')).encode())
            context = [{'role': h['role'], 'content': h['content']} for h in state['history'][-8:]]
            previous_runs = []
            for entry in state['execution_log']:
                if entry.get('type') == 'pod_services':
                    for observation in entry.get('observations', []):
                        if 'stages' in observation and 'run_id' in observation:
                            previous_runs.append(observation)
            prompt = (
                'You are Science Agent. Use only the supplied conversation and files, not other users history. '
                f'Conversation: {sid}. History: {json.dumps(context, ensure_ascii=False)[-12000:]}\n'
                f'Previous recorded workflow reports: {json.dumps(previous_runs[-3:])}\n'
                'For S3 operations use only the selected credential in the private context. '
                'If none is selected, ask the user to select saved credentials in Settings. '
                'Never use global AWS environment values or local credential files as a fallback. '
                f'Domain: {state["domain_knowledge"]}\nRequest: {message}\n'
                f'Read {root}/{prefix}/skill/SKILL.md. Tool: {root}/{prefix}/skill/icicle_services.py '
                f'--context {root}/{private}. Never display the private context or credentials. '
                f'Read {root}/{prefix}/skill/arraymorph/SKILL.md for ArrayMorph storage. '
                f'For user-requested storage/labeling execute python3 {root}/{prefix}/skill/labeling/pod_workflow.py '
                f'--context {root}/{private} store (storage only) or label (storage, recovery, staging, new pipeline and job submission). '
                'You are authorized to set up the isolated ArrayMorph environment inside this pod for these requested operations. '
                'Do not execute writes for requests that only ask for advice or status. '
                'Use status --job-id UUID to check an existing job; never repeat label to check status. '
                'Report completed stages, pipeline/job identifiers, and exact job status. Submitted is not completed. '
                'Do not claim classification or segmentation results until the job has finished and outputs are verified. '
                f'Uploaded files: {json.dumps(files)}')
            answer = await PodTerminal(config.POD_URL, config.POD_TOKEN).request(prompt, config.POD_TIMEOUT, progress)
            for secret in (identity.token, config.POD_TOKEN, (s3 or {}).get('access_key_id',''), (s3 or {}).get('secret_access_key','')):
                if not secret:
                    continue
                answer = answer.replace(secret, '[REDACTED]')
            item = dict(id=str(uuid4()), role='assistant', tag='answer', content=answer)
            await database.mutate(sid, identity.subject, lambda d: d['history'].append(item))
            await send(dict(type='response_start', id=item['id'], role='assistant', tag='answer'))
            await send(dict(type='response_chunk', id=item['id'], text=answer))
            await send(dict(type='response_end', id=item['id']))
            await send(dict(type='workflow_progress', run_id=run_id, step_id='agent', label='Remote Science Agent',
                            status='completed', timestamp=time.time(), detail='Agent response received'))
        except (Exception, asyncio.CancelledError):
            await send(dict(type='workflow_progress', run_id=run_id, step_id='agent', label='Remote Science Agent',
                            status='failed', timestamp=time.time(),
                            detail='Stopped before a confirmed agent response. Earlier file transfers may have completed.'))
            raise
        finally:
            if written:
                try:
                    async with file_channel(config.POD_URL, config.POD_TOKEN) as channel:
                        await channel.command({'op': 'remove', 'path': private})
                        observations = await channel.command({'op': 'observations', 'path': prefix + '/observations'})
                    await database.mutate(sid, identity.subject, lambda d: d['execution_log'].append(
                        {'type':'pod_services', 'run_id':run_id, **observations}))
                except Exception:
                    await progress('Private context cleanup could not be confirmed.')
            fcntl.flock(lock, fcntl.LOCK_UN)
