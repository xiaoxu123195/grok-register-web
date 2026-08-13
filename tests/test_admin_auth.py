import os
import tempfile
import unittest

from werkzeug.security import generate_password_hash

from core.auth import AdminGate, LoginThrottle


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class AdminGateConfigTest(unittest.TestCase):
    def test_disabled_when_nothing_is_configured(self):
        gate = AdminGate.from_environment({})

        self.assertFalse(gate.enabled)
        # A disabled gate must let the historical localhost workflow through.
        self.assertTrue(gate.is_authenticated({}))
        # ...but must never accept a password, so an empty hash cannot be
        # coaxed into authenticating anyone.
        self.assertFalse(gate.verify(''))
        self.assertFalse(gate.verify('anything'))

    def test_hash_from_environment_variable(self):
        gate = AdminGate.from_environment({
            'GROK_REGISTER_ADMIN_PASSWORD_HASH': generate_password_hash('correct horse'),
        })

        self.assertTrue(gate.enabled)
        self.assertTrue(gate.verify('correct horse'))
        self.assertFalse(gate.verify('wrong horse'))
        self.assertFalse(gate.is_authenticated({}))

    def test_plaintext_environment_variable_is_hashed_at_boot(self):
        gate = AdminGate.from_environment({
            'GROK_REGISTER_ADMIN_PASSWORD': 'plain-secret',
        })

        self.assertTrue(gate.enabled)
        self.assertTrue(gate.verify('plain-secret'))
        self.assertFalse(gate.verify('other'))

    def test_hash_file_wins_over_environment_variable(self):
        """The file path exists because Compose corrupts '$' in env values."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'admin.hash')
            with open(path, 'w', encoding='utf-8') as handle:
                # Trailing newline is what an editor or the helper script writes.
                handle.write(generate_password_hash('from-file') + '\n')

            gate = AdminGate.from_environment({
                'GROK_REGISTER_ADMIN_PASSWORD_HASH_FILE': path,
                'GROK_REGISTER_ADMIN_PASSWORD_HASH': generate_password_hash('from-env'),
            })

        self.assertTrue(gate.enabled)
        self.assertTrue(gate.verify('from-file'))
        self.assertFalse(gate.verify('from-env'))

    def test_missing_hash_file_falls_back_without_crashing(self):
        gate = AdminGate.from_environment({
            'GROK_REGISTER_ADMIN_PASSWORD_HASH_FILE': '/nonexistent/admin.hash',
        })

        self.assertFalse(gate.enabled)

    def test_corrupt_hash_never_authenticates(self):
        """A Compose-mangled hash must reject everything, not accept everything."""
        mangled = 'scrypt:32768:8:1$472f9af004a5e375'
        gate = AdminGate(mangled)

        self.assertTrue(gate.enabled)
        self.assertFalse(gate.verify(''))
        self.assertFalse(gate.verify('anything'))


class PublicPathTest(unittest.TestCase):
    def test_only_the_login_surface_is_public(self):
        gate = AdminGate(generate_password_hash('x'))

        for public in ('/login', '/api/auth/status', '/static/css/style.css'):
            self.assertTrue(gate.is_public_path(public), public)

        # The SPA bundle stays gated so a scanner cannot enumerate the API.
        for gated in (
            '/',
            '/static/js/app.js',
            '/static/js/pages/results.js',
            '/api/results/sso',
            '/api/settings',
            '/api/auth/logout',
        ):
            self.assertFalse(gate.is_public_path(gated), gated)


class LoginThrottleTest(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.throttle = LoginThrottle(
            max_failures=3, base_lockout=60, max_lockout=300,
            window=900, time_fn=self.clock,
        )

    def test_lockout_engages_only_after_the_threshold(self):
        self.assertEqual(self.throttle.retry_after('1.2.3.4'), 0)

        self.assertEqual(self.throttle.record_failure('1.2.3.4'), 0)
        self.assertEqual(self.throttle.record_failure('1.2.3.4'), 0)
        self.assertEqual(self.throttle.record_failure('1.2.3.4'), 60)

        self.assertGreater(self.throttle.retry_after('1.2.3.4'), 0)

    def test_lockout_expires_on_its_own(self):
        for _ in range(3):
            self.throttle.record_failure('1.2.3.4')
        self.clock.advance(61)

        self.assertEqual(self.throttle.retry_after('1.2.3.4'), 0)

    def test_repeated_failures_back_off_up_to_the_cap(self):
        for _ in range(3):
            self.throttle.record_failure('1.2.3.4')
        self.assertEqual(self.throttle.record_failure('1.2.3.4'), 120)
        self.assertEqual(self.throttle.record_failure('1.2.3.4'), 240)
        self.assertEqual(self.throttle.record_failure('1.2.3.4'), 300)
        self.assertEqual(self.throttle.record_failure('1.2.3.4'), 300)

    def test_clients_are_tracked_independently(self):
        for _ in range(3):
            self.throttle.record_failure('1.2.3.4')

        self.assertGreater(self.throttle.retry_after('1.2.3.4'), 0)
        self.assertEqual(self.throttle.retry_after('5.6.7.8'), 0)

    def test_success_clears_the_counter(self):
        self.throttle.record_failure('1.2.3.4')
        self.throttle.record_failure('1.2.3.4')
        self.throttle.reset('1.2.3.4')

        self.assertEqual(self.throttle.record_failure('1.2.3.4'), 0)

    def test_tracking_table_is_bounded(self):
        throttle = LoginThrottle(max_clients=8, window=1, time_fn=self.clock)
        for i in range(50):
            throttle.record_failure(f'10.0.0.{i}')
            self.clock.advance(2)

        self.assertLessEqual(len(throttle._clients), 8)


if __name__ == '__main__':
    unittest.main()
