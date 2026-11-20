========
Glossary
========

The terms below have one meaning throughout the documentation. Where the code
uses a word in more than one sense, the entry says which sense each name
carries.

.. glossary::
   :sorted:

   Agent
   Controller
      The policy that chooses actions at each control step. CityLearn ships rule-based
      controllers (:term:`Business as usual`, :term:`Reference controllers`) and
      reinforcement-learning agents; :doc:`usage/custom_controller` shows how to write your own.

   Business as usual
   BAU
      The operational reference controller, :py:class:`citylearn.agents.baseline.BusinessAsUsualAgent`.
      It charges connected EVs at full power until 100% SOC by default, starts flexible appliances as
      soon as they are ready and uses stationary batteries for PV self-consumption. ``evaluate_v2()``
      runs it on the same scenario and window and reports it in the ``*_business_as_usual_*`` KPIs.
      See :doc:`guides/baselines`.

   Baseline
      In KPI names, ``baseline`` always means the conventional counterfactual: the same buildings
      without storage (and without partial-load control for buildings with LSTM dynamics), PV retained,
      computed from the simulator's own series without another rollout. It is selected by the
      ``baseline_condition`` of ``evaluate_v2()``. It is not the :term:`Business as usual` controller.
      Two class names also contain the word: ``BaselineAgent`` is a passive controller that disables
      every active action (no control), and ``ZeroActionBaselineAgent`` requests zero for every action.
      The rule-based policies are called :term:`Reference controllers`, not baselines. In
      :term:`Demand response` settlement, the request's baseline is its pre-event reference power.

   Reference controllers
      The rule-based policies ``RBCBasicPolicy``, ``RBCSmartPolicy`` and ``RBCCommunityPolicy`` in
      :py:mod:`citylearn.agents.baseline`, used as comparison points for new controllers. See
      :doc:`guides/baselines`.

   Dataset
      A folder with a ``schema.json`` and the data files it names: building loads, weather, prices,
      carbon intensity, EV schedules and events. Public datasets are resolved by name and downloaded
      on first use; the :doc:`guides/dataset_catalogue` lists them.

   Schema
      The JSON file that describes a :term:`Dataset`: its buildings and assets, observations, actions,
      reward, time window and enabled services. Constructor arguments of ``CityLearnEnv`` override the
      matching schema keys. See :doc:`guides/schema_reference`.

   Scenario
      One configuration of a :term:`Dataset`: the schema plus the constructor arguments, such as the
      time window, services, physics version and random seed. Results are comparable only between runs
      of the same scenario.

   Community
   District
      The set of buildings simulated together, which share a grid connection and, when enabled, a
      local market. District KPIs (``level == 'district'``) describe the community as a whole.

   Member
      A building of the :term:`Community`. With dynamic topology, members can join and leave during
      an episode.

   Portfolio
      Several communities run in step by ``MultiCommunityEnv``; portfolio KPIs aggregate them. See
      :doc:`guides/multi_community_reference`.

   Time step
      One row of the dataset, and one simulated interval of ``seconds_per_time_step`` seconds. Energy
      series are in kWh per time step: at a 15-minute step, 1 kW for one step is 0.25 kWh.

   Episode
      The run from ``reset()`` until the environment terminates. An episode of N time steps (states)
      executes N - 1 control steps, because its last state is only the observation after the last
      action: the 24 hourly states of a day give 23 transitions. ``episode_time_steps=25`` covers a
      whole day of hourly data.

   Episode split
      How a long time window is divided into episodes: consecutive episodes (the default), rolling
      episodes that start at every time step, random episodes, or an explicit list of
      ``(start, end)`` windows. Consecutive episodes share their boundary row, so every interval is
      simulated once.

   KPI
   Key performance indicator
      A number that describes a completed simulation, such as cost, imported energy or EV service.
      ``evaluate_v2()`` returns one row per KPI and scope; the KPI name (``cost_function`` column)
      reads ``level_family_subfamily_metric_variant_unit``. See :doc:`kpis`.

   Scorecard
      The default selection of KPIs for comparing controllers, returned by ``env.scorecard()``. See
      :doc:`guides/scorecard`.

   Evaluation condition
      Which series of a building ``evaluate_v2()`` reads: with or without storage, partial load and
      PV. The defaults evaluate the simulated run as the control and the :term:`Baseline` as the
      reference.

   Flat interface
   Entity interface
      The two observation and action contracts. The flat interface exchanges one vector per agent;
      the entity interface exchanges tables of buildings, chargers, EVs and other assets with their
      relations. See :doc:`guides/interfaces_flat_entity`.

   Dynamic topology
      ``topology_mode='dynamic'``: members and assets join or leave the community during the
      episode, following the schema's ``topology_events``. Requires the :term:`Entity interface`.

   Electrical service
      The total and per-phase import and export limits of the community's connections, and the KPIs
      that measure violations of them.

   Demand response
      Requests from a grid operator to change the community's power during an activation window, with
      a direction, a target power, a payment and a shortfall penalty. Delivery is measured against the
      mean power before the event. See :doc:`guides/features`.

   Deferrable appliance
      A flexible load, such as a washing machine, whose cycle must run once between its earliest start
      and its deadline. The controller chooses when it starts.

   EV departure service
      Whether an EV leaves with at least its minimum acceptable charge. Target accuracy, a separate KPI,
      measures how close the departure SOC is to the requested SOC in both directions.

   Physics version
      The version of the device and building physics a run uses: ``2`` (default) or ``1``, the physics of
      CityLearn 3.6.0. See :doc:`guides/migration`.
