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


class DatabaseUrlTests(SimpleTestCase):
    """DATABASE_URL must select the right backend and decode credentials."""

    @staticmethod
    def _db(url):
        """Reload base.py with DATABASE_URL set to *url*.

        An empty string means "not configured": env() treats it as unset, and
        because the key is present, read_dotenv()'s setdefault() will not
        repopulate it from the developer's own .env. Without that the test
        would depend on whatever DATABASE_URL the machine happens to have.
        """
        import importlib
        import os

        previous = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = url
        os.environ.setdefault("DJANGO_SECRET_KEY", "k" * 50)
        try:
            base = importlib.import_module("vivacalc.settings.base")
            return importlib.reload(base).DATABASES["default"]
        finally:
            if previous is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = previous
            importlib.reload(importlib.import_module("vivacalc.settings.base"))

    def test_mysql_scheme_selects_the_mysql_backend(self):
        db = self._db("mysql://u:p@localhost:3306/vivacalc")
        self.assertEqual(db["ENGINE"], "django.db.backends.mysql")
        self.assertEqual(db["NAME"], "vivacalc")
        self.assertEqual(db["PORT"], "3306")

    def test_mariadb_scheme_also_uses_the_mysql_backend(self):
        self.assertEqual(
            self._db("mariadb://u:p@h:3306/d")["ENGINE"],
            "django.db.backends.mysql",
        )

    def test_postgres_scheme_selects_postgresql(self):
        self.assertEqual(
            self._db("postgres://u:p@h:5432/d")["ENGINE"],
            "django.db.backends.postgresql",
        )

    def test_mysql_gets_utf8mb4_and_strict_mode(self):
        """Neither is MySQL's default; both matter for a money ledger."""
        options = self._db("mysql://u:p@h:3306/d")["OPTIONS"]
        self.assertEqual(options["charset"], "utf8mb4")
        self.assertIn("STRICT_TRANS_TABLES", options["init_command"])

    def test_postgres_gets_no_mysql_options(self):
        self.assertEqual(self._db("postgres://u:p@h:5432/d")["OPTIONS"], {})

    def test_a_percent_encoded_password_is_decoded(self):
        db = self._db("mysql://viva:p%40ss%21word@h:3306/d")
        self.assertEqual(db["PASSWORD"], "p@ss!word")

    def test_an_unsupported_scheme_fails_loudly(self):
        from vivacalc.settings.env import ImproperlyConfigured

        with self.assertRaises(ImproperlyConfigured):
            self._db("oracle://u:p@h/d")

    def test_no_database_url_falls_back_to_sqlite(self):
        self.assertEqual(self._db("")["ENGINE"], "django.db.backends.sqlite3")
