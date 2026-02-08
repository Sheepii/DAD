#!/usr/bin/env python
"""Start a production-ready WSGI server so IIS/ARR can terminate TLS."""

from __future__ import annotations

import os
import subprocess
import sys

import manage


def _get_waitress_serve():
    try:
        from waitress import serve
    except ImportError:
        # Fallback for environments where requirements are stale on disk.
        subprocess.check_call([sys.executable, "-m", "pip", "install", "waitress==2.1.0"])
        from waitress import serve
    return serve


def main() -> None:
    manage.ensure_requirements()
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dad.settings")
    serve = _get_waitress_serve()

    from dad.wsgi import application

    host = os.environ.get("PROD_HOST", "127.0.0.1")
    port = int(os.environ.get("PROD_PORT", "8000"))
    print(f"Starting Waitress on {host}:{port} for IIS/ARR reverse proxy")
    serve(application, host=host, port=port)


if __name__ == "__main__":
    main()
