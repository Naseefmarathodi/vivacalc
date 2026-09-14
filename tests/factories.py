"""Small hand-rolled factories.

Deliberately not factory_boy: the object graph is three models deep, so a
dependency would cost more than it saves.
"""

from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model

from adminpanel.models import Portal, TravelBooking

User = get_user_model()

PASSWORD = "Correct-Horse-9271"


def make_admin(username="admin_user", **kwargs):
    return User.objects.create_user(
        username=username, password=PASSWORD, role=User.Role.ADMIN, **kwargs
    )


def make_staff(username="staff_user", **kwargs):
    return User.objects.create_user(
        username=username, password=PASSWORD, role=User.Role.STAFF, **kwargs
    )


def make_superuser(username="root_user", **kwargs):
    return User.objects.create_superuser(
        username=username, password=PASSWORD, **kwargs
    )


def make_portal(name="Galileo", **kwargs):
    return Portal.objects.create(name=name, **kwargs)


def make_booking(user, portal=None, buy="1000.00", sell="1250.00", **kwargs):
    kwargs.setdefault("passenger_name", "Rahul Menon")
    kwargs.setdefault("service", "Return ticket")
    kwargs.setdefault("sector", "DXB-BOM")
    return TravelBooking.objects.create(
        entered_by=user,
        portal=portal,
        buy_price=Decimal(buy),
        sell_price=Decimal(sell),
        **kwargs,
    )
