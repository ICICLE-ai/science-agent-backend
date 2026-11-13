"""Transfer files through ttyd with optional Tapis gateway authentication."""
import asyncio
import base64
from contextlib import asynccontextmanager
import hashlib
import json
from pathlib import Path
import secrets
import shlex
import re
import codecs
from urllib.parse import urlsplit

import aiohttp


class PodFiles:
    def __init__(self, ws, marker):
        self.ws, self.marker = ws, marker
        self.buffer = ''
        self.info = None
        self.decoder = codecs.getincrementaldecoder('utf-8')('replace')
        self.request_id = 0

    def _response(self):
        prefix = self.marker + '{'
        start = self.buffer.find(prefix)
        while start >= 0:
            payload = self.buffer[start+len(self.marker):]
            try:
                data, end = json.JSONDecoder().raw_decode(payload)
            except json.JSONDecodeError:
                # A tmux repaint can truncate an ACK and then replay it in full.
                start = self.buffer.find(prefix, start + len(prefix))
                continue
            self.buffer = payload[end:]
            return data
        return None

    async def receive(self):
        while True:
            data = self._response()
            if data is not None:
                return data
            message = await self.ws.receive()
            if message.type in {aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR}:
                raise RuntimeError('Remote agent: file transfer terminal disconnected.')
            if message.type == aiohttp.WSMsgType.BINARY and message.data[:1] == b'0':
                self.buffer += self.decoder.decode(message.data[1:])
                self.buffer = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', self.buffer)
                self.buffer = self.buffer[-262144:]

    async def command(self, value):
        self.request_id += 1
        request = {**value, 'request_id': self.request_id}
        await self.ws.send_bytes(b'0' + json.dumps(request, separators=(',', ':')).encode() + b'\n')
        try:
            async with asyncio.timeout(30):
                while True:
                    response = await self.receive()
                    # Check the ID before interpreting a replayed ACK or error.
                    if response.pop('request_id', None) == self.request_id:
                        if 'error' in response:
                            raise RuntimeError('Remote agent: file transfer failed (' + response['error'] + ').')
                        return response
        except TimeoutError:
            raise RuntimeError('Remote agent: file transfer acknowledgement timed out.') from None

    async def put(self, path, data):
        checksum = hashlib.sha256(data).hexdigest()
        await self.command({'op': 'put', 'path': path, 'size': len(data), 'sha256': checksum})
        for offset in range(0, len(data), 32768):
            await self.command({'op': 'chunk', 'data': base64.b64encode(data[offset:offset+32768]).decode()})
        result = await self.command({'op': 'finish'})
        if result.get('sha256') != checksum or result.get('size') != len(data):
            raise RuntimeError('Remote agent: uploaded file checksum does not match.')
        return result


@asynccontextmanager
async def file_channel(url, token=''):
    from .pod_terminal import PodTerminal
    PodTerminal(url, token)  # Validate the configured origin before sending credentials.
    origin = urlsplit(url)
    origin_url = f'{origin.scheme}://{origin.netloc}'
    marker = 'SAFILE_' + secrets.token_hex(12)
    source = Path(__file__).with_name('pod_receiver.py').read_bytes()
    bootstrap = ('import base64;exec(base64.b64decode(' + repr(base64.b64encode(source).decode())
                 + '));serve(' + repr(marker) + ')')
    shell = 'python3 -u -c ' + shlex.quote(bootstrap)
    command = 'new-window -n ' + marker + ' ' + shlex.quote(shell)
    async with aiohttp.ClientSession(headers={'X-Tapis-Token': token} if token else {},
                                     timeout=aiohttp.ClientTimeout(total=30)) as client:
        async with client.get(url.rstrip('/')+'/token', allow_redirects=False) as response:
            if response.status != 200:
                raise RuntimeError(f'Remote agent: file authentication returned HTTP {response.status}.')
            auth = await response.json()
        async with client.ws_connect(url.rstrip('/')+'/ws', protocols=['tty'], origin=origin_url) as ws:
            await ws.send_str(json.dumps({'AuthToken': auth.get('token', ''), 'columns': 160, 'rows': 50}))
            await asyncio.sleep(1)
            await ws.send_bytes(b'0\x02')
            await asyncio.sleep(.2)
            await ws.send_bytes(b'0:')
            await asyncio.sleep(.2)
            await ws.send_bytes(b'0' + command.encode())
            await asyncio.sleep(.5)
            await ws.send_bytes(b'0\r')
            channel = PodFiles(ws, marker)
            try:
                try:
                    async with asyncio.timeout(30):
                        channel.info = await channel.receive()
                except TimeoutError:
                    raise RuntimeError('Remote agent: file transfer channel did not become ready.') from None
                if not channel.info.get('ready'):
                    raise RuntimeError('Remote agent: file transfer receiver did not confirm readiness.')
                yield channel
            finally:
                if not ws.closed:
                    try:
                        # Target this window explicitly even if the receiver failed;
                        # never send a JSON command into the restored agent prompt.
                        await ws.send_bytes(b'0\x02')
                        await asyncio.sleep(.2)
                        await ws.send_bytes(b'0:')
                        await asyncio.sleep(.2)
                        await ws.send_bytes(b'0' + ('kill-window -t ' + marker).encode())
                        await asyncio.sleep(.3)
                        await ws.send_bytes(b'0\r')
                        await asyncio.sleep(.3)
                    except (Exception, asyncio.CancelledError):
                        pass
