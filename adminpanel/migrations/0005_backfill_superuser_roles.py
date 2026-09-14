"""Make the displayed role match actual access.

Before this migration a superuser could show Role = "Staff" in the user list
while in fact having full panel access. ``role`` is now the authoritative
application permission, so every existing superuser is promoted to
``role="admin"``; nobody gains or loses access, the label simply stops lying.
"""

from django.db import migrations


def promote_superusers(apps, schema_editor):
    CustomUser = apps.get_model("adminpanel", "CustomUser")
    CustomUser.objects.filter(is_superuser=True).exclude(role="admin").update(
        role="admin"
    )


def noop_reverse(apps, schema_editor):
    """Nothing to undo: demoting would remove access these users already had."""


class Migration(migrations.Migration):

    dependencies = [
        ("adminpanel", "0004_integrity_and_roles"),
    ]

    operations = [
        migrations.RunPython(promote_superusers, noop_reverse),
    ]
