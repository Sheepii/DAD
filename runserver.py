import os
import sys

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

import manage


def main() -> None:
    os.chdir(PROJECT_ROOT)
    manage.ensure_requirements()
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dad.settings")
    from django.core.management import execute_from_command_line

    args = ["manage.py", "runserver"]
    if len(sys.argv) == 1:
        args.append("0.0.0.0:8080")
    else:
        args.extend(sys.argv[1:])
    execute_from_command_line(args)


if __name__ == "__main__":
    main()
