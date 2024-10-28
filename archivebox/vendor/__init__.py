import sys
import importlib
from pathlib import Path

VENDOR_DIR = Path(__file__).parent

VENDORED_LIBS = [
    'abx',
    'pydantic-pkgr',
    'pocket',
]

for subdir in reversed(sorted(VENDOR_DIR.iterdir())):
    if subdir.is_dir() and subdir.name not in VENDORED_LIBS and not subdir.name.startswith('_'):
        VENDORED_LIBS.append(subdir.name)

def load_vendored_libs():
    if str(VENDOR_DIR) not in sys.path:
        sys.path.append(str(VENDOR_DIR))
    
    for lib_name in VENDORED_LIBS:
        lib_dir = VENDOR_DIR / lib_name
        assert lib_dir.is_dir(), f'Expected vendor libary {lib_name} could not be found in {lib_dir}'

        try:
            lib = importlib.import_module(lib_name)
            # print(f"Successfully imported lib from environment {lib_name}")
        except ImportError:
            sys.path.append(str(lib_dir))
            try:
                lib = importlib.import_module(lib_name)
                # print(f"Successfully imported lib from vendored fallback {lib_name}: {inspect.getfile(lib)}")
            except ImportError as e:
                print(f"Failed to import lib from environment or vendored fallback {lib_name}: {e}", file=sys.stderr)
                sys.exit(1)
        

