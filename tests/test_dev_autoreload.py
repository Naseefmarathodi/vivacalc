"""Guard for the .env autoreload hook.

This exists because the first version called a method that does not exist on
StatReloader. `manage.py test` never starts the autoreloader, so the broken
receiver was only discovered when runserver crashed on boot — these tests
invoke the receiver directly so that cannot happen again.
"""

from django.apps import apps
from django.conf import settings
from django.test import SimpleTestCase, override_settings
from django.utils.autoreload import StatReloader


class EnvFileWatchTests(SimpleTestCase):
    def test_the_reloader_exposes_the_api_we_use(self):
        reloader = StatReloader()
        self.assertTrue(hasattr(reloader, "extra_files"))
        self.assertFalse(hasattr(reloader, "watch_file"))

    @override_settings(DEBUG=True)
    def test_the_receiver_registers_the_env_file_without_raising(self):
        from django.utils.autoreload import autoreload_started

        apps.get_app_config("vivapanel")._watch_env_file()

        reloader = StatReloader()
        autoreload_started.send(sender=reloader)

        self.assertIn(settings.BASE_DIR / ".env", reloader.extra_files)

    @override_settings(DEBUG=False)
    def test_nothing_is_registered_outside_debug(self):
        config = apps.get_app_config("vivapanel")
        # Must be a no-op rather than an error when DEBUG is off.
        self.assertIsNone(config._watch_env_file())
