.. _installation-page:

============
Installation
============

CityLearn v3 is distributed as ``citylearn`` on PyPI and requires Python 3.9 or
newer. It supports NumPy 1.x and 2.x and gives bit-identical simulation results
on both. Use a virtual environment to keep its dependencies separate.

.. code-block:: console

   python -m venv .venv

Activate it on Linux or macOS:

.. code-block:: console

   source .venv/bin/activate

On Windows PowerShell:

.. code-block:: powershell

   .venv\Scripts\Activate.ps1

Install and check the package:

.. code-block:: console

   python -m pip install --upgrade pip
   python -m pip install citylearn
   python -c "from citylearn import __version__; print(__version__)"

Continue with :doc:`quickstart`. Both the package and Python import name are
``citylearn``.

Optional dependencies
*********************

For Parquet datasets or exports:

.. code-block:: console

   python -m pip install "citylearn[parquet]"

For PV autosizing from EPW weather using PySAM:

.. code-block:: console

   python -m pip install "citylearn[pysam]"

For building new datasets from End-Use Load Profiles with
``citylearn.end_use_load_profiles`` (installs ``doe_xstock`` and OpenStudio):

.. code-block:: console

   python -m pip install "citylearn[end_use_load_profiles]"

Datasets
********

Public datasets are downloaded from the official repository and cached locally.
The first download needs internet access. List the available names in Python:

.. code-block:: python

   from citylearn.data import DataSet
   print(DataSet().get_dataset_names())

For your own data, pass a local ``schema.json`` path instead of a dataset name.
See :doc:`guides/dataset_reference` for files, units and offline use.

Existing projects and development
*********************************

Record the installed version with the command above and pin that version
in your project dependencies. Read :doc:`guides/migration` when updating a project.
To work on CityLearn itself, follow :doc:`guides/developer_guide`.
