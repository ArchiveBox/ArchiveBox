# Configuration file for the Sphinx documentation builder.
#
# This file only contains a selection of the most common options. For a full
# list see the documentation:
# http://www.sphinx-doc.org/en/master/config

# -- Path setup --------------------------------------------------------------

# If extensions (or modules to document with autodoc) are in another directory,
# add these directories to sys.path here. If the directory is relative to the
# documentation root, use os.path.abspath to make it absolute, like shown here.

import datetime
import os
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))
sys.path.append(str(Path(__file__).parent.parent / "archivebox"))

# -- Project information -----------------------------------------------------

project = "ArchiveBox"

copyright = f"{datetime.date.today().year} ArchiveBox"
author = "Nick Sweeting"
github_url = "https://github.com/ArchiveBox/ArchiveBox"
github_doc_root = "https://github.com/ArchiveBox/docs/tree/master/"  # docs repo uses master branch
github_view_style = "blob"
language = "en"

# The full version, including alpha/beta/rc tags
release = (Path(__file__).parent.parent / "pyproject.toml").read_text().split("version = ", 1)[-1].split("\n", 1)[0].strip('"').strip("'")
tag = release

# 0.8.5 -> v0.8.5
if release[0].isdigit():
    tag = f"v{release}"  # .split('rc')[0]

# Detect if this is a dev/pre-release build using PEP 440 parsing.
# A version like "0.9.10" with no suffix is stable.
# A version like "0.9.10rc1", "0.9.10.dev1", "0.9.10a1" is pre-release.
# When you release 0.9.0 final (no suffix), it auto-becomes stable.

try:
    from packaging.version import Version

    is_dev = Version(release).is_prerelease or Version(release).is_devrelease
except Exception:
    # fallback if packaging is not installed
    is_dev = any(label in release for label in ("dev", "rc", "alpha", "beta"))
# RTD "latest" always builds from the default branch = dev docs
rtd_version = os.environ.get("READTHEDOCS_VERSION", "")
if rtd_version in ("latest", "dev", "main", "master"):
    is_dev = True

# -- General configuration ---------------------------------------------------

# Add any Sphinx extension module names here, as strings. They can be
# extensions coming with Sphinx (named 'sphinx.ext.*') or your custom
# ones.
extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.linkcode",
    "sphinx.ext.autosummary",
    # 'sphinx.ext.graphviz',
    # 'sphinx.ext.inheritance_diagram'
    "myst_parser",  # pip install myst-parser
    "autodoc2",
    "sphinxcontrib.mermaid",  # pip install sphinxcontrib-mermaid
    # 'recommonmark',
]
autodoc2_packages = [
    {
        "path": "../archivebox",
        "module": "archivebox",
        "exclude_dirs": [
            "__pycache__",
            "migrations",
            "vendor",
            "typings",
            "templates",
            "static",
            "tests",
            "tmp",
        ],
        "exclude_files": [
            "tests.py",
            "conftest.py",
            "fixtures.py",
        ],
    },
]


autodoc2_output_dir = "apidocs"
autodoc2_render_plugin = "myst"
autodoc2_skip_module_regexes = [
    r".*migrations.*",
    r".*vendor.*",
    r".*\.tests($|\..*)",
    r".*\.conftest$",
    r".*\.fixtures$",
]
autodoc2_hidden_regexes = [
    r".*__package__",
]
myst_enable_extensions = ["linkify"]  # pip install linkify-it-py
myst_fence_as_directive = ["mermaid"]  # render ```mermaid blocks via sphinxcontrib-mermaid

source_suffix = {
    ".rst": "restructuredtext",
    ".txt": "markdown",
    ".md": "markdown",
}
master_doc = "index"
napoleon_google_docstring = True
napoleon_use_param = True
napoleon_use_ivar = False
napoleon_use_rtype = True
napoleon_include_special_with_doc = False

# Add any paths that contain templates here, relative to this directory.
templates_path = ["_templates"]

# List of patterns, relative to source directory, that match files and
# directories to ignore when looking for source files.
# This pattern also affects html_static_path and html_extra_path.
exclude_patterns = [
    "_build",
    "**/Thumbs.db",
    "**/.DS_Store",
    "data*",
    "requirements.txt",
    "**/requirements.txt",
    "**/tests/**",
    "**/templates/**",
    "**/migrations/**",
    "_Sidebar.md",
    "_Footer.md",
]

suppress_warnings = [
    "myst.header",  # non-consecutive header levels (common in wiki markdown)
    "myst.xref_missing",  # cross-reference targets from wiki-style links
    "myst.xref_ambiguous",  # ambiguous cross-references across modules
    "autodoc2.dup_item",  # duplicate items from Django model inheritance
]


# -- Options for HTML output -------------------------------------------------

# The theme to use for HTML and HTML Help pages.  See the documentation for
# a list of builtin themes.
#
html_logo = "logo.png"
html_theme = "sphinx_rtd_theme"
html_theme_options = {
    "navigation_depth": 5,
    "collapse_navigation": False,
    "sticky_navigation": True,
    "version_selector": True,
    "language_selector": False,
    "style_external_links": True,
}
html_context = {
    "display_github": True,
    "github_user": "ArchiveBox",
    "github_repo": "docs",
    "github_version": "master",  # docs repo uses master branch
    "conf_py_path": "/",
    # RTD injects these automatically when building on RTD:
    #   current_version, versions, downloads, READTHEDOCS, etc.
    # For local/non-RTD builds, set version info explicitly:
    "current_version": f"{release} (dev)" if is_dev else release,
}
html_show_sphinx = False

# Display the version prominently so users know which docs they're reading
version = release  # short X.Y version shown in sidebar
# release is already set above  # full version with alpha/beta/rc tags

texinfo_documents = [
    (
        master_doc,
        "archivebox",
        "archivebox Documentation",
        author,
        "archivebox",
        "The open-source self-hosted internet archive.",
        "Miscellaneous",
    ),
]

autodoc_default_flags = ["members"]
autodoc_member_order = "bysource"
autosummary_generate = True

pygments_style = "sphinx"

# Add any paths that contain custom static files (such as style sheets) here,
# relative to this directory. They are copied after the builtin static files,
# so a file named "default.css" will overwrite the builtin "default.css".
html_static_path = ["_static"]

man_pages = [
    (master_doc, "archivebox", "archivebox Documentation", [author], 1),
]


def linkcode_resolve(domain, info):
    """
    Calculate link to source code on Github
    Docs: https://www.sphinx-doc.org/en/master/usage/extensions/linkcode.html
    """
    module_name = str(info["module"] or "")
    package_name = module_name.split(".", 1)[0]  # archivebox
    submodule_name = module_name.split(f"{package_name}", 1)[-1].strip(".")  # core.models
    symbol_name = str(info["fullname"] or "")  # Crawl.abid_ts_src
    full_name = f"{package_name}.{submodule_name}.{symbol_name}".replace("..", ".")  # archivebox.core.models.Crawl.abid_ts_src
    fallback_url = f"https://github.com/search?type=code&q=repo%3AArchiveBox%2FArchiveBox%20{full_name.replace('.', '%20')}"

    # 'archivebox.core.models.Crawl' -> archivebox/core/models.py
    file_path = f"{package_name}/{submodule_name.replace('.', '/')}.py"  # archivebox/core/models.py

    # correct for any extra / or .py
    file_path = file_path.strip("/").strip(".py") + ".py"

    # fallback to using Github search instead if URL doesn't look like a valid file path
    if not file_path.startswith("archivebox/"):
        return fallback_url
    if "//" in file_path:
        return fallback_url
    if file_path.count(".py") > 1:
        return fallback_url

    # correct for archivebox/cli.py -> archivebox/cli/__init__.py
    init_path = f"{package_name}/{submodule_name.replace('.', '/')}/__init__.py"
    if not Path(f"../{file_path}").is_file():
        if Path(f"../{init_path}").is_file():
            file_path = init_path
        else:
            return fallback_url

    # https://github.com/ArchiveBox/ArchiveBox/blob/v0.8.5/archivebox/core/models.py#archivebox.core.models.Crawl.abid_ts_src#:~:text=abid_ts_src
    return f"{github_url}/{github_view_style}/{tag}/{file_path}#{full_name}#:~:text={symbol_name.rsplit('.', 1)[-1]}"
