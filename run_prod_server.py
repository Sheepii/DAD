#!/usr/bin/env python
"""Start a production-ready WSGI server so IIS/ARR can terminate TLS."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import manage


def main() -> None:
    manage.ensure_requirements()
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dad.settings")

    try:
        from waitress import serve
    except ImportError as exc:
        raise RuntimeError(
            "waitress is required for the production server. "
            "Install dependencies via `pip install -r requirements.txt`."
        ) from exc

    from dad.wsgi import application

    host = os.environ.get("PROD_HOST", "127.0.0.1")
    port = int(os.environ.get("PROD_PORT", "8000"))
    print(f"Starting Waitress on {host}:{port} for IIS/ARR reverse proxy")
    serve(application, host=host, port=port)


if __name__ == "__main__":
    main()
