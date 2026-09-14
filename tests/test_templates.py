"""Template hygiene checks.

These exist because the failure mode is silent: Django's ``{# #}`` comment is
single-line only, so a multi-line one is not a comment at all — it renders as
visible text on the page. That shipped twice during development.
"""

import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

TEMPLATE_DIR = Path(settings.BASE_DIR) / "templates"


class TemplateCommentTests(SimpleTestCase):
    def test_no_multiline_hash_comments(self):
        offenders = []
        for path in sorted(TEMPLATE_DIR.rglob("*.html")):
            text = path.read_text(encoding="utf-8")
            for match in re.finditer(r"\{#", text):
                close = text.find("#}", match.start())
                newline = text.find("\n", match.start())
                if close == -1 or (newline != -1 and newline < close):
                    line = text[: match.start()].count("\n") + 1
                    offenders.append(
                        f"{path.relative_to(TEMPLATE_DIR)}:{line} — use "
                        f"{{% comment %}} for multi-line notes"
                    )
        self.assertEqual(offenders, [], "\n".join(offenders))

    def test_every_template_extends_or_is_a_full_document(self):
        """Catches a page template that silently renders without the shell."""
        skip = {"components", "errors"}
        for path in sorted(TEMPLATE_DIR.rglob("*.html")):
            if path.parent.name in skip or path.name.startswith("_"):
                continue
            text = path.read_text(encoding="utf-8")
            with self.subTest(template=str(path.relative_to(TEMPLATE_DIR))):
                self.assertTrue(
                    "{% extends" in text or "<!DOCTYPE html>" in text,
                    f"{path.name} is neither a full document nor an extension",
                )


class StaticAssetTests(SimpleTestCase):
    def test_no_template_references_a_deleted_stylesheet(self):
        """The old flat static/style.css and script.js are gone."""
        for path in sorted(TEMPLATE_DIR.rglob("*.html")):
            text = path.read_text(encoding="utf-8")
            with self.subTest(template=path.name):
                self.assertNotIn("'style.css'", text)
                self.assertNotIn("'script.js'", text)

    def test_the_logo_is_referenced_by_its_original_path(self):
        base = (TEMPLATE_DIR / "components" / "_sidebar.html").read_text()
        self.assertIn("{% static 'logo.png' %}", base)
