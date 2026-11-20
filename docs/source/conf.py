# Configuration file for the Sphinx documentation builder.
#
# This file only contains a selection of the most common options. For a full
# list see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Path setup --------------------------------------------------------------

# If extensions (or modules to document with autodoc) are in another directory,
# add these directories to sys.path here. If the directory is relative to the
# documentation root, use os.path.abspath to make it absolute, like shown here.
#
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent / '_ext'))
from citylearn.__init__ import __version__


# -- Project information -----------------------------------------------------

project = 'CityLearn'
copyright = '2023, Jose Ramon Vazquez-Canteli, Kingsley Nweye, Zoltan Nagy'
author = 'Jose Ramon Vazquez-Canteli, Kingsley Nweye, Zoltan Nagy'

# The full version, including alpha/beta/rc tags
release = __version__


# -- General configuration ---------------------------------------------------

# Add any Sphinx extension module names here, as strings. They can be
# extensions coming with Sphinx (named 'sphinx.ext.*') or your custom
# ones.
extensions = [
    'citylearn_guides',
    'sphinx.ext.napoleon',
    'sphinx.ext.viewcode',
    'sphinx.ext.autodoc',
    'sphinxcontrib.bibtex', # for citations
    'sphinxemoji.sphinxemoji', # for emojis
    'sphinx_copybutton', # to copy code block
    'myst_nb', # jupyter notebook
    'nbsphinx_link', # link jupyter notebook from dir that is not in docs/
    'sphinx_panels', # for backgrounds
    'sphinxarg.ext', # document CLI
]

# source for bib references
bibtex_bibfiles = ['references.bib']

# citation style
bibtex_default_style = 'plain'
bibtex_reference_style = 'label'

# Add any paths that contain templates here, relative to this directory.
templates_path = ['_templates']

# List of patterns, relative to source directory, that match files and
# directories to ignore when looking for source files.
# This pattern also affects html_static_path and html_extra_path.
exclude_patterns = ['guides/pt/**', 'guides/retired_datasets.md']

# Canonical Markdown guides are published by citylearn_guides at build time.
myst_heading_anchors = 4
nb_execution_mode = 'off'
nbsphinx_execute = 'never'


# -- Options for HTML output -------------------------------------------------

# The theme to use for HTML and HTML Help pages.  See the documentation for
# a list of builtin themes.
#
html_theme = 'sphinx_rtd_theme'

# Add any paths that contain custom static files (such as style sheets) here,
# relative to this directory. They are copied after the builtin static files,
# so a file named "default.css" will overwrite the builtin "default.css".
html_static_path = ['_static']
html_css_files = ['citylearn.css']

#html context
html_context = {
  'display_github': True,
  'github_user': 'citylearn-project',
  'github_repo': 'CityLearn',
  'github_version': 'master/docs/source/',
}


# -- Link check (sphinx-build -b linkcheck, run weekly by docs-linkcheck.yml) --

# Sites that refuse automated requests but work in a browser.
linkcheck_ignore = [
    r'https://www\.ercot\.com/.*',
]
linkcheck_timeout = 30
linkcheck_retries = 2
# GitHub renders heading anchors with JavaScript, so they cannot be checked.
linkcheck_anchors_ignore_for_url = [r'https://github\.com/.*']
