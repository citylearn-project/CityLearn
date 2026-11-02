"""Conservative, channel-specific bounds for configured telemetry faults."""

import numpy as np
from gymnasium import spaces


def _envelope(service, event, low, high, dtype):
    if event.module == "asset" or event.mode == "missing":
        candidate_low = candidate_high = service._event_replacement_value(event)
    elif event.mode == "bias":
        candidate_low, candidate_high = low + (event.value or 0.0), high + (event.value or 0.0)
    elif event.mode == "noise" and (event.std or 0.0) > 0.0:
        candidate_low, candidate_high = -np.inf, np.inf
    elif event.mode == "clip":
        minimum = -np.inf if event.min_value is None else event.min_value
        maximum = np.inf if event.max_value is None else event.max_value
        candidate_low, candidate_high = np.clip([low, high], minimum, maximum)
    else:
        # Stuck samples an earlier value at this same point in the channel
        # pipeline, so the incoming envelope also covers its stored value.
        return low, high

    # Include inactive windows and round outward, including intermediate float32
    # assignments in entity tables and unrounded Python floats in flat outputs.
    lower, upper = min(low, candidate_low), max(high, candidate_high)
    with np.errstate(over="ignore"):
        rounded_low, rounded_high = np.asarray([lower, upper], dtype=dtype)
    if rounded_low > lower:
        rounded_low = np.nextafter(rounded_low, dtype.type(-np.inf))
    if rounded_high < upper:
        rounded_high = np.nextafter(rounded_high, dtype.type(np.inf))
    return float(rounded_low), float(rounded_high)


def adjusted_space(service, observation_space):
    events = sorted(
        (event for event in service.events if service._module_enabled(event.module)
         and (event.module in {"observation", "forecast"}
              or (event.module == "asset" and event.target_feature in service.TELEMETRY_FEATURES))),
        key=lambda event: event.order,
    )
    if not events:
        return observation_space

    def adjust_box(box, applications):
        low, high = box.low.copy(), box.high.copy()
        for event, index in applications:
            low[index], high[index] = _envelope(
                service, event, float(low[index]), float(high[index]), box.dtype
            )
        return spaces.Box(low=low, high=high, dtype=box.dtype)

    if service.env.interface == "entity":
        specs = service.env.entity_specs["tables"]
        tables = {}
        for table, box in observation_space["tables"].spaces.items():
            applications = []
            features, ids = specs[table]["features"], specs[table]["ids"]
            for event in events:
                if event.target_type != table:
                    continue
                columns = (range(len(features)) if event.module == "asset"
                           else service._matching_feature_indices(event, features))
                for row in service._matching_entity_rows(event, table, ids):
                    applications.extend((event, (row, column)) for column in columns)
            tables[table] = adjust_box(box, applications) if applications else box
        return spaces.Dict({**observation_space.spaces, "tables": spaces.Dict(tables)})

    result = []
    for box, layout in zip(observation_space, service._flat_observation_layout()):
        applications = [(event, index) for event in events for index, descriptor in enumerate(layout)
                        if service._observation_event_matches(event, descriptor)]
        result.append(adjust_box(box, applications) if applications else box)
    return result
