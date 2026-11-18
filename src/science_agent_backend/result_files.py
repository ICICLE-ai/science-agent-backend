"""Copy observed result JSON directly from Smart Labeler to PostgreSQL bytes."""
import hashlib
import json
from pathlib import PurePosixPath
from urllib.parse import quote

import aiohttp
from . import config, database

MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024


async def save_result_files(sid, subject, token, records, message_id):
    files, errors, seen, total = [], [], set(), 0
    async with aiohttp.ClientSession(headers={'Tapis-Token': token, 'X-Tapis-Token': token},
                                    timeout=aiohttp.ClientTimeout(total=120)) as client:
        for record in records:
            analysis = record.get('result_analysis') or {}
            if analysis.get('state') not in {'analyzed', 'partial'}:
                continue
            system, root = analysis.get('system'), analysis.get('output_directory')
            job_id = record.get('job_id')
            if not system or not root or not job_id:
                continue
            for file in analysis.get('files', [])[:20]:
                path = file.get('path', '')
                if path in seen:
                    continue
                seen.add(path)
                try:
                    if '..' in PurePosixPath(path).parts or not PurePosixPath(path).is_relative_to(PurePosixPath(root)):
                        raise ValueError('Result path is outside its recorded output directory.')
                    pipeline_id = ((record.get('smart_labeler') or {}).get('pipeline') or {}).get('id', 0)
                    url = config.SMART_LABELER_BASE_URL.rstrip('/') + '/get_file/' + quote(str(pipeline_id), safe='') + '/' + quote(system, safe='')
                    async with client.get(url, params={'filePath': path}, allow_redirects=False) as response:
                        if response.status != 200:
                            raise ValueError(f'Result download returned HTTP {response.status}.')
                        content = bytearray()
                        async for chunk in response.content.iter_chunked(64 * 1024):
                            if len(content) + len(chunk) > MAX_FILE_BYTES or total + len(chunk) > MAX_TOTAL_BYTES:
                                raise ValueError('Result download size limit exceeded.')
                            content.extend(chunk)
                            total += len(chunk)
                    json.loads(content)
                    name = 'result-' + hashlib.sha256((str(job_id) + ':' + path + ':' + message_id).encode()).hexdigest()[:24] + '.json'
                    info = await database.put_attachment(sid, subject, name, 'application/json', bytes(content),
                        output_metadata={'message_id': message_id, 'job_id': job_id, 'source_path': path})
                    files.append(info)
                except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
                    errors.append({'path': path, 'error': str(exc)})
    return files, errors
