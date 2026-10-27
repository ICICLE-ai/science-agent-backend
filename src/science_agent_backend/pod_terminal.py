"""ttyd transport with optional Tapis gateway authentication."""
import asyncio
import json
import re
import secrets
from time import monotonic
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
        reply_finished = False
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
                    await self.health_check(ws, stream, screen, progress)
                    await ws.send_bytes(b'0\x1b[200~' + instruction.encode() + b'\x1b[201~')
                    await asyncio.sleep(0.5)
                    submitted = True
                    await ws.send_bytes(b'0\r')
                    if progress:
                        await progress('Request sent to the remote agent; waiting for its response')
                    deadline = asyncio.get_running_loop().time() + timeout
                    candidate, candidate_since = None, 0
                    recovered = None
                    while asyncio.get_running_loop().time() < deadline:
                        await self._frame(ws, stream, 1)
                        idle = self._idle(screen)
                        if idle and self._has_end(screen, end):
                            reply_finished = True
                        answer = self._answer(screen, begin, end) or recovered
                        if idle and answer is None and self._has_end(screen, end):
                            recovered = await self._recover_answer(begin, end)
                            if recovered is None:
                                raise RuntimeError('Remote agent: the answer finished, but its full text could not be recovered. Check the agent terminal before retrying; do not repeat submitted jobs.')
                            answer = recovered
                        if not idle or answer is None:
                            candidate, candidate_since = None, 0
                            continue
                        if answer != candidate:
                            candidate, candidate_since = answer, monotonic()
                        # Status-bar redraws do not mean the answer is still running.
                        elif monotonic() - candidate_since >= 1:
                            completed = True
                            return answer.replace(self.token, '[REDACTED]') if self.token else answer
                    raise RuntimeError('Remote agent: response timed out. Check the remote terminal before retrying; a remote operation may still be running.')
                finally:
                    if submitted and not completed and not reply_finished and not ws.closed:
                        # Disconnect alone leaves the persistent tmux agent running.
                        try:
                            await ws.send_bytes(b'0\x03')
                        except (aiohttp.ClientError, ConnectionError):
                            pass

    @staticmethod
    def _shell_prompt(screen):
        line = screen.display[screen.cursor.y]
        return (not line[screen.cursor.x:].strip()
                and re.fullmatch(r'[\w./~:@ ()-]*[#$%]\s*', line[:screen.cursor.x]) is not None)

    async def health_check(self, ws, stream, screen, progress=None):
        """Repair known startup states; return only when the agent is ready."""
        from .pod_receiver import metrics_prompt_choice
        from .pod_files import file_channel

        deadline = monotonic() + 12
        actions = []
        while monotonic() < deadline:
            changed = await self._frame(ws, stream, 1)
            if metrics_prompt_choice('\n'.join(screen.display)) is not None:
                if 'declined_metrics' not in actions and not changed:
                    async with file_channel(self.url, self.token) as channel:
                        result = await channel.command({'op': 'decline-metrics'})
                    if not result.get('declined'):
                        raise RuntimeError('Remote agent: the information-sharing prompt could not be safely declined. No request was sent.')
                    actions.append('declined_metrics')
                    screen.reset()
                    deadline = monotonic() + 60
                    if progress:
                        await progress('Declined optional usage metrics sharing; waiting for the agent input prompt')
            elif self._shell_prompt(screen):
                if 'started_agent' not in actions and not changed:
                    async with file_channel(self.url, self.token) as channel:
                        result = await channel.command({'op': 'start-agent'})
                    if not result.get('started'):
                        raise RuntimeError('Remote agent: the terminal is not an empty shell; automatic startup was skipped.')
                    actions.append('started_agent')
                    screen.reset()
                    deadline = monotonic() + 60
                    if progress:
                        await progress('Agent is not running; starting a new agent session')
            elif self._idle(screen) and not changed:
                if actions and progress:
                    await progress('Agent health check passed; ready to receive the request')
                return {'status': 'ready', 'actions': actions}
        if actions:
            raise RuntimeError('Remote agent: startup recovery did not reach the agent input prompt within 60 seconds. No request was sent. Check the agent terminal.')
        raise RuntimeError('Remote agent: terminal is busy or its input prompt is unavailable.')

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
    def _lines(screen):
        history = [''.join(line[x].data if x in line else ' ' for x in range(screen.columns))
                   for line in screen.history.top]
        return [line.rstrip() for line in history + screen.display]

    @classmethod
    def _has_end(cls, screen, end):
        return any(line.strip() == end for line in cls._lines(screen))

    async def _recover_answer(self, begin, end):
        # Full-screen redraws can discard the start of long replies from pyte.
        # Read only this request's framed answer from the agent's tmux pane.
        from .pod_files import file_channel
        chunks, offset = [], 0
        async with file_channel(self.url, self.token) as channel:
            while True:
                result = await channel.command(dict(op='terminal-answer', begin=begin,
                                                     end=end, offset=offset))
                if not result.get('found'):
                    return None
                chunk = result['text']
                chunks.append(chunk)
                offset += len(chunk)
                if offset >= result['total']:
                    return '\n'.join(self._clean_lines(''.join(chunks).splitlines())).strip() or None
                if not chunk:
                    raise RuntimeError('Remote agent: answer transfer stopped before completion.')

    @staticmethod
    def _clean_lines(lines):
        return [re.sub(r'(?:~?\d+(?:\.\d+)?K|K)/\d+K\s+pinned.*$', '', value).rstrip()
                for value in lines]

    @classmethod
    def _answer(cls, screen, begin, end):
        lines = cls._lines(screen)
        start = None
        for index, line in enumerate(lines):
            if line.strip() == begin:
                start = index + 1
            elif start is not None and line.strip() == end:
                answer_lines = cls._clean_lines(lines[start:index])
                answer = '\n'.join(answer_lines).strip()
                if answer:
                    return answer
        return None
