import sys
import importlib
from pathlib import Path

VENDOR_DIR = Path(__file__).parent

VENDORED_LIBS = {
    # sys.path dir:         library name
    #'python-atomicwrites':  'atomicwrites',
    #'django-taggit':        'taggit',
    'pydantic-pkgr':        'pydantic_pkgr',
    'pocket':               'pocket',
    #'base32-crockford':     'base32_crockford',
}

def load_vendored_libs():
    for lib_subdir, lib_name in VENDORED_LIBS.items():
        lib_dir = VENDOR_DIR / lib_subdir
        assert lib_dir.is_dir(), 'Expected vendor libary {lib_name} could not be found in {lib_dir}'

        try:
            lib = importlib.import_module(lib_name)
            # print(f"Successfully imported lib from environment {lib_name}: {inspect.getfile(lib)}")
        except ImportError:
            sys.path.append(str(lib_dir))
            try:
                lib = importlib.import_module(lib_name)
                # print(f"Successfully imported lib from vendored fallback {lib_name}: {inspect.getfile(lib)}")
            except ImportError as e:
                print(f"Failed to import lib from environment or vendored fallback {lib_name}: {e}", file=sys.stderr)
                sys.exit(1)
        

