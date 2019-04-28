# Configuration file for the Sphinx documentation builder.
#
# This file only contains a selection of the most common options. For a full
# list see the documentation:
# http://www.sphinx-doc.org/en/master/config

# -- Path setup --------------------------------------------------------------

# If extensions (or modules to document with autodoc) are in another directory,
# add these directories to sys.path here. If the directory is relative to the
# documentation root, use os.path.abspath to make it absolute, like shown here.
#
import os
import sys
sys.path.insert(0, os.path.abspath('.'))

import django

PYTHON_DIR = os.path.abspath(os.path.dirname(os.path.abspath(__file__)))

sys.path.insert(0, os.path.abspath('../'))
sys.path.insert(0, os.path.abspath('.'))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
django.setup()

VERSION = open(os.path.join(PYTHON_DIR, 'VERSION'), 'r').read().strip()

# -- Project information -----------------------------------------------------

project = 'ArchiveBox'
copyright = '2019, Nick Sweeting'
author = 'Nick Sweeting'

# The full version, including alpha/beta/rc tags
release = VERSION


# -- General configuration ---------------------------------------------------

# Add any Sphinx extension module names here, as strings. They can be
# extensions coming with Sphinx (named 'sphinx.ext.*') or your custom
# ones.
extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.napoleon',
    'sphinx.ext.viewcode',
    # 'sphinxcontrib.blockdiag'
    'recommonmark'
]

source_suffix = {
    '.rst': 'restructuredtext',
    '.txt': 'markdown',
    '.md': 'markdown',
}
master_doc = 'archivebox'
napoleon_google_docstring = True
napoleon_use_param = True
napoleon_use_ivar = False
napoleon_use_rtype = True
napoleon_include_special_with_doc = False

# Add any paths that contain templates here, relative to this directory.
templates_path = ['_templates']

# List of patterns, relative to source directory, that match files and
# directories to ignore when looking for source files.
# This pattern also affects html_static_path and html_extra_path.
exclude_patterns = [
    '_build',
    'Thumbs.db',
    '.DS_Store',
    'data',
    'output',
    'templates',
    'tests',
    'migrations',
]


# -- Options for HTML output -------------------------------------------------

# The theme to use for HTML and HTML Help pages.  See the documentation for
# a list of builtin themes.
#
github_url = 'https://github.com/pirate/ArchiveBox'
html_logo = '../themes/static/archive.png'
html_theme = 'sphinx_rtd_theme'
html_theme_options = {}

texinfo_documents = [
    (master_doc, 'archivebox', 'archivebox Documentation',
     author, 'archivebox', 'The open-source self-hosted internet archive.',
     'Miscellaneous'),
]

pygments_style = 'friendly'

# Add any paths that contain custom static files (such as style sheets) here,
# relative to this directory. They are copied after the builtin static files,
# so a file named "default.css" will overwrite the builtin "default.css".
html_static_path = ['_static']


man_pages = [
    (master_doc, 'archivebox', 'archivebox Documentation',
     [author], 1)
]
