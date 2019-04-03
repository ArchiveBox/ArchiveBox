import os
import sys


PYTHON_DIR = os.path.dirname(os.path.abspath(__file__))

sys.path.append(PYTHON_DIR)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")

import django
django.setup()

from django.conf import settings

DATABASE_FILE = settings.DATABASE_FILE
