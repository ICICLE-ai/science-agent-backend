"""Store request uploads through ArrayMorph using private per-account settings."""
import argparse
import fcntl
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import venv
from uuid import UUID, uuid4
from datetime import datetime, timezone


def worker(context, index, operation):
    s3 = context['s3']
    if operation == 'cloud':
        import boto3
        from botocore.config import Config
        client = boto3.client('s3', endpoint_url=s3['endpoint'], region_name=s3['region'],
            aws_access_key_id=s3['access_key_id'], aws_secret_access_key=s3['secret_access_key'],
            config=Config(signature_version='s3v4', connect_timeout=10, read_timeout=20,
                retries={'max_attempts': 1}, s3={'addressing_style': 'path', 'payload_signing_enabled': True}))
        listed = client.list_objects_v2(Bucket=s3['bucket'], Prefix=object_key(context, index) + '/')
        objects = listed.get('Contents', [])
        if not objects:
            raise RuntimeError('No ArrayMorph cloud objects observed')
        for item in objects:
            response = client.get_object(Bucket=s3['bucket'], Key=item['Key'])
            data = response['Body'].read()
            response['Body'].close()
            if len(data) != item['Size']:
                raise RuntimeError('Cloud object size mismatch')
        print(json.dumps({'http_status': listed['ResponseMetadata']['HTTPStatusCode'], 'object_count': len(objects)}), flush=True)
        return
    import arraymorph
    import numpy as np
    from arraymorph_hdf5 import NativeHDF5
    if importlib.metadata.version('arraymorph') != '0.2.0b4':
        raise RuntimeError('Unsupported connector version')
    arraymorph.configure_s3(bucket=s3['bucket'], endpoint=s3['endpoint'], region=s3['region'],
        access_key=s3['access_key_id'], secret_key=s3['secret_access_key'],
        use_tls=True, addressing_style=False, use_signed_payloads=True)
    arraymorph.enable()
    item = context['files'][index]
    source = Path(item['path'])
    key = object_key(context, index)
    native = NativeHDF5()
    if operation == 'write':
        native.write_uint8(key, 'original', np.frombuffer(source.read_bytes(), dtype=np.uint8))
        evidence = {'written': True}
    else:
        data = native.read_uint8(key, 'original', (item['size'],)).tobytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest != item['sha256']:
            raise RuntimeError('Recovered original differs from upload')
        recovered = Path(context['_directory']) / 'arraymorph-recovered'
        recovered.mkdir(mode=0o700, exist_ok=True)
        path = recovered / source.name
        path.write_bytes(data)
        evidence = {'verified': True, 'sha256': digest, 'recovered_path': str(path)}
    print(json.dumps(evidence), flush=True)
    os._exit(0)


def object_key(context, index):
    return (f"science-agent/users/{context['storage_namespace']}/{context['session_id']}/"
            f"{context['run_id']}/{index}.h5")


def ensure_environment():
    root = Path.home() / '.science-agent/envs'
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    environment = root / 'arraymorph'
    python = environment / 'bin/python'
    with (root / 'arraymorph-install.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        marker = environment / '.science-agent-version'
        if not marker.exists():
            venv.EnvBuilder(with_pip=True).create(environment)
            with (root / 'arraymorph-install.log').open('w') as log:
                result = subprocess.run([str(python), '-m', 'pip', 'install', '--only-binary=:all:',
                    'arraymorph==0.2.0b4', 'numpy==2.3.1', 'boto3==1.39.3', 'h5py==3.16.0'],
                    stdout=log, stderr=log, timeout=150)
            if result.returncode:
                raise RuntimeError('ArrayMorph environment setup failed')
            marker.write_text('0.2.0b4')
    return python


def main():
    os.umask(0o077)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    parser = argparse.ArgumentParser()
    parser.add_argument('--context', required=True)
    parser.add_argument('--worker', choices=('write', 'read', 'cloud'))
    parser.add_argument('--index', type=int, default=0)
    args = parser.parse_args()
    path = Path(args.context).resolve()
    context = json.loads(path.read_text())
    context['_directory'] = str(path.parent)
    if args.worker:
        worker(context, args.index, args.worker)
        return
    report = {'method': 'ARRAYMORPH', 'executed': False, 'stages': [], 'files': [],
              'observed_at': datetime.now(timezone.utc).isoformat(),
              'compatibility': '0.2.0b4 bundled HDF5 with isolated native workers'}
    try:
        s3 = context.get('s3')
        if not s3:
            raise RuntimeError('Configure your account S3 credentials and bucket in Settings first')
        for key in ('access_key_id', 'secret_access_key', 'endpoint', 'bucket', 'region'):
            if not s3.get(key):
                raise RuntimeError('Incomplete account S3 settings')
        report['url'] = s3['endpoint'] + '/' + s3['bucket']
        context['session_id'] = str(UUID(context['session_id']))
        context['run_id'] = str(UUID(context['run_id']))
        namespace = context.get('storage_namespace', '')
        if len(namespace) != 64 or any(c not in '0123456789abcdef' for c in namespace):
            raise RuntimeError('Invalid account storage namespace')
        files = context.get('files', [])
        if not files:
            raise RuntimeError('No uploaded files available in this request')
        for item in files:
            source = Path(item['path']).resolve()
            if source.parent != (path.parent / 'uploads').resolve():
                raise RuntimeError('Upload is outside this request')
            if source.stat().st_size != item['size'] or not 0 < item['size'] <= 64 * 1024 * 1024:
                raise RuntimeError('Invalid upload size')
            if hashlib.sha256(source.read_bytes()).hexdigest() != item['sha256']:
                raise RuntimeError('Uploaded file checksum differs')
        if not Path('/etc/pki/tls/certs/ca-bundle.crt').is_file():
            raise RuntimeError('Native S3 CA bundle missing; follow the ArrayMorph installation skill')
        python = ensure_environment()
        report['stages'].append('ArrayMorph environment ready')
        env = os.environ.copy()
        home = path.parent / 'arraymorph-home'
        home.mkdir(mode=0o700, exist_ok=True)
        env['HOME'] = str(home)
        for key in ('HDF5_PLUGIN_PATH', 'HDF5_VOL_CONNECTOR'):
            env.pop(key, None)
        # Run boto3 in the same isolated environment, not the agent interpreter.
        for index, item in enumerate(files):
            key = object_key(context, index)
            recovered = {}
            for operation in ('write', 'read', 'cloud'):
                child = subprocess.run([str(python), __file__, '--context', str(path),
                    '--worker', operation, '--index', str(index)], capture_output=True, text=True, timeout=90, env=env)
                if child.returncode:
                    raise RuntimeError('ArrayMorph ' + operation + ' failed; native worker exit ' + str(child.returncode))
                lines = [line for line in child.stdout.splitlines() if line.startswith('{')]
                evidence = json.loads(lines[-1])
                if operation == 'read':
                    recovered = evidence
                if operation == 'cloud':
                    report['http_status'] = evidence['http_status']
                report['stages'].append(item['name'] + ': ' + operation + ' completed')
            report['files'].append({'name': item['name'], 'bucket': s3['bucket'], 'key': key,
                                    'bytes': item['size'], **recovered, **evidence})
        report.update(executed=True, success=True)
    except Exception as exc:
        message = str(exc)
        for secret in (context.get('s3') or {}).values():
            if isinstance(secret, str) and secret and secret not in ('tacc',):
                message = message.replace(secret, '[REDACTED]')
        report.update(success=False, error=message)
    observations = path.parent / 'observations'
    observations.mkdir(mode=0o700, exist_ok=True)
    (observations / ('arraymorph-' + str(uuid4()) + '.json')).write_text(json.dumps(report))
    print(json.dumps(report, indent=2))
    return 0 if report.get('success') else 1


if __name__ == '__main__':
    raise SystemExit(main())
