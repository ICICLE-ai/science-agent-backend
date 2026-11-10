"""Run inside the agent pod using private request-scoped credentials."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler
from uuid import uuid4

from run_arraymorph_labeling_workflow import stage_recovered_image, submit_smart_labeler


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class Client:
    def __init__(self, context, directory):
        self.context, self.directory = context, directory

    def request(self, method, path, query=None, body=None):
        url = self.context['smart_labeler_url'].rstrip('/') + path
        if query:
            url += '?' + urlencode(query)
        token = self.context['tapis_token']
        request = Request(url, method=method, data=json.dumps(body).encode() if body is not None else None,
                          headers={'Tapis-Token': token, 'X-Tapis-Token': token, 'Content-Type':'application/json'})
        record = dict(method=method, url=url, executed=True,
                      observed_at=datetime.now(timezone.utc).isoformat())
        if body is not None:
            record['request_body'] = body
        try:
            with build_opener(NoRedirect).open(request, timeout=120) as response:
                record['http_status'] = response.status
                value = json.load(response)
                record['response'] = value
                return value
        except Exception as exc:
            record['http_status'] = getattr(exc, 'code', None)
            if isinstance(exc, HTTPError):
                record['error_body'] = exc.read(4096).decode('utf-8', errors='replace')
            raise RuntimeError(f'{method} {path} failed (HTTP {record["http_status"]}). Check recorded observations before retrying writes.') from None
        finally:
            (self.directory / 'observations').mkdir(exist_ok=True)
            serialized = json.dumps(record)
            for secret in (token, (self.context.get('s3') or {}).get('access_key_id'),
                           (self.context.get('s3') or {}).get('secret_access_key')):
                if secret:
                    serialized = serialized.replace(secret, '[REDACTED]')
            (self.directory / 'observations' / (str(uuid4())+'.json')).write_text(serialized)

    def get(self, path, query=None):
        return self.request('GET', path, query=query)

    def post(self, path, body):
        return self.request('POST', path, body=body)


def execute(context_path, operation, job_id=None, output_dir=None):
    path = Path(context_path).resolve()
    context = json.loads(path.read_text())
    directory = path.parent
    client = Client(context, directory)
    if operation in {'status', 'results'}:
        if not job_id or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in job_id):
            raise ValueError('A valid job ID is required.')
        result = {'job_id': job_id, 'response': client.get('/get_job_status/' + job_id)}
        if operation == 'results':
            if not output_dir:
                raise ValueError('Provide the output directory observed during submission; do not guess it.')
            if '..' in Path(output_dir).parts:
                raise ValueError('Invalid output directory.')
            result['output_files'] = client.get('/get_files/0/' + context['tapis_system'], {'dir':output_dir})
        return result
    report_path = directory / 'workflow-result.json'
    if report_path.exists():
        return json.loads(report_path.read_text())
    marker = directory / 'workflow-started'
    marker.touch(exist_ok=False)
    report = dict(success=False, stages=[], run_id=context['run_id'])
    os.environ['SCIENCE_AGENT_PROGRESS_FILE'] = str(directory / 'workflow-progress.jsonl')
    try:
        result = subprocess.run([sys.executable, str(Path(__file__).parent.parent / 'arraymorph/store_files.py'),
                                 '--context', str(path)], capture_output=True, text=True, timeout=600)
        if result.returncode:
            raise RuntimeError('ArrayMorph storage failed; inspect the ArrayMorph observation, do not submit a job.')
        storage = json.loads(result.stdout)
        report['arraymorph'] = storage
        report['stages'].append('ArrayMorph S3 write and fresh-process recovery verified')
        if operation == 'store':
            report['success'] = True
            return report
        if len(storage['files']) != 1:
            raise RuntimeError('This initial labeling flow requires exactly one image. Storage is complete.')
        item = storage['files'][0]
        if Path(item['name']).suffix.lower() not in {'.jpg','.jpeg','.png','.tif','.tiff','.webp'}:
            raise RuntimeError('Labeling requires an image file.')
        manifest = dict(session_id=context['session_id'], dataset_id=context['run_id'],
                        source_filename=item['name'], recovered_path=item['recovered_path'])
        staged = stage_recovered_image(manifest, context['tapis_token'], context['tapis_base_url'],
                                       context['tapis_system'], context['tapis_base_dir'])
        report['tapis_staging'] = staged
        report['stages'].append('Recovered image staged and listed by Tapis')
        report['smart_labeler'] = submit_smart_labeler(manifest, staged, context['user_request'], client,
                                                      write_marker=directory / 'submission-started')
        report['stages'].append('Smart Labeler job submitted and initial status retrieved')
        report['success'] = True
    except Exception as exc:
        report['error'] = str(exc)
    finally:
        serialized = json.dumps(report)
        for secret in [context.get('tapis_token',''), *(context.get('s3') or {}).values()]:
            if isinstance(secret,str) and len(secret)>16 and secret not in [context.get('s3',{}).get('endpoint')]:
                serialized = serialized.replace(secret,'[REDACTED]')
        report_path.write_text(serialized)
        observations = directory / 'observations'
        observations.mkdir(exist_ok=True)
        (observations / 'workflow.json').write_text(serialized)
    return json.loads(report_path.read_text())


if __name__ == '__main__':
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument('--context',required=True)
    parser.add_argument('operation', choices=['store','label','status','results'])
    parser.add_argument('--job-id')
    parser.add_argument('--output-dir')
    args = parser.parse_args()
    print(json.dumps(execute(args.context,args.operation,args.job_id,args.output_dir),indent=2))
