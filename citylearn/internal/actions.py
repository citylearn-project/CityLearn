"""Route active action names to the keyword arguments of :py:meth:`citylearn.building.Building.apply_actions`.

Every parser (flat vectors, entity vectors and entity tables) and every place that builds a building's zero
action uses :py:func:`building_action_kwargs`, so a device action is grouped the same way everywhere.
"""

from typing import Any, Dict, Iterable, Mapping

ELECTRIC_VEHICLE_ACTION_PREFIX = 'electric_vehicle_storage_'
DEFERRABLE_APPLIANCE_ACTION_PREFIX = 'deferrable_appliance_'
ESCALATOR_ACTION_PREFIX = 'escalator_'


def building_action_kwargs(names: Iterable[str], values: Iterable[Any]) -> Mapping[str, Any]:
    """Return the :py:meth:`Building.apply_actions` keyword arguments for paired action names and values.

    Names are matched by prefix:

    - ``electric_vehicle_storage_<charger_id>`` goes to ``electric_vehicle_storage_actions`` keyed by charger id;
    - ``deferrable_appliance_<id>`` goes to ``deferrable_appliance_actions`` keyed by the full action name;
    - ``escalator_<id>`` goes to ``escalator_actions`` keyed by the full action name;
    - any other name ``<name>`` becomes the keyword ``<name>_action``.

    Values are passed through unchanged, so clipping and type conversion stay with the caller. The grouped
    mappings are only present when at least one name of that kind is given.
    """

    kwargs: Dict[str, Any] = {}
    electric_vehicle_actions: Dict[str, Any] = {}
    deferrable_appliance_actions: Dict[str, Any] = {}
    escalator_actions: Dict[str, Any] = {}

    for name, value in zip(names, values):
        if name.startswith(ELECTRIC_VEHICLE_ACTION_PREFIX):
            electric_vehicle_actions[name[len(ELECTRIC_VEHICLE_ACTION_PREFIX):]] = value
        elif name.startswith(DEFERRABLE_APPLIANCE_ACTION_PREFIX):
            deferrable_appliance_actions[name] = value
        elif name.startswith(ESCALATOR_ACTION_PREFIX):
            escalator_actions[name] = value
        else:
            kwargs[f'{name}_action'] = value

    if electric_vehicle_actions:
        kwargs['electric_vehicle_storage_actions'] = electric_vehicle_actions
    if deferrable_appliance_actions:
        kwargs['deferrable_appliance_actions'] = deferrable_appliance_actions
    if escalator_actions:
        kwargs['escalator_actions'] = escalator_actions

    return kwargs


def zero_building_action_kwargs(names: Iterable[str]) -> Mapping[str, Any]:
    """Return :py:func:`building_action_kwargs` with every named action set to 0.0."""

    names = list(names)
    return building_action_kwargs(names, [0.0] * len(names))
