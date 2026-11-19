.. _installation-page:

============
Installation
============

CityLearn v3 is distributed as ``citylearn`` on PyPI and requires Python 3.10 or
newer; CityLearn 3.5.0 and older also install on Python 3.9. It supports NumPy 1.x and 2.x: observations, rewards and simulated time
series are bit-identical on both. KPIs can differ in the last binary digits
(relative differences of order 1e-15), for two reasons. NumPy 2.3 and later add
up more than 8,192 values in a different order, which affects totals over
episodes longer than 8,192 time steps, such as a full year of hourly steps, and
the district Gini ratio of more than 90 members. The equity audit's Gini ratio
uses a BLAS dot product, whose last digit depends on the BLAS build and the
CPU, and NumPy 1 and 2 wheels ship different OpenBLAS releases.

Use a virtual environment to keep its dependencies separate.

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

Version compatibility
*********************

The base requirements of each release, from its ``requirements.txt`` and
``python_requires``; "any" means the release does not constrain the version.
The first row is the source on ``master``, which the next release will ship.
The last column gives the Python versions for which the pinned requirements
publish wheels on PyPI. It is derived from those pins, not tested, and names
the pin that sets the limit. CityLearn 2.4.0 to 2.4.2 were withdrawn from PyPI.

.. csv-table::
   :header: "CityLearn", "Tag date", "Python", "NumPy", "Gym / Gymnasium", "scikit-learn", "PyTorch", "Other pins", "Installable Python (derived)"

   "Unreleased", "-", ">=3.10", "<3.0.0", "gymnasium>=0.28.1,<2.0.0", "any", "any", "none", "3.10 - 3.14 in CI; 3.15 lacks wheels for pandas, scikit-learn and PyYAML on some platforms"
   "3.3.0 - 3.5.0", "2026-11-13 - 2026-11-17", ">=3.9", "<3.0.0", "gymnasium>=0.28.1,<2.0.0", "any", "any", "none", "No pin limits Python; see the CI coverage below"
   "3.2.0", "2026-11-06", ">=3.9", "<2.0.0", "gymnasium>=0.28.1,<2.0.0", "<=1.2.2", "any", "none; OpenStudio and doe_xstock moved to the end_use_load_profiles extra", "3.9 - 3.11 (scikit-learn 1.2.2)"
   "3.0.0 - 3.1.1", "2026-09-09 - 2026-11-04", ">=3.9", "<2.0.0", "gymnasium<=0.28.1", "<=1.2.2", "any (with torchvision)", "doe_xstock>=2.0.0, openstudio<=3.10.0", "3.9 - 3.11 (scikit-learn 1.2.2), where OpenStudio <=3.10.0 has a wheel"
   "2.5.0", "2025-10-30", ">=3.7.7", "<2.0.0", "gymnasium<=0.28.1", "<=1.2.2", "any (with torchvision)", "doe_xstock>=1.1.0, openstudio<=3.3.0, nrel-pysam", "Where OpenStudio <=3.3.0 has a wheel; reported to install on 3.9 and to fail on 3.10 and 3.11"
   "2.2.0 - 2.4.2", "2024-11-06 - 2025-08-10", ">=3.7.7", "<2.0.0", "gymnasium (any)", "<=1.2.2", "any (with torchvision)", "doe_xstock>=1.0.0 (2.2.0) or >=1.1.0, openstudio<=3.3.0, nrel-pysam", "Where OpenStudio <=3.3.0 has a wheel; reported to install on 3.9 and to fail on 3.10 and 3.11"
   "2.0.0 - 2.1.2", "2023-09-10 - 2024-02-25", ">=3.7", ">=1.21.6", "gym>=0.21.0", "==1.0.2", ">=1.12.0 (with torchvision>=0.13.0)", "pandas==1.3.5", "3.7 - 3.10 (pandas 1.3.5, scikit-learn 1.0.2)"
   "1.5.0 - 1.8.0", "2023-01-28 - 2023-04-06", ">=3.7", "==1.21.6", "gym==0.25.1 (1.8.0: gym>=0.21.0)", "==1.0.2", "==1.12.0 (with torchvision==0.13.0)", "pandas==1.3.5", "3.7 - 3.10 (NumPy 1.21.6, PyTorch 1.12.0)"

Continuous integration runs the test suite on Linux with Python 3.10, 3.11,
3.12, 3.13 and 3.14 (NumPy 2, and NumPy 1 on Python 3.10). It also installs the
built package with ``pip`` and runs a simulation on macOS (Apple Silicon) and
Windows with Python 3.10 and 3.14. Python 3.10 reached its upstream end of life
in October 2026; CityLearn keeps it as the minimum while downstream users still
run it.

Troubleshooting installation
****************************

``No matching distribution found for openstudio<=3.3.0``
   CityLearn 2.2.0 to 2.5.0 required OpenStudio 3.3.0 or older, which PyPI does
   not provide for recent Python versions (reported for 3.10 and 3.11). Install
   CityLearn 3.2.0 or newer: OpenStudio and ``doe_xstock`` are then needed only
   for ``citylearn.end_use_load_profiles`` and come with the
   ``end_use_load_profiles`` extra.

scikit-learn fails to compile, for example with an OpenMP error on macOS
   CityLearn 2.2.0 to 3.2.0 pinned ``scikit-learn<=1.2.2``, which has no wheels
   for Python 3.12 or newer, so ``pip`` tries to build it from source. Install
   CityLearn 3.3.0 or newer, or use Python 3.11 or older for those releases.

``TypeError: 'staticmethod' object is not callable`` when importing CityLearn
   Reported for CityLearn 2.3.0 on Python 3.9. Install a current release.

An old release is required to reproduce earlier results
   Install it without dependencies and then the dependencies that the table
   above lists for it, with versions available for your Python:

   .. code-block:: console

      python -m pip install --no-deps citylearn==2.3.1

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
