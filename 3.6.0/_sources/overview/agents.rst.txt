======
Agents
======

An agent maps observations to actions. In flat mode with ``central_agent=True``,
one action vector covers the community. In decentralized flat mode, the environment uses
one vector per building. Whether those decisions share information depends on
the controller, not just the number of vectors.

Controller choices
******************

* :py:class:`citylearn.agents.baseline.BusinessAsUsualAgent`: the operational
  reference described in :doc:`../guides/baselines`.
* :py:class:`citylearn.agents.baseline.RBCBasicPolicy`,
  :py:class:`~citylearn.agents.baseline.RBCSmartPolicy` and
  :py:class:`~citylearn.agents.baseline.RBCCommunityPolicy`: reference
  rule-based baselines with price, forecast and community information.
* :py:mod:`citylearn.agents.rbc`: classic hour-based rule-based controllers.
* :py:mod:`citylearn.agents.q_learning`: tabular Q-learning.
* :py:mod:`citylearn.agents.sac`: Soft Actor-Critic.
* :py:mod:`citylearn.agents.marlisa`: coordinated multi-agent learning.
* A custom agent or an external learning library using a compatible wrapper.

The classic RL agents/wrappers use flat spaces. Entity-mode controllers consume
tables, masks and edges and must handle the active population and action
contract. The native BAU and the reference baselines accept both interfaces
through their flat action path.

Create your own
***************

Start with :doc:`../usage/custom_controller`: a complete agent/reward example
with the correct reset/step loop. For the base lifecycle, see
:py:class:`citylearn.agents.base.Agent`.

Use :doc:`../usage/agents` for learning-agent notebooks. Select the reward
separately from the controller and evaluate final results using
:doc:`../kpis`.
