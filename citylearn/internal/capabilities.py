"""Explicit interface combinations known to be unsupported in this release."""

def unsupported_reason(schema, interface=None, topology_mode=None):
    interface = interface or schema.get('interface', 'flat')
    topology_mode = topology_mode or schema.get('topology_mode', 'static')
    if interface != 'entity' and topology_mode == 'dynamic':
        return "Dynamic topology requires the entity interface."
    if interface != 'entity' and (schema.get('demand_response') or {}).get('enabled', False):
        return "Demand response requires the entity interface."
    if (interface == 'flat' and schema.get('interface') == 'entity'
            and (schema.get('robustness') or {}).get('enabled', False)):
        return "Robustness targets declared for entity are not translated automatically into flat observations."
    if interface == 'entity' and any(b.get('escalators') for b in schema.get('buildings', {}).values()):
        return "Escalator actions are currently supported only by the flat interface."
    return None
