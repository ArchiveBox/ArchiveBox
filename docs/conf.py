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
import inspect
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
github_view_style = "blob"
language = "en"

# The full version, including alpha/beta/rc tags
release = (Path(__file__).parent.parent / "pyproject.toml").read_text().split("version = ", 1)[-1].split("\n", 1)[0].strip('"').strip("'")
tag = release

# 0.8.5 -> v0.8.5
if release[0].isdigit():
    tag = f"v{release}"  # .split('rc')[0]

# Branch and PR builds must link to the code they actually document.
tag = os.environ.get("READTHEDOCS_GIT_COMMIT_HASH") or os.environ.get("READTHEDOCS_GIT_IDENTIFIER") or tag
github_doc_root = f"{github_url}/tree/{tag}/docs/"

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
    "sphinx_rtd_theme",
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
# Preserve GitHub-compatible heading fragments used by the shared wiki pages.
myst_heading_anchors = 6
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
    "github_repo": "ArchiveBox",
    "github_version": tag,
    "conf_py_path": "/docs/",
    # RTD injects these automatically when building on RTD:
    #   current_version, versions, downloads, READTHEDOCS, etc.
    # For local/non-RTD builds, set version info explicitly:
    "current_version": rtd_version or release,
    "is_dev": is_dev,
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
    """Link re-exported symbols to their defining file without importing Django."""
    if domain != "py" or not info.get("module", "").startswith("archivebox"):
        return None
    root = Path(__file__).resolve().parent.parent
    module_name = info["module"]
    obj = sys.modules.get(module_name)
    source = None
    anchor = ""
    try:
        for part in info.get("fullname", "").split("."):
            if part:
                obj = inspect.getattr_static(obj, part)
        if isinstance(obj, property):
            obj = obj.fget
        obj = inspect.unwrap(obj)
        source = inspect.getsourcefile(obj)
        lines, start = inspect.getsourcelines(obj)
        anchor = f"#L{start}-L{start + len(lines) - 1}"
    except (AttributeError, TypeError, OSError):
        # Static autodoc builds may not have loaded the object. Link its module.
        module_path = root.joinpath(*module_name.split("."))
        source = next((path for path in (module_path.with_suffix(".py"), module_path / "__init__.py") if path.is_file()), None)
    if source is None:
        return None
    try:
        relative = Path(source).resolve().relative_to(root)
    except ValueError:
        return None
    return f"{github_url}/{github_view_style}/{tag}/{relative.as_posix()}{anchor}"


def configure_source_links(app, pagename, templatename, context, doctree):
    """Generated API pages have Python source links, not editable Markdown files."""
    if pagename.startswith("apidocs/"):
        context["display_github"] = False
    elif pagename == "README":
        context["conf_py_path"] = "/"


def setup(app):
    app.connect("html-page-context", configure_source_links)
