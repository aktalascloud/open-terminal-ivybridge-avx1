"""Actual proxy routes with synthetic origins/cookies and in-memory transports."""
import asyncio
from pathlib import Path
import unittest

import httpx
from test_terminal_mainstream import main, FOLDER, TestClient, env_patch, fixture
from open_terminal.browser import router
from open_terminal.utils.fs import UserFS


class Resource(httpx.AsyncByteStream):
    def __init__(self): self.closed = False
    async def __aiter__(self):
        for _ in range(257):
            yield b'x' * 65536
    async def aclose(self): self.closed = True


class ProxyContracts(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.sessions = dict(router.sessions)
        self.profiles = dict(router.profiles)
        self.calls = []
        self.resources = []
        self.created = []
        for actor in ['actor-a', 'actor-b']:
            def respond(request, actor=actor):
                self.calls.append((actor, request))
                if request.url.path == '/set':
                    return httpx.Response(200, headers={'set-cookie': f'session={actor}; Secure; Path=/'}, content=b'fixture')
                if request.url.path == '/redirect':
                    return httpx.Response(302, headers={'location': 'https://other.invalid/next'}, content=b'')
                if request.url.path == '/oversize':
                    resource = Resource()
                    self.resources.append(resource)
                    return httpx.Response(200, headers={'content-type': 'text/html'}, stream=resource)
                return httpx.Response(200, headers={'content-type': 'text/plain'}, content=b'fixture')
            profile = httpx.AsyncClient(transport=httpx.MockTransport(respond), follow_redirects=False)
            self.created.append(profile)
            router.profiles[actor] = profile
            router.sessions[actor] = router.Session(actor, 'synthetic-cap', actor, 'chat', UserFS(home=str(FOLDER)))

    def tearDown(self):
        self.client.close()
        for client in self.created:
            asyncio.run(client.aclose())
        router.sessions.clear()
        router.sessions.update(self.sessions)
        router.profiles.clear()
        router.profiles.update(self.profiles)

    def url(self, actor='actor-a', path='get', token='synthetic-cap', scheme='https', host='site.invalid'):
        return f'/browser/view/{actor}/{token}/frame/{scheme}/{host}/{path}'

    def test_private_service_headers_never_reach_the_target(self):
        response = self.client.get(self.url(), headers={'Authorization': 'Bearer synthetic-service',
            'Cookie': 'webui=synthetic-private', 'x-user-id': 'other', 'x-session-id': 'other',
            'x-api-key': 'synthetic-key', 'x-custom-secret': 'synthetic-private', 'Accept': 'text/plain'})
        self.assertEqual(response.status_code, 200)
        actor, request = self.calls[0]
        self.assertEqual(actor, 'actor-a')
        for key in ['authorization', 'cookie', 'x-user-id', 'x-session-id', 'x-api-key', 'x-custom-secret']:
            self.assertNotIn(key, request.headers)
        self.assertEqual(request.headers['accept'], 'text/plain')

    def test_target_cookies_are_owner_scoped_and_not_exposed_to_the_embedder(self):
        response = self.client.get(self.url(path='set'))
        self.assertNotIn('set-cookie', response.headers)
        self.client.get(self.url())
        self.assertEqual(self.calls[-1][1].headers.get('cookie'), 'session=actor-a')
        self.client.get(self.url(actor='actor-b'))
        self.assertNotIn('cookie', self.calls[-1][1].headers)

    def test_invalid_capability_and_target_schemes_fail_before_any_target_request(self):
        self.assertEqual(self.client.get(self.url(token='wrong')).status_code, 404)
        self.assertEqual(self.client.get(self.url(scheme='file')).status_code, 400)
        self.assertEqual(self.client.get(self.url(host='user:password@site.invalid')).status_code, 400)
        self.assertEqual(self.calls, [])

    def test_redirects_are_rewritten_without_automatically_following(self):
        response = self.client.get(self.url(path='redirect'), follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(self.calls), 1)
        self.assertIn('/frame/https/other.invalid/next', response.headers['location'])

    def test_oversized_rewritten_resource_closes_its_stream_and_returns_a_bounded_error(self):
        response = self.client.get(self.url(path='oversize'))
        self.assertEqual(response.status_code, 413)
        self.assertLess(len(response.content), 200)
        self.assertTrue(self.resources[0].closed)


if __name__ == '__main__':
    try:
        unittest.main()
    finally:
        env_patch.stop()
        fixture.cleanup()
