"""Optional admin password gate for the Web console.

Disabled by default, so the historical localhost workflow is unchanged: with
no password configured every request passes straight through. Set
``GROK_REGISTER_ADMIN_PASSWORD_HASH`` (preferred) or
``GROK_REGISTER_ADMIN_PASSWORD`` to require a login.

The gate is deliberately coarse — one shared operator password, no user
accounts — because the console has exactly one operator and anything richer
would be security theatre on top of a single-tenant tool.
"""

from __future__ import annotations

import logging
import threading
import time

from werkzeug.security import check_password_hash, generate_password_hash

logger = logging.getLogger(__name__)

SESSION_KEY = 'admin_authenticated'

ENV_HASH_FILE = 'GROK_REGISTER_ADMIN_PASSWORD_HASH_FILE'
ENV_HASH = 'GROK_REGISTER_ADMIN_PASSWORD_HASH'
ENV_PLAINTEXT = 'GROK_REGISTER_ADMIN_PASSWORD'

# Reachable without a session, kept as small as possible: the login form and
# the stylesheet it needs. The SPA bundle stays behind the gate so a scanner
# cannot even enumerate the API surface.
PUBLIC_PATHS = frozenset({
    '/login',
    '/api/auth/status',
    '/static/css/style.css',
})

MAX_FAILURES = 5
BASE_LOCKOUT_SEC = 60
MAX_LOCKOUT_SEC = 900
FAILURE_WINDOW_SEC = 900
MAX_TRACKED_CLIENTS = 1024


class LoginThrottle:
    """Per-client failure counter with exponential lockout.

    Keyed on ``request.remote_addr``. Behind a reverse proxy every request
    shares the proxy's address, which makes the lockout global rather than
    per-client — that fails closed, so it is left as-is instead of trusting a
    spoofable ``X-Forwarded-For``.
    """

    def __init__(self, *, max_failures=MAX_FAILURES, base_lockout=BASE_LOCKOUT_SEC,
                 max_lockout=MAX_LOCKOUT_SEC, window=FAILURE_WINDOW_SEC,
                 max_clients=MAX_TRACKED_CLIENTS, time_fn=time.monotonic):
        self._max_failures = max_failures
        self._base_lockout = base_lockout
        self._max_lockout = max_lockout
        self._window = window
        self._max_clients = max_clients
        self._time = time_fn
        self._lock = threading.Lock()
        self._clients = {}

    def _prune(self, now):
        """Drop entries that are neither locked nor inside the failure window."""
        stale = [
            key for key, entry in self._clients.items()
            if entry['locked_until'] <= now and entry['last_failure'] + self._window <= now
        ]
        for key in stale:
            del self._clients[key]
        # Hard cap so a spray across forged addresses cannot grow this forever.
        if len(self._clients) > self._max_clients:
            oldest = sorted(self._clients.items(), key=lambda kv: kv[1]['last_failure'])
            for key, _ in oldest[:len(self._clients) - self._max_clients]:
                del self._clients[key]

    def retry_after(self, client):
        """Seconds the client must wait, or 0 when an attempt is allowed."""
        now = self._time()
        with self._lock:
            entry = self._clients.get(client)
            if not entry:
                return 0
            remaining = entry['locked_until'] - now
            return max(0, remaining)

    def record_failure(self, client):
        """Count a failed attempt and return the resulting lockout seconds."""
        now = self._time()
        with self._lock:
            self._prune(now)
            entry = self._clients.get(client)
            if not entry or entry['last_failure'] + self._window <= now:
                entry = {'failures': 0, 'locked_until': 0, 'last_failure': now}
                self._clients[client] = entry

            entry['failures'] += 1
            entry['last_failure'] = now
            if entry['failures'] < self._max_failures:
                return 0

            # 5th failure locks for base, then doubles per extra failure.
            overshoot = entry['failures'] - self._max_failures
            lockout = min(self._base_lockout * (2 ** overshoot), self._max_lockout)
            entry['locked_until'] = now + lockout
            return lockout

    def reset(self, client):
        with self._lock:
            self._clients.pop(client, None)


class AdminGate:
    """Holds the configured password hash and answers authorization questions."""

    def __init__(self, password_hash='', throttle=None):
        self._hash = str(password_hash or '').strip()
        self.throttle = throttle if throttle is not None else LoginThrottle()

    @classmethod
    def from_environment(cls, env, throttle=None):
        # Preferred: a file. Werkzeug hashes contain '$', which Docker Compose
        # silently eats as variable interpolation — a hash pasted into .env
        # loses its salt segment and every login then fails with "wrong
        # password". Reading a file bypasses interpolation entirely.
        hash_file = str(env.get(ENV_HASH_FILE, '') or '').strip()
        if hash_file:
            try:
                with open(hash_file, 'r', encoding='utf-8') as handle:
                    from_file = handle.read().strip()
            except OSError as exc:
                logger.error('Cannot read %s=%s: %s', ENV_HASH_FILE, hash_file, exc)
                from_file = ''
            if from_file:
                return cls(from_file, throttle=throttle)
            logger.error(
                '%s points at %s but no hash was read; the console stays OPEN',
                ENV_HASH_FILE, hash_file,
            )

        configured = str(env.get(ENV_HASH, '') or '').strip()
        if configured:
            if '$' in configured and configured.count('$') < 2:
                logger.warning(
                    '%s looks truncated (a werkzeug hash has two "$" separators). '
                    'Docker Compose eats "$" during interpolation — use %s instead.',
                    ENV_HASH, ENV_HASH_FILE,
                )
            return cls(configured, throttle=throttle)

        plaintext = str(env.get(ENV_PLAINTEXT, '') or '').strip()
        if plaintext:
            logger.warning(
                '%s holds a plaintext password; prefer %s so the secret never '
                'sits in the process environment (scripts/hash_password.py)',
                ENV_PLAINTEXT, ENV_HASH,
            )
            return cls(generate_password_hash(plaintext), throttle=throttle)

        return cls('', throttle=throttle)

    @property
    def enabled(self):
        return bool(self._hash)

    def verify(self, candidate):
        """Constant-time password check. Always False when the gate is off."""
        if not self.enabled:
            return False
        try:
            return check_password_hash(self._hash, str(candidate or ''))
        except (ValueError, TypeError):
            # A malformed hash must not authenticate anyone.
            logger.error('Configured admin password hash is not usable')
            return False

    def is_authenticated(self, session):
        if not self.enabled:
            return True
        return bool(session.get(SESSION_KEY))

    def is_public_path(self, path):
        return str(path or '') in PUBLIC_PATHS

    @staticmethod
    def mark_authenticated(session):
        session.clear()
        session[SESSION_KEY] = True
        session.permanent = True

    @staticmethod
    def sign_out(session):
        session.clear()
