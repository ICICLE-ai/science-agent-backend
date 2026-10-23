"""Short-lived terminal file receiver, executed inside a dedicated tmux window."""
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import termios
import tty
import subprocess
import signal
import re


def terminal_answer(begin, end):
    if (not re.fullmatch(r'SA_BEGIN_[a-f0-9]{24}', begin)
            or end != 'SA_END_' + begin[len('SA_BEGIN_'):]):
        raise ValueError('Invalid answer markers')
    result = subprocess.run(['tmux', 'capture-pane', '-p', '-J', '-S', '-10000', '-t', ':0.0'],
                            capture_output=True, text=True, timeout=5, check=True)
    lines = result.stdout.splitlines()
    start, answer = None, None
    for index, line in enumerate(lines):
        if line.strip() == begin:
            start = index + 1
        elif start is not None and line.strip() == end:
            answer = '\n'.join(lines[start:index]).strip()
            start = None
    if answer is not None and len(answer) > 1024 * 1024:
        raise ValueError('Agent answer exceeds transfer limit')
    return answer


def serve(marker):
    root = Path.home() / '.science-agent'
    root.mkdir(mode=0o700, exist_ok=True)
    os.umask(0o077)
    attrs = termios.tcgetattr(sys.stdin.fileno())
    tty.setraw(sys.stdin.fileno())
    pending = None
    handle = None
    request_id = 0
    captured_answer, captured_markers = None, None
    signal.signal(signal.SIGHUP, lambda *_: sys.exit(0))
    def reply(data):
        data['request_id'] = request_id
        sys.stdout.write(marker + json.dumps(data, separators=(',', ':')) + '\r\n')
        sys.stdout.flush()
    def target(value):
        relative = Path(value)
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('Invalid destination')
        path = (root / relative).resolve()
        if not path.is_relative_to(root.resolve()):
            raise ValueError('Destination escapes workspace')
        return path
    try:
        reply({'ready': True, 'root': str(root), 'python': sys.version.split()[0],
               'curl': bool(shutil.which('curl')), 'hermes': bool(shutil.which('hermes'))})
        while True:
            line = sys.stdin.buffer.readline(131072)
            if not line:
                break
            try:
                request = json.loads(line)
                request_id = request['request_id']
                op = request['op']
                if op == 'put':
                    if handle:
                        raise ValueError('Previous transfer unfinished')
                    path = target(request['path'])
                    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    pending = path.with_name(path.name + '.part-' + marker[-8:])
                    handle = pending.open('wb')
                    expected = request['sha256']
                    size = request['size']
                    total = 0
                    digest = hashlib.sha256()
                    reply({'accepted': True})
                elif op == 'chunk':
                    if handle is None:
                        raise ValueError('No transfer')
                    data = base64.b64decode(request['data'], validate=True)
                    total += len(data)
                    if total > size:
                        raise ValueError('Transfer exceeds declared size')
                    handle.write(data)
                    digest.update(data)
                    reply({'received': total})
                elif op == 'finish':
                    if handle is None:
                        raise ValueError('No transfer')
                    handle.close()
                    handle = None
                    if total != size or digest.hexdigest() != expected:
                        raise ValueError('Size or checksum mismatch')
                    os.replace(pending, path)
                    pending = None
                    reply({'path': str(path), 'size': total, 'sha256': digest.hexdigest()})
                elif op == 'remove':
                    target(request['path']).unlink(missing_ok=True)
                    reply({'removed': True})
                elif op == 'terminal-answer':
                    if request.get('offset', 0) == 0:
                        captured_answer = terminal_answer(request['begin'], request['end'])
                        captured_markers = (request['begin'], request['end'])
                    elif (request['begin'], request['end']) != captured_markers:
                        raise ValueError('Answer markers changed during transfer')
                    offset = request.get('offset', 0)
                    if not isinstance(offset, int) or offset < 0:
                        raise ValueError('Invalid answer offset')
                    reply({'found': captured_answer is not None,
                           'text': (captured_answer or '')[offset:offset + 16384],
                           'total': len(captured_answer or '')})
                elif op == 'check':
                    tool = target(request['tool'])
                    context = target(request['context'])
                    operation = request['operation']
                    if operation not in ('inspect-files', 'get', 'arraymorph-health'):
                        raise ValueError('Invalid check')
                    args = [sys.executable, str(tool), '--context', str(context), operation]
                    if operation == 'get':
                        args.append(request['endpoint'])
                    result = subprocess.run(args, capture_output=True, timeout=35)
                    reply({'check': json.loads(result.stdout), 'exit_code': result.returncode})
                elif op == 'observations':
                    directory = target(request['path'])
                    records = []
                    for record in sorted(directory.glob('*.json'))[:100]:
                        data = json.loads(record.read_text())
                        records.append({k: data[k] for k in
                            ('method', 'url', 'http_status', 'observed_at', 'executed', 'error', 'success', 'files', 'stages',
                             'response', 'request_body', 'error_body', 'smart_labeler', 'tapis_staging', 'arraymorph', 'run_id') if k in data})
                    reply({'observations': records})
                elif op in ('start-arraymorph-probe', 'arraymorph-probe-status'):
                    relative = Path(request['path'])
                    if relative.parent != Path('checks/arraymorph') or not relative.name.startswith('probe-'):
                        raise ValueError('Invalid ArrayMorph probe directory')
                    directory = target(request['path'])
                    if op == 'start-arraymorph-probe':
                        if (directory / 'started').exists():
                            raise ValueError('Probe already started')
                        (directory / 'started').touch(mode=0o600)
                        with (directory / 'runner.log').open('w') as log:
                            process = subprocess.Popen([sys.executable, str(directory / 'install_probe.py')],
                                stdout=log, stderr=log, stdin=subprocess.DEVNULL, start_new_session=True,
                                cwd=directory)
                        reply({'started': True, 'pid': process.pid})
                    else:
                        report = directory / 'result.json'
                        reply({'result': json.loads(report.read_text()) if report.exists() else {'status': 'starting'}})
                elif op in ('start-arraymorph-upload', 'arraymorph-upload-status'):
                    parts = Path(request['path']).parts
                    from uuid import UUID
                    if len(parts) != 4 or parts[0] != 'sessions' or parts[2] != 'runs':
                        raise ValueError('Invalid request directory')
                    UUID(parts[1])
                    UUID(parts[3])
                    directory = target(request['path'])
                    output = directory / 'arraymorph-tool-result.json'
                    if op == 'start-arraymorph-upload':
                        marker_path = directory / 'arraymorph-started'
                        if marker_path.exists():
                            raise ValueError('Upload already started')
                        marker_path.touch(mode=0o600)
                        with output.open('w') as out, (directory / 'arraymorph-stderr.log').open('w') as err:
                            process = subprocess.Popen([sys.executable,
                                str(directory / 'arraymorph-skill/store_files.py'), '--context', str(directory / 'context.json')],
                                stdout=out, stderr=err, stdin=subprocess.DEVNULL, start_new_session=True, cwd=directory)
                        reply({'started': True, 'pid': process.pid})
                    else:
                        try:
                            result = json.loads(output.read_text())
                        except (OSError, ValueError):
                            result = {'status': 'running'}
                        reply({'result': result})
                elif op == 'clean-transfer-checks':
                    removed = 0
                    for fixture in (root / 'checks').glob('*/five-mib-transfer.bin*'):
                        if fixture.is_file():
                            fixture.unlink()
                            removed += 1
                    reply({'removed_fixtures': removed})
                elif op == 'exit':
                    reply({'closed': True})
                    break
                else:
                    raise ValueError('Unknown operation')
            except Exception as exc:
                reply({'error': type(exc).__name__})
                break
    finally:
        if handle:
            handle.close()
        if pending:
            pending.unlink(missing_ok=True)
        try:
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSANOW, attrs)
        except termios.error:
            pass
