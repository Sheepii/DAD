import os
import sys

import manage


def main() -> None:
    manage.ensure_requirements()
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dad.settings")
    from django.core.management import execute_from_command_line

    args = ["manage.py", "runserver"]
    if len(sys.argv) == 1:
        args.append("0.0.0.0:8000")
    else:
        args.extend(sys.argv[1:])
    execute_from_command_line(args)


if __name__ == "__main__":
    main()
