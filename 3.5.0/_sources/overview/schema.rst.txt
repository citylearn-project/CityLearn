.. _schema-page:

======
Schema
======

A schema is the JSON configuration used to construct
:py:class:`citylearn.citylearn.CityLearnEnv`. It selects members, data files,
equipment, observations, actions, reward and optional services.

Start from a public dataset's schema, then change the sections required for
your experiment. File paths are resolved against the dataset root. The
:doc:`../guides/schema_reference` gives the supported fields and defaults;
:doc:`../guides/dataset_reference` describes the referenced data.

Load a schema by dataset name, local path or a Python dictionary as shown in
:doc:`../usage/load_environment`. Configuration is part of the simulator's
Python/JSON workflow. CityLearn UI is for exploring exported results.

Example structure
*****************

.. code-block:: text

   schema.json
   ├── simulation window and timestep
   ├── observations and actions
   ├── reward_function
   ├── buildings: data files, devices and electrical_service
   ├── electric_vehicles_def
   └── optional community_market, demand_response, topology and robustness

A complete existing schema is provided below:

.. include:: ../../../data/datasets/baeda_3dem/schema.json
   :code: json
