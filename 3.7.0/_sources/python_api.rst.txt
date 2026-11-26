==========
Python API
==========

The supported API is the set of modules below. Their documented classes,
functions and arguments follow the release notes and the migration guide when
they change.

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - Module
     - Use it for
   * - :py:mod:`citylearn.citylearn`
     - ``CityLearnEnv``, the environment: ``reset``, ``step``, ``evaluate_v2``,
       ``scorecard`` and the exports. ``EvaluationCondition`` selects the series
       ``evaluate_v2`` reads. ``set_experiment_identity`` declares the controller
       recorded in the export manifest, which ``compare_exports`` needs to pair two runs.
   * - :py:mod:`citylearn.multi_community`
     - ``MultiCommunityEnv``, several communities run in step, with portfolio KPIs.
   * - :py:mod:`citylearn.agents`
     - Controllers: ``BusinessAsUsualAgent`` and the reference rule-based policies in
       :py:mod:`citylearn.agents.baseline`, the ``Agent`` base class for your own
       controller, and the reinforcement-learning agents.
   * - :py:mod:`citylearn.reward_function`
     - Built-in rewards and the ``RewardFunction`` base class.
   * - :py:mod:`citylearn.wrappers`
     - Gymnasium wrappers: normalised and discrete spaces, Stable-Baselines3 and RLlib adapters.
   * - :py:mod:`citylearn.data`
     - ``DataSet``: list, download and cache the public datasets.
   * - :py:mod:`citylearn.building`, :py:mod:`citylearn.energy_model`,
       :py:mod:`citylearn.electric_vehicle`, :py:mod:`citylearn.electric_vehicle_charger`
     - The simulated buildings and devices, for reading their state and series
       during and after an episode.
   * - :py:mod:`citylearn.cost_function`
     - The legacy cost functions behind ``evaluate()``.
   * - :py:mod:`citylearn.random_streams`
     - The random stream versions selected by ``random_stream_version``.

Other modules are documented for reference but are not a stable interface:
``citylearn.utilities`` and ``citylearn.utils`` hold helpers the package uses
itself, and the remaining modules support the classes above.
``citylearn.internal`` holds the environment's private services. It is not
published here, and it can change in any release without notice.

.. toctree::
   :maxdepth: 1

   All modules <api/modules>
