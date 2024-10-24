#!/usr/bin/env python
import os
import sys

if __name__ == '__main__':
    # if you're a developer working on archivebox, still prefer the archivebox
    # versions of ./manage.py commands whenever possible. When that's not possible
    # (e.g. makemigrations), you can comment out this check temporarily

    allowed_commands = ['makemigrations', 'migrate', 'startapp','squashmigrations', 'generate_stubs', 'test']

    if not any(cmd in sys.argv for cmd in allowed_commands):
        print("[X] Don't run ./manage.py directly (unless you are a developer running makemigrations):")
        print()
        print('    Hint: Use these archivebox CLI commands instead of the ./manage.py equivalents:')
        print('        archivebox init          (migrates the databse to latest version)')
        print('        archivebox server        (runs the Django web server)')
        print('        archivebox shell         (opens an iPython Django shell with all models imported)')
        print('        archivebox manage [cmd]  (any other management commands)')
        raise SystemExit(2)

    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)
