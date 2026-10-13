"""ttyd transport with optional Tapis gateway authentication."""
import asyncio
import json
import re
import secrets
from urllib.parse import urlsplit

import aiohttp
import pyte


class PodTerminal:
    def __init__(self, url, token=''):
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('Use an HTTPS pod URL without credentials or query parameters.')
        self.url = url.rstrip('/')
        self.token = token or ''

    async def request(self, prompt, timeout=180, progress=None):
        """Submit one request; completion requires a framed reply and an idle prompt."""
        marker = secrets.token_hex(12)
        begin, end = 'SA_BEGIN_' + marker, 'SA_END_' + marker
        instruction = (
            'For the web client, wrap only your final answer between two standalone lines. '
            f'The opening line is {json.dumps(begin)} and the closing line is {json.dumps(end)}. '
            'Do not put these lines in reasoning or tool output.\n' + prompt
        )
        # Bracketed paste preserves multiline content without executing pasted
        # control characters as terminal shortcuts.
        instruction = ''.join(c for c in instruction if c in '\n\t' or (ord(c) >= 32 and ord(c) != 127))
        screen = pyte.HistoryScreen(160, 50, history=5000)
        stream = pyte.ByteStream(screen)
        submitted = False
        completed = False
        async with aiohttp.ClientSession(
            headers={'X-Tapis-Token': self.token} if self.token else {},
            timeout=aiohttp.ClientTimeout(total=20),
        ) as client:
            async with client.get(self.url + '/token', allow_redirects=False) as response:
                if response.status != 200:
                    raise RuntimeError(f'Remote agent: authentication endpoint returned HTTP {response.status}.')
                auth = await response.json()
            origin = urlsplit(self.url)
            async with client.ws_connect(self.url + '/ws', protocols=['tty'],
                    origin=f'{origin.scheme}://{origin.netloc}', heartbeat=20) as ws:
                await ws.send_str(json.dumps({'AuthToken': auth.get('token', ''),
                                              'columns': 160, 'rows': 50}))
                # File transfers use temporary tmux windows; return to the agent.
                await asyncio.sleep(1)
                await ws.send_bytes(b'0\x020')
                try:
                    # Allow the initial tmux screen to finish replaying.
                    ready_deadline = asyncio.get_running_loop().time() + 12
                    while asyncio.get_running_loop().time() < ready_deadline:
                        if await self._frame(ws, stream, 1) is False and self._idle(screen):
                            break
                    else:
                        raise RuntimeError('Remote agent: terminal is busy or its input prompt is unavailable.')
                    await ws.send_bytes(b'0\x1b[200~' + instruction.encode() + b'\x1b[201~')
                    await asyncio.sleep(0.5)
                    submitted = True
                    await ws.send_bytes(b'0\r')
                    if progress:
                        await progress('Request sent to the remote agent; waiting for its response')
                    deadline = asyncio.get_running_loop().time() + timeout
                    while asyncio.get_running_loop().time() < deadline:
                        changed = await self._frame(ws, stream, 1)
                        answer = self._answer(screen, begin, end)
                        if answer is not None and not changed and self._idle(screen):
                            completed = True
                            return answer.replace(self.token, '[REDACTED]') if self.token else answer
                    raise RuntimeError('Remote agent: response timed out. Check the remote terminal before retrying; a remote operation may still be running.')
                finally:
                    if submitted and not completed and not ws.closed:
                        # Disconnect alone leaves the persistent tmux agent running.
                        try:
                            await ws.send_bytes(b'0\x03')
                        except (aiohttp.ClientError, ConnectionError):
                            pass

    @staticmethod
    async def _frame(ws, stream, timeout):
        try:
            message = await asyncio.wait_for(ws.receive(), timeout)
        except TimeoutError:
            return False
        if message.type in {aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.ERROR}:
            raise RuntimeError('Remote agent: terminal disconnected before the response completed.')
        if message.type == aiohttp.WSMsgType.BINARY and message.data[:1] == b'0':
            stream.feed(message.data[1:])
            return True
        return False

    @staticmethod
    def _idle(screen):
        lines = screen.display
        return (any(line.lstrip().startswith('\u276f') for line in lines)
                and any('\u2624' in line for line in lines)
                and not any('msg=interrupt' in line for line in lines))

    @staticmethod
    def _answer(screen, begin, end):
        history = [''.join(line[x].data if x in line else ' ' for x in range(screen.columns))
                   for line in screen.history.top]
        lines = [line.rstrip() for line in history + screen.display]
        start = None
        for index, line in enumerate(lines):
            if line.strip() == begin:
                start = index + 1
            elif start is not None and (line.strip() == end or line.lstrip().startswith('╰─')):
                answer_lines = [re.sub(
                    r'(?:~?\d+(?:\.\d+)?K|K)/\d+K\s+pinned.*$', '', value
                ).rstrip() for value in lines[start:index]]
                answer = '\n'.join(answer_lines).strip()
                if answer:
                    return answer
        return None
