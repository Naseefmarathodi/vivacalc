"""Waitress entry point for the LAN deployment.

Run directly, or point a Windows Service (NSSM / sc.exe) at this file.

    set DJANGO_SETTINGS_MODULE=vivacalc.settings.lan
    python serve_waitress.py

Binding to 0.0.0.0 makes the app reachable on whatever address DHCP currently
holds, which is what lets the fixed hostname keep working when the lease moves.
It listens on every interface of this machine only — it does not expose
anything to the internet. That boundary is enforced by the router (the LAN is
behind NAT with no port forward) and by the Windows Firewall rule, which is
scoped to the local subnet.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

# LAN settings by default; override in the service definition if needed.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "vivacalc.settings.lan")


def main() -> int:
    try:
        from waitress import serve
    except ImportError:
        sys.stderr.write(
            "waitress is not installed. Run:  pip install waitress\n"
        )
        return 1

    from django.core.wsgi import get_wsgi_application

    application = get_wsgi_application()

    host = os.environ.get("WAITRESS_HOST", "0.0.0.0")
    port = int(os.environ.get("WAITRESS_PORT", "8000"))
    threads = int(os.environ.get("WAITRESS_THREADS", "8"))

    from django.conf import settings

    sys.stdout.write(
        f"VivaCalc starting on http://{host}:{port}  "
        f"(hostname: http://{settings.LAN_HOSTNAME}"
        f"{'' if port == 80 else ':' + str(port)})\n"
    )
    sys.stdout.flush()

    serve(application, host=host, port=port, threads=threads,
          ident="VivaCalc", channel_timeout=120)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
