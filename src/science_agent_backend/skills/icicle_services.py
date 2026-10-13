"""Read-only ICICLE operations using credentials scoped to a web request."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import time
import struct
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from uuid import uuid4


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def execute(context_path, operation, endpoint=None):
    context = json.loads(Path(context_path).read_text())
    if operation == 'inspect-files':
        files = []
        for info in context['files']:
            path = Path(info['path'])
            digest = hashlib.sha256()
            with path.open('rb') as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b''):
                    digest.update(chunk)
            item = {**info, 'observed_size': path.stat().st_size,
                    'observed_sha256': digest.hexdigest()}
            item['verified'] = item['size'] == item['observed_size'] and item['sha256'] == item['observed_sha256']
            with path.open('rb') as handle:
                header = handle.read(24)
            if header.startswith(b'\x89PNG\r\n\x1a\n') and len(header) == 24:
                width, height = struct.unpack('!II', header[16:24])
                item['image'] = {'format': 'PNG', 'width': width, 'height': height}
            try:
                from PIL import Image
                with Image.open(path) as image:
                    item['image'] = {'format': image.format, 'width': image.width, 'height': image.height}
            except (ImportError, OSError):
                pass
            files.append(item)
        return {'files': files}
    if operation == 'arraymorph-health':
        base = context.get('arraymorph_url', '')
        if not base:
            return {'error': 'Remote ArrayMorph adapter is not configured.', 'executed': False}
        url, headers = base.rstrip('/') + '/health', {}
    else:
        if not re.fullmatch(r'/(pipes|patra/list|pipe/[0-9]+|get_job_status/[A-Za-z0-9_-]+)', endpoint or ''):
            raise ValueError('This remote adapter only permits documented read-only operations.')
        base = context.get('smart_labeler_url', '')
        if urlsplit(base).scheme != 'https':
            raise ValueError('An HTTPS Smart Labeler URL is required.')
        token = context.get('tapis_token', '')
        if not token:
            return {'error': 'A user Tapis token is required for Smart Labeler.', 'executed': False}
        url, headers = base.rstrip('/') + endpoint, {'Tapis-Token': token, 'X-Tapis-Token': token}
    observation = {'method': 'GET', 'url': url, 'observed_at': int(time.time()), 'executed': True}
    try:
        with build_opener(NoRedirect).open(Request(url, headers=headers), timeout=25) as response:
            raw = response.read(4 * 1024 * 1024 + 1)
            if len(raw) > 4 * 1024 * 1024:
                raise ValueError('Service response exceeded 4 MiB.')
            observation['http_status'] = response.status
            try:
                observation['response'] = json.loads(raw)
            except ValueError:
                observation['error'] = 'Service returned a non-JSON response.'
    except HTTPError as exc:
        observation.update(http_status=exc.code, error='Service rejected this request.')
    except URLError:
        observation['error'] = 'Service could not be reached from this pod.'
    token = context.get('tapis_token', '')
    serialized = json.dumps(observation)
    if token:
        serialized = serialized.replace(token, '[REDACTED]')
    observation = json.loads(serialized)
    directory = Path(context_path).parent / 'observations'
    directory.mkdir(mode=0o700, exist_ok=True)
    record = directory / (uuid4().hex + '.json')
    record.write_text(serialized)
    record.chmod(0o600)
    observation['observation_path'] = str(record)
    return observation


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--context', required=True)
    parser.add_argument('operation', choices=['inspect-files', 'get', 'arraymorph-health'])
    parser.add_argument('endpoint', nargs='?')
    args = parser.parse_args()
    try:
        print(json.dumps(execute(args.context, args.operation, args.endpoint)))
    except Exception as exc:
        print(json.dumps({'error': type(exc).__name__, 'executed': False}))
        raise SystemExit(1)
