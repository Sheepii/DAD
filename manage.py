#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path


def _parse_requirements(path: Path) -> list[str]:
    if not path.exists():
        return []
    requirements: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        requirements.append(line)
    return requirements


def _distribution_name(req: str) -> str:
    if "@" in req:
        return req.split("@", 1)[0].strip()
    return re.split(r"[<=>!~]", req, maxsplit=1)[0].strip()


def _is_installed(req: str) -> bool:
    try:
        import importlib.metadata as metadata
    except Exception:
        return False
    name = _distribution_name(req)
    if not name:
        return True
    try:
        installed = metadata.version(name)
    except metadata.PackageNotFoundError:
        if "-" in name:
            alt = name.replace("-", "_")
        else:
            alt = name.replace("_", "-")
        try:
            installed = metadata.version(alt)
        except metadata.PackageNotFoundError:
            return False
    if "==" in req:
        expected = req.split("==", 1)[1].strip()
        return installed == expected
    return True


def ensure_requirements() -> None:
    if os.environ.get("DAD_SKIP_PIP", "").lower() in {"1", "true", "yes"}:
        return
    requirements_path = Path(__file__).resolve().parent / "requirements.txt"
    requirements = _parse_requirements(requirements_path)
    if not requirements:
        return
    missing = [req for req in requirements if not _is_installed(req)]
    if not missing:
        return
    os.environ.setdefault("PIP_DISABLE_PIP_VERSION_CHECK", "1")
    print("Installing Python dependencies...", file=sys.stderr)
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", str(requirements_path)])


def main():
    """Run administrative tasks."""
    ensure_requirements()
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dad.settings')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
