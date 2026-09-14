from django.apps import AppConfig


class VivapanelConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "vivapanel"

    def ready(self):
        # Registers the sign-in / sign-out notification receivers.
        from . import signals  # noqa: F401

        self._watch_env_file()

    @staticmethod
    def _watch_env_file():
        """Make the dev autoreloader restart when .env changes.

        .env is read once at startup, and Django's StatReloader only watches
        .py files. Without this, editing a credential in .env appears to do
        nothing until you manually restart - which is confusing enough that it
        is worth the four lines.
        """
        from django.conf import settings

        if not settings.DEBUG:
            return

        from django.utils.autoreload import autoreload_started

        def watch(sender, **kwargs):
            # extra_files is the supported hook; StatReloader has no
            # watch_file() method.
            sender.extra_files.add(settings.BASE_DIR / ".env")

        autoreload_started.connect(watch, dispatch_uid="vivacalc_watch_dotenv")
