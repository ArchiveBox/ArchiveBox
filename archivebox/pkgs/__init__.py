import sys
import importlib
from pathlib import Path

PKGS_DIR = Path(__file__).parent

VENDORED_PKGS = [
    'abx',
    # 'abx-pkg',
    # ... everything else in archivebox/pkgs/* comes after ...
]

# VENDORED_PKGS += [ ... ./pkgs/* ... ]
for subdir in reversed(sorted(PKGS_DIR.iterdir())):
    if subdir.is_dir() and subdir.name not in VENDORED_PKGS and not subdir.name.startswith('_'):
        VENDORED_PKGS.append(subdir.name)


def load_vendored_pkgs():
    """Add archivebox/pkgs to sys.path and import all vendored python packages present within"""
    if str(PKGS_DIR) not in sys.path:
        sys.path.append(str(PKGS_DIR))
    
    for pkg_name in VENDORED_PKGS:
        pkg_dir = PKGS_DIR / pkg_name
        assert pkg_dir.is_dir(), f'Required vendored pkg {pkg_name} could not be found in {pkg_dir}'

        try:
            lib = importlib.import_module(pkg_name)
            # print(f"Successfully imported lib from environment {pkg_name}")
        except ImportError:
            sys.path.append(str(pkg_dir))  # perhaps the pkg is in a subdirectory of the directory
            try:
                lib = importlib.import_module(pkg_name)
                # print(f"Successfully imported lib from vendored fallback {pkg_name}: {inspect.getfile(lib)}")
            except ImportError as e:
                print(f"Failed to import required pkg from sys.path or archivebox/pkgs dir {pkg_name}: {e}", file=sys.stderr)
                sys.exit(1)
        

