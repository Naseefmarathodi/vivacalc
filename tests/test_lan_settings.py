"""Guards on the LAN deployment settings.

The three TLS-dependent protections are deliberately off in this module. That
is only safe because the listener is private, so these tests exist to make the
choice explicit and to stop `prod` being pointed at the LAN by accident.
"""

import importlib

from django.test import SimpleTestCase


def _lan_settings(**env):
    """Import vivacalc.settings.lan in isolation with a given environment."""
    import os

    previous = {k: os.environ.get(k) for k in env}
    os.environ.setdefault("DJANGO_SECRET_KEY", "test-key-" + "x" * 40)
    os.environ.update({k: v for k, v in env.items() if v is not None})
    try:
        module = importlib.import_module("vivacalc.settings.lan")
        return importlib.reload(module)
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class AllowedHostsTests(SimpleTestCase):
    def test_the_whole_dhcp_pool_is_accepted(self):
        lan = _lan_settings()
        for octet in (50, 52, 117, 150):
            with self.subTest(ip=octet):
                self.assertIn(f"192.168.1.{octet}", lan.ALLOWED_HOSTS)

    def test_addresses_outside_the_pool_are_not_accepted(self):
        lan = _lan_settings()
        for octet in (49, 151, 200):
            with self.subTest(ip=octet):
                self.assertNotIn(f"192.168.1.{octet}", lan.ALLOWED_HOSTS)

    def test_the_hostname_and_short_name_are_accepted(self):
        lan = _lan_settings()
        self.assertIn("myserver.local", lan.ALLOWED_HOSTS)
        self.assertIn("myserver", lan.ALLOWED_HOSTS)

    def test_the_pool_is_configurable(self):
        lan = _lan_settings(
            DHCP_SUBNET="10.0.0", DHCP_RANGE_START="10", DHCP_RANGE_END="12"
        )
        self.assertIn("10.0.0.10", lan.ALLOWED_HOSTS)
        self.assertIn("10.0.0.12", lan.ALLOWED_HOSTS)
        self.assertNotIn("10.0.0.13", lan.ALLOWED_HOSTS)

    def test_the_hostname_is_configurable(self):
        lan = _lan_settings(LAN_HOSTNAME="vivacalc.local")
        self.assertIn("vivacalc.local", lan.ALLOWED_HOSTS)
        self.assertIn("vivacalc", lan.ALLOWED_HOSTS)

    def test_csrf_origins_cover_the_hostname_over_http(self):
        lan = _lan_settings()
        self.assertIn("http://myserver.local", lan.CSRF_TRUSTED_ORIGINS)
        self.assertIn("http://192.168.1.117", lan.CSRF_TRUSTED_ORIGINS)


class PlainHttpIsWorkableTests(SimpleTestCase):
    """Each of these being True would break LAN access — two of them silently."""

    def test_no_ssl_redirect(self):
        self.assertFalse(_lan_settings().SECURE_SSL_REDIRECT)

    def test_no_hsts(self):
        self.assertEqual(_lan_settings().SECURE_HSTS_SECONDS, 0)

    def test_cookies_are_sent_over_http(self):
        lan = _lan_settings()
        self.assertFalse(lan.SESSION_COOKIE_SECURE)
        self.assertFalse(lan.CSRF_COOKIE_SECURE)


class NonTlsProtectionsStayOnTests(SimpleTestCase):
    def test_debug_is_off(self):
        self.assertFalse(_lan_settings().DEBUG)

    def test_cookies_are_still_httponly_and_samesite(self):
        lan = _lan_settings()
        self.assertTrue(lan.SESSION_COOKIE_HTTPONLY)
        self.assertEqual(lan.SESSION_COOKIE_SAMESITE, "Lax")

    def test_clickjacking_and_sniffing_protections_stay_on(self):
        lan = _lan_settings()
        self.assertEqual(lan.X_FRAME_OPTIONS, "DENY")
        self.assertTrue(lan.SECURE_CONTENT_TYPE_NOSNIFF)

    def test_the_throttle_cache_is_shared_not_per_process(self):
        backend = _lan_settings().CACHES["default"]["BACKEND"]
        self.assertNotIn("locmem", backend)
        self.assertIn("db", backend)
