"""Read-only declared target view, independent of current topology presence.

Only lightweight structures and metadata are copied. No reset, topology event,
physical control, dataset copy or mutation is applied to the live environment.
"""

from copy import copy

from citylearn.internal.entity_interface import CityLearnEntityInterfaceService


def declared_target_view(service):
    topology = service.env._topology_service
    view = copy(service.env)
    members = {}

    def member_copy(building, name):
        clone = copy(building)
        clone.name = name
        clone.observation_metadata = building.observation_metadata
        clone.action_metadata = building.action_metadata
        clone.electric_vehicle_chargers = list(building.electric_vehicle_chargers or [])
        clone.deferrable_appliances = list(building.deferrable_appliances or [])
        return clone

    for name, building in topology._initial_member_pool.items():
        clone = member_copy(building, name)
        initial = topology._initial_building_structures[name]
        clone.electric_vehicle_chargers = list(initial.electric_vehicle_chargers)
        clone.deferrable_appliances = list(initial.deferrable_appliances)
        clone.electrical_storage, clone.pv = initial.electrical_storage, initial.pv
        clone.observation_metadata = initial.observation_metadata
        clone.action_metadata = initial.action_metadata
        members[name] = clone

    # Retain each declared identity even after a scheduled removal. Absence is
    # handled by the live layout, not by pretending its event is an unknown ID.
    for event in topology._events:
        target = event.target_member_id
        if event.operation == "add_member" and target not in members:
            if event.source_member_id not in members:
                continue  # The topology service diagnoses an invalid source.
            members[target] = member_copy(members[event.source_member_id], target)
        elif event.operation == "add_asset" and target in members:
            building = members[target]
            source = members.get(event.source_member_id or target)
            if source is None:
                continue
            source_id = event.source_asset_id or event.target_asset_id
            if event.target_asset_type == "charger":
                if any(c.charger_id == event.target_asset_id for c in building.electric_vehicle_chargers):
                    continue
                asset = copy(topology._resolve_source_charger(source, source_id))
                asset.charger_id = event.target_asset_id
                building.electric_vehicle_chargers = [*building.electric_vehicle_chargers, asset]
            elif event.target_asset_type == "deferrable_appliance":
                if any(a.name == event.target_asset_id for a in building.deferrable_appliances):
                    continue
                asset = copy(topology._resolve_source_deferrable_appliance(source, source_id))
                asset.name = event.target_asset_id
                building.deferrable_appliances = [*building.deferrable_appliances, asset]
            elif event.target_asset_type == "electrical_storage":
                building.electrical_storage = topology._resolve_source_storage(source)
            elif event.target_asset_type == "pv":
                building.pv = topology._resolve_source_pv(source)

    for building in members.values():
        topology._sync_dynamic_asset_metadata(building)
    view.buildings = list(members.values())
    view.electric_vehicles = list(topology.ev_pool.values())
    view._entity_service = CityLearnEntityInterfaceService(view)
    validator = copy(service)
    validator.env = view
    validator._flat_layout_cache = None
    view._robustness_service = validator
    return validator
