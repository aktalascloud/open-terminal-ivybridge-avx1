"""Isolated Terminal0.16 contracts; no browser, screen, audio or input is opened."""
import ast
import asyncio
import io
import json
import os
from pathlib import Path
import struct
import inspect
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
work = ROOT / '.avx1-work'
work.mkdir(exist_ok=True)
assert work.resolve().is_relative_to(ROOT.resolve())
fixture = tempfile.TemporaryDirectory(prefix='mainstream-contract-', dir=work)
FOLDER = Path(fixture.name)
assert FOLDER.resolve().is_relative_to(work.resolve())
environment = {k: v for k, v in os.environ.items() if not k.upper().startswith('OPEN_TERMINAL_')}
environment.update(OPEN_TERMINAL_API_KEY='synthetic-mainstream', OPEN_TERMINAL_LOG_DIR=str(FOLDER / 'logs'),
                   XDG_CONFIG_HOME=str(FOLDER), XDG_STATE_HOME=str(FOLDER))
env_patch = patch.dict(os.environ, environment, clear=True)
env_patch.start()
from open_terminal import config
config._SYSTEM_CONFIG_PATH = FOLDER / 'no-system-config.toml'
config.init()
from open_terminal import main, desktop
from open_terminal.browser import router as browser
from open_terminal.browser import chrome
from open_terminal.frames import Frames
from open_terminal.utils import port
from open_terminal.utils.log import LogReader
from open_terminal.dependencies import matches_api_key
import httpx
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from PIL import Image
from starlette.websockets import WebSocketDisconnect

AUTH = {'Authorization': 'Bearer synthetic-mainstream', 'x-user-id': 'actor', 'x-session-id': 'chat'}


class HttpAndSocket(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)

    def tearDown(self):
        self.client.close()

    def test_private_browser_creation_requires_key(self):
        before = set(browser.sessions)
        response = self.client.post('/browser/sessions', json={'url': 'https://public.example'})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(set(browser.sessions), before)

    def test_browser_session_is_bound_to_actor_and_chat_without_starting_chrome(self):
        with patch('open_terminal.browser.chrome.Chrome.create', new_callable=AsyncMock) as launch:
            with TestClient(main.app) as client:
                response = client.post('/browser/sessions', json={'url': 'https://public.example'}, headers=AUTH)
                self.assertEqual(response.status_code, 200, response.text)
                row = response.json()
                for overrides in ({'x-user-id': 'other'}, {'x-session-id': 'other'}):
                    self.assertEqual(client.get('/browser/sessions/' + row['id'], headers={**AUTH, **overrides}).status_code, 404)
                self.assertEqual(client.get(f"/browser/view/{row['id']}/wrong/runtime.js").status_code, 404)
                self.assertEqual(client.patch('/browser/sessions/' + row['id'], headers=AUTH, json={'chat_id': 'other'}).status_code, 409)
                self.assertEqual(client.delete('/browser/sessions/' + row['id'], headers=AUTH).status_code, 200)
                launch.assert_not_awaited()

    def test_browser_rejects_non_http_and_credential_urls(self):
        with TestClient(main.app) as client:
            for value in ('javascript:alert(1)', 'file:///private', 'https://name:password@public.example/'):
                with self.subTest(url=value):
                    self.assertEqual(client.post('/browser/sessions', json={'url': value}, headers=AUTH).status_code, 400)

    def test_desktop_unauthorized_or_invalid_action_never_captures(self):
        capture = AsyncMock()
        with patch.object(desktop, 'get_desktop', capture):
            self.assertEqual(self.client.get('/desktop/screenshot').status_code, 401)
            for payload in ({'actions': []}, {'actions': [{'action': 'click', 'x': -1, 'y': 0}]},
                            {'actions': [{'action': 'key', 'key': 'a;shutdown'}]}):
                self.assertEqual(self.client.post('/desktop/action', json=payload, headers=AUTH).status_code, 422)
            capture.assert_not_awaited()

    def test_authenticated_desktop_uses_only_injected_synthetic_screen(self):
        image = io.BytesIO()
        Image.new('RGB', (2, 2), 'white').save(image, 'PNG')
        fake = NS(actions=asyncio.Lock(), screenshot=AsyncMock(return_value=image.getvalue()))
        with patch.object(desktop, 'get_desktop', AsyncMock(return_value=fake)):
            response = self.client.get('/desktop/screenshot', headers=AUTH)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, image.getvalue())

    def test_events_websocket_auth_and_subscription_dispatch(self):
        calls = []
        async def events(ws, fs, cwd, ports):
            calls.append(ws.headers.get('x-user-id'))
            await ws.send_json({'type': 'fixture'})
            await ws.close()
        with patch.object(main, 'system_events', events):
            with self.client.websocket_connect('/events', headers=AUTH) as ws:
                ws.send_json({'type': 'auth', 'token': 'wrong'})
                with self.assertRaises(WebSocketDisconnect) as error:
                    ws.receive_json()
                self.assertEqual(error.exception.code, 4001)
            self.assertEqual(calls, [])
            with self.client.websocket_connect('/events', headers=AUTH) as ws:
                ws.send_json({'type': 'auth', 'token': 'synthetic-mainstream'})
                self.assertEqual(ws.receive_json(), {'type': 'fixture'})
            self.assertEqual(calls, ['actor'])

    def test_desktop_batch_stops_without_replaying_uncertain_action(self):
        calls = []
        def perform(body):
            calls.append(body.text)
            if len(calls) == 2:
                raise OSError('synthetic uncertain operation')
        fake = NS(actions=asyncio.Lock(), transport='frames', width=10, height=10,
                  perform=perform, screenshot=AsyncMock())
        with patch.object(desktop, 'get_desktop', AsyncMock(return_value=fake)):
            response = self.client.post('/desktop/action', headers=AUTH,
                json={'actions': [{'action': 'type', 'text': text} for text in ('one', 'two', 'three')]})
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()['detail']['completed_actions'], 1)
        self.assertEqual(response.json()['detail']['failed_action_index'], 1)
        self.assertEqual(calls, ['one', 'two'])
        fake.screenshot.assert_not_awaited()

    def test_process_websocket_keeps_actor_and_chat_ownership(self):
        path = FOLDER / 'process.jsonl'
        path.write_text(json.dumps({'type': 'stdout', 'data': 'synthetic output'}) + '\n', encoding='utf-8')
        process = main.BackgroundProcess('fixture', 'synthetic', NS(), status='done', finished_at=10**12,
                                         log_path=str(path), user_id='actor', session_id='chat')
        with patch.dict(main._processes, {'fixture': process}, clear=True):
            for overrides in ({'x-user-id': 'other'}, {'x-session-id': 'other'}):
                with self.client.websocket_connect('/execute/fixture/status', headers={**AUTH, **overrides}) as ws:
                    ws.send_json({'type': 'auth', 'token': 'synthetic-mainstream'})
                    with self.assertRaises(WebSocketDisconnect) as error: ws.receive_json()
                    self.assertEqual(error.exception.code, 4004)
            with self.client.websocket_connect('/execute/fixture/status', headers=AUTH) as ws:
                ws.send_json({'type': 'auth', 'token': 'synthetic-mainstream'})
                output = ws.receive_json()
                self.assertEqual(output['output'], [{'type': 'stdout', 'data': 'synthetic output'}])
                self.assertEqual(output['next_offset'], 1)


class LogsAndPorts(unittest.IsolatedAsyncioTestCase):
    async def test_browser_proxy_never_forwards_terminal_identity_or_api_key(self):
        captured = []
        def transport(request):
            captured.append(request)
            return httpx.Response(200, text='synthetic remote body')
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            session = browser.Session('session', 'synthetic-capability', 'actor', 'chat', NS())
            scope = {'type': 'http', 'method': 'GET', 'scheme': 'http', 'path': '/browser/view/session/token/frame/https/public.example/page',
                     'query_string': b'', 'server': ('127.0.0.1', 1), 'headers': [
                         (b'authorization', b'Bearer synthetic-terminal-key'), (b'cookie', b'token=synthetic-owner'),
                         (b'x-user-id', b'actor'), (b'x-private', b'synthetic-private')], 'path_params': {}}
            from fastapi import Request
            with patch.dict(browser.sessions, {'session': session}, clear=True), patch.dict(browser.profiles, {'actor': client}, clear=True):
                response = await browser.frame(Request(scope), 'session', 'synthetic-capability', 'https', 'public.example', 'page')
                body = b''.join([chunk async for chunk in response.body_iterator])
            self.assertEqual(body, b'synthetic remote body')
            self.assertEqual(len(captured), 1)
            for header in ('authorization', 'cookie', 'x-user-id', 'x-private'):
                self.assertNotIn(header, captured[0].headers)

    async def test_log_reader_waits_for_complete_unicode_record_and_keeps_cursor(self):
        path = FOLDER / 'partial.jsonl'
        encoded = (json.dumps({'type': 'stdout', 'data': 'строка'}, ensure_ascii=False) + '\n').encode()
        path.write_bytes(encoded[:-3])
        reader = LogReader(str(path))
        self.assertEqual(await reader.read(), ([], 0, False))
        with path.open('ab') as output: output.write(encoded[-3:])
        self.assertEqual(await reader.read(), ([{'type': 'stdout', 'data': 'строка'}], 1, False))
        self.assertEqual(await reader.read(), ([], 1, False))

    async def test_log_reader_detects_rotation_and_absolute_offset(self):
        path = FOLDER / 'rotation.jsonl'
        path.write_text(json.dumps({'type': 'stdout', 'data': 'first'}) + '\n', encoding='utf-8')
        reader = LogReader(str(path))
        await reader.read()
        replacement = FOLDER / 'replacement.jsonl'
        replacement.write_text(json.dumps({'type': 'log_rotated', 'offset': 100}) + '\n' + json.dumps({'type': 'stdout', 'data': 'new'}) + '\n', encoding='utf-8')
        replacement.replace(path)
        self.assertEqual(await reader.read(), ([{'type': 'stdout', 'data': 'new'}], 101, True))

    async def test_completed_failed_scanner_restarts_for_new_viewer(self):
        old = asyncio.Queue()
        done = asyncio.create_task(asyncio.sleep(0))
        await done
        previous = (port._subscribers, port._scanner, port._snapshot)
        port._subscribers, port._scanner, port._snapshot = {old}, done, []
        scanner = None
        viewer = port.watch_listening_ports()
        try:
            with patch.object(port, 'run_io', AsyncMock(return_value=[{'port': 8123}])) as scan:
                self.assertEqual(await anext(viewer), [])
                self.assertEqual(await asyncio.wait_for(anext(viewer), 1), [{'port': 8123}])
                scan.assert_awaited_once()
                scanner = port._scanner
        finally:
            await viewer.aclose()
            if scanner and not scanner.done():
                scanner.cancel()
                await asyncio.gather(scanner, return_exceptions=True)
            port._subscribers, port._scanner, port._snapshot = previous


class BinaryAndMcp(unittest.IsolatedAsyncioTestCase):
    async def test_windows_debug_channel_is_loopback_without_proxy_or_server_credentials(self):
        self.assertIn('proxy', inspect.signature(chrome.websockets.connect).parameters)
        profile = FOLDER / 'synthetic-browser-profile'
        process = NS(returncode=None, kill=Mock(), wait=AsyncMock())
        async def spawn(*args, **kwargs):
            (profile / 'DevToolsActivePort').write_text('8123\n/devtools/browser/synthetic\n', encoding='utf-8')
            return process
        connect = AsyncMock(return_value=object())
        with patch.object(chrome.asyncio, 'create_subprocess_exec', side_effect=spawn) as create, \
             patch.object(chrome.websockets, 'connect', connect), \
             patch.object(chrome, 'Host', side_effect=lambda proc, **kw: NS(process=proc, **kw)):
            host = await chrome.windows_host(['synthetic-chrome', f'--user-data-dir={profile}'], str(profile), str(FOLDER))
        self.assertIs(host.process, process)
        self.assertIsNone(connect.call_args.kwargs['proxy'])
        self.assertEqual(connect.call_args.args[0], 'ws://127.0.0.1:8123/devtools/browser/synthetic')
        self.assertIn('--remote-debugging-address=127.0.0.1', create.call_args.args)
        self.assertNotIn('OPEN_TERMINAL_API_KEY', create.call_args.kwargs['env'])
        process.kill.assert_not_called()

    def test_frames_reuse_original_jpeg_and_send_bounded_pixel_delta(self):
        image = Image.new('RGB', (4, 3), 'white')
        frames = Frames()
        first = frames.encode(image)
        self.assertEqual(struct.unpack('!6H', first[:12]), (4, 3, 0, 0, 4, 3))
        self.assertIsNone(frames.encode(image))
        image.putpixel((1, 1), (0, 0, 0))
        delta = frames.encode(image)
        self.assertEqual(struct.unpack('!6H', delta[:12]), (4, 3, 1, 1, 1, 1))
        output = io.BytesIO()
        image.save(output, 'JPEG')
        self.assertEqual(Frames().jpeg(output.getvalue())[12:], output.getvalue())

    async def test_mcp_verifier_reuses_validated_constant_time_key_matcher(self):
        tree = ast.parse((ROOT / 'open_terminal/mcp_server.py').read_text('utf-8'))
        node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'ApiKeyVerifier')
        scope = {'TokenVerifier': object, 'AccessToken': NS, 'matches_api_key': matches_api_key}
        exec(compile(ast.Module(body=[node], type_ignores=[]), 'mcp-verifier', 'exec'), scope)
        verifier = scope['ApiKeyVerifier']()
        for token in ('wrong', 'неверно', '\ud800', None):
            self.assertIsNone(await verifier.verify_token(token))
        self.assertEqual((await verifier.verify_token('synthetic-mainstream')).client_id, 'open-terminal')


if __name__ == '__main__':
    try:
        unittest.main()
    finally:
        env_patch.stop()
        fixture.cleanup()
