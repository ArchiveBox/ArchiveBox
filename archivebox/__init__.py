__package__ = 'archivebox'
from .config import setup_django, OUTPUT_DIR

print(OUTPUT_DIR)
setup_django()
