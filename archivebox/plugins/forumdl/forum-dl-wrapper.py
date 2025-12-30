#!/usr/bin/env python3
"""
Wrapper for forum-dl that applies Pydantic v2 compatibility patches.

This wrapper fixes forum-dl 0.3.0's incompatibility with Pydantic v2 by monkey-patching
the JsonlWriter class to use model_dump_json() instead of the deprecated json(models_as_dict=False).
"""

import sys

# Apply Pydantic v2 compatibility patch BEFORE importing forum_dl
try:
    from forum_dl.writers.jsonl import JsonlWriter
    from pydantic import BaseModel

    # Check if we're using Pydantic v2
    if hasattr(BaseModel, 'model_dump_json'):
        def _patched_serialize_entry(self, entry):
            """Use Pydantic v2's model_dump_json() instead of deprecated json(models_as_dict=False)"""
            return entry.model_dump_json()

        JsonlWriter._serialize_entry = _patched_serialize_entry
except (ImportError, AttributeError):
    # forum-dl not installed or already compatible - no patch needed
    pass

# Now import and run forum-dl's main function
from forum_dl import main

if __name__ == '__main__':
    sys.exit(main())
