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
from .pod_terminal import PodTerminal, PodTerminalDisconnected
from .pod_files import file_channel


async def transfer_attachments(channel, prefix, sid, subject, uploaded_files, progress):
    files, total = [], 0
    for info in uploaded_files:
        name = info['name']
        if Path(name).name != name or name in {'.', '..'} or '\\' in name or '\x00' in name:
            raise RuntimeError('Invalid upload filename.')
        try:
            attachment = await database.get_attachment(sid, subject, name)
        except FileNotFoundError:
            raise RuntimeError(f'Attachment "{name}" is missing. Attach the file again before retrying.') from None
        total += attachment['size']
        if total > config.UPLOAD_LIMIT:
            raise RuntimeError('Uploaded files exceed the remote transfer limit.')
        result = await channel.put(prefix + '/uploads/' + name, attachment['content'])
        files.append({'name': name, **result})
        await progress(f'Transferred and verified {name}')
    return files


def verified_storage_reply(observations, run_id, files):
    if not files:
        return None
    expected = sorted((f['name'], f['size'], f['sha256']) for f in files)
    for report in observations:
        if (report.get('run_id') != run_id or report.get('success') is not True
                or 'tapis_staging' in report or 'smart_labeler' in report):
            continue
        storage = report.get('arraymorph') or {}
        if storage.get('success') is not True or storage.get('http_status') != 200:
            continue
        recovered = sorted((f.get('name', ''), f.get('bytes', 0), f.get('sha256', ''))
                           for f in storage.get('files', []) if f.get('verified') is True)
        if recovered == expected:
            return ('ArrayMorph uploaded the attached files to S3 and verified that the recovered '
                    'files match the originals. The agent terminal disconnected after storage; '
                    'no retry is needed.')
    return None


async def run(sid, identity, message, send):
    if not config.POD_URL:
        raise RuntimeError('Agent service URL is not configured.')
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

        async def finish_pod_run():
            nonlocal written
            async with file_channel(config.POD_URL, identity.token) as channel:
                await channel.command({'op': 'remove', 'path': private})
                records = await channel.command({'op': 'observations', 'path': prefix + '/observations'})
            await database.mutate(sid, identity.subject, lambda d: d['execution_log'].append(
                {'type':'pod_services', 'run_id':run_id, **records}))
            written = False
            return records['observations']

        try:
            state = await database.get(sid, identity.subject)
            from .s3_credentials import load_profile
            s3 = await load_profile(identity.subject, include_secrets=True)
            await progress('Connecting and transferring service instructions')
            async with file_channel(config.POD_URL, identity.token) as channel:
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
                    tapis_base_dir=f'/users/{identity.username}/demo',
                    previous_workflows=[observation for entry in state['execution_log']
                        if entry.get('type') == 'pod_services' for observation in entry.get('observations', [])
                        if 'stages' in observation and 'run_id' in observation][-10:])).encode())
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
                'Choose the operation from the current request, not earlier conversation turns. '
                'For a request to just upload to S3 with ArrayMorph, execute store and stop after storage verification. '
                'Do not call Smart Labeler, stage in Tapis, or submit jobs for storage-only requests. '
                'Wait for the workflow result before reporting success or failure. '
                'You are authorized to set up the isolated ArrayMorph environment inside this pod for these requested operations. '
                'Do not execute writes for requests that only ask for advice or status. '
                'Use status --job-id UUID to check an existing job; never repeat label to check status. '
                'If no job ID is supplied, status uses the latest job recorded for this conversation. '
                'When a job is complete, status automatically reads its result JSON and returns result_analysis. '
                'Explain the per-file counts, labels, score statistics and limitations from result_analysis, '
                'not just that the job finished. Missing or unreadable output is not zero detections. '
                'Report completed stages, pipeline/job identifiers, and exact job status. Submitted is not completed. '
                'Do not claim classification or segmentation results until the job has finished and outputs are verified. '
                f'Uploaded files: {json.dumps(files)}')
            completion_detail = 'Agent response received'
            try:
                answer = await PodTerminal(config.POD_URL, identity.token).request(prompt, config.POD_TIMEOUT, progress)
            except PodTerminalDisconnected:
                try:
                    records = await finish_pod_run()
                except Exception:
                    records = []
                answer = verified_storage_reply(records, run_id, files)
                if answer is None:
                    raise
                completion_detail = 'S3 upload verified from the workflow record'
            for secret in (identity.token, (s3 or {}).get('access_key_id',''), (s3 or {}).get('secret_access_key','')):
                if not secret:
                    continue
                answer = answer.replace(secret, '[REDACTED]')
            item = dict(id=str(uuid4()), role='assistant', tag='answer', content=answer)
            records = await finish_pod_run() if written else []
            if any(record.get('result_analysis', {}).get('files') for record in records):
                from .result_files import save_result_files
                downloads, download_errors = await save_result_files(sid, identity.subject, identity.token, records, item['id'])
                if download_errors:
                    item['content'] += '\n\nSome result JSON downloads could not be saved. The analysis above does not confirm their availability for download.'
                if downloads:
                    current = await database.get(sid, identity.subject)
                    await send(dict(type='output_files', files=current['output_files']))
            await database.mutate(sid, identity.subject, lambda d: d['history'].append(item))
            await send(dict(type='response_start', id=item['id'], role='assistant', tag='answer'))
            await send(dict(type='response_chunk', id=item['id'], text=item['content']))
            await send(dict(type='response_end', id=item['id']))
            await send(dict(type='workflow_progress', run_id=run_id, step_id='agent', label='Remote Science Agent',
                            status='completed', timestamp=time.time(), detail=completion_detail))
        except (Exception, asyncio.CancelledError):
            await send(dict(type='workflow_progress', run_id=run_id, step_id='agent', label='Remote Science Agent',
                            status='failed', timestamp=time.time(),
                            detail='Stopped before a confirmed agent response. Earlier file transfers may have completed.'))
            raise
        finally:
            if written:
                try:
                    await finish_pod_run()
                except Exception:
                    await progress('Private context cleanup could not be confirmed.')
            fcntl.flock(lock, fcntl.LOCK_UN)
