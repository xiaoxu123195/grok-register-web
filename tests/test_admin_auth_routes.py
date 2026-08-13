"""End-to-end checks of the admin gate against the real Flask app.

``app`` reads the gate configuration from the environment at import time, so
each scenario runs in a child interpreter with its own environment — the same
pattern tests/test_static_mime_types.py uses.
"""

import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

PASSWORD = 'operator-secret-123'


def run_scenario(script, env_overrides=None):
    env = {**os.environ, 'PYTHONUTF8': '1'}
    # Never let a developer's own gate configuration leak into the child.
    for key in (
        'GROK_REGISTER_ADMIN_PASSWORD',
        'GROK_REGISTER_ADMIN_PASSWORD_HASH',
        'GROK_REGISTER_ADMIN_PASSWORD_HASH_FILE',
    ):
        env.pop(key, None)
    env.update(env_overrides or {})

    return subprocess.run(
        [sys.executable, '-c', textwrap.dedent(script)],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


class AdminGateRouteTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.hash_path = os.path.join(self._tmp.name, 'admin.hash')

        from werkzeug.security import generate_password_hash
        with open(self.hash_path, 'w', encoding='utf-8') as handle:
            handle.write(generate_password_hash(PASSWORD) + '\n')

        self.gated_env = {'GROK_REGISTER_ADMIN_PASSWORD_HASH_FILE': self.hash_path}

    def assert_scenario(self, script, env_overrides=None):
        result = run_scenario(script, env_overrides)
        self.assertEqual(
            result.returncode, 0,
            msg=f'child process failed:\n{result.stdout}\n{result.stderr}',
        )

    def test_unauthenticated_requests_are_blocked(self):
        self.assert_scenario(
            """
            import app

            with app.app.test_client() as client:
                assert app.admin_gate.enabled, 'gate should be enabled'

                page = client.get('/')
                assert page.status_code == 302, page.status_code
                assert page.headers['Location'].endswith('/login')

                # The SPA bundle must not be readable before login.
                bundle = client.get('/static/js/app.js')
                assert bundle.status_code == 302, bundle.status_code

                for path in ('/api/results/sso', '/api/results/accounts',
                             '/api/settings', '/api/register/status'):
                    res = client.get(path)
                    assert res.status_code == 401, (path, res.status_code)
                    assert res.get_json()['code'] == 'UNAUTHORIZED', path

                # Login form and its stylesheet stay reachable.
                assert client.get('/login').status_code == 200
                assert client.get('/static/css/style.css').status_code == 200
            """,
            self.gated_env,
        )

    def test_correct_password_unlocks_the_console(self):
        self.assert_scenario(
            f"""
            import app

            with app.app.test_client() as client:
                res = client.post('/login', data={{'password': {PASSWORD!r}}})
                assert res.status_code == 302, res.status_code
                assert res.headers['Location'].endswith('/')

                assert client.get('/').status_code == 200
                assert client.get('/static/js/app.js').status_code == 200

                status = client.get('/api/auth/status').get_json()['data']
                assert status == {{'enabled': True, 'authenticated': True}}, status

                # Logging out closes the door again.
                assert client.post('/api/auth/logout').status_code == 200
                assert client.get('/').status_code == 302
            """,
            self.gated_env,
        )

    def test_wrong_password_is_rejected_and_then_locked_out(self):
        self.assert_scenario(
            """
            import app

            with app.app.test_client() as client:
                for _ in range(5):
                    res = client.post('/login', data={'password': 'nope'})
                    assert res.status_code == 401, res.status_code
                    assert client.get('/').status_code == 302

                # Sixth attempt is refused outright, even with the real password.
                res = client.post('/login', data={'password': 'operator-secret-123'})
                assert res.status_code == 429, res.status_code
                assert client.get('/').status_code == 302
            """,
            self.gated_env,
        )

    def test_websocket_connect_is_refused_without_a_session(self):
        """The connect handler replays log lines carrying registration emails."""
        self.assert_scenario(
            f"""
            import app

            flask_client = app.app.test_client()
            anon = app.socketio.test_client(app.app, flask_test_client=flask_client)
            assert not anon.is_connected(), 'anonymous socket must be refused'

            res = flask_client.post('/login', data={{'password': {PASSWORD!r}}})
            assert res.status_code == 302, res.status_code

            authed = app.socketio.test_client(app.app, flask_test_client=flask_client)
            assert authed.is_connected(), 'authenticated socket must be accepted'
            """,
            self.gated_env,
        )

    def test_disabled_gate_keeps_the_console_open(self):
        """Default configuration must behave exactly as before."""
        self.assert_scenario(
            """
            import app

            assert not app.admin_gate.enabled

            with app.app.test_client() as client:
                assert client.get('/').status_code == 200
                assert client.get('/static/js/app.js').status_code == 200
                # /login is pointless without a gate, so it bounces home.
                assert client.get('/login').status_code == 302

                status = client.get('/api/auth/status').get_json()['data']
                assert status == {'enabled': False, 'authenticated': True}, status

            socket = app.socketio.test_client(app.app)
            assert socket.is_connected(), 'socket must stay open when the gate is off'
            """,
        )


if __name__ == '__main__':
    unittest.main()
