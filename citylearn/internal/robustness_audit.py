"""Explicit observation-index and completed-interval robustness populations."""

DEFINITION_VERSION = "robustness-audit-v1"


def metadata():
    return {
        "definition_version": DEFINITION_VERSION,
        "legacy_population": "queried_observation_indices_and_action_applications_including_terminal_telemetry",
        "executed_population": "completed_physical_intervals_only",
        "coverage_unit": "event_step_with_at_least_one_matching_application_not_individual_sensor_uptime",
        "empty_denominator": None,
        "inactive_targets": "scheduled_but_not_applied",
        "masking": "applications_counted_before_hidden_fault_allowlist_masking",
        "state_identity": "event_id_and_logical_target_id_retained_across_absence_cleared_on_reset",
    }


def summary(service):
    env = service.env
    start = int(env.episode_tracker.episode_start_time_step)
    end = int(env.episode_tracker.episode_end_time_step)
    current = start + int(env.time_step)
    observed = set(service._observed_steps)
    names = list(dict.fromkeys(
        [b.name for b in getattr(env, "_all_buildings", env.buildings)]
        + [application["building"] for record in service._history.values()
           for application in record["applications"] if application["building"] is not None]
    ))
    legacy_buildings, legacy_district = service.summarize(names)
    executed_buildings, executed_district = service.summarize(names, executed_only=True)
    district = {
        "configured_event_count": len(service.events),
        "enabled_event_count": 0,
        "scheduled_event_count": 0,
        "observation_index_count": len(observed),
        "executed_interval_count": int(env.time_step),
        "terminal_observation_count": int(env.terminated and current in observed),
        "unexecuted_observation_count": sum(step >= current for step in observed),
        "window_observation_event_step_count": 0,
        "applied_observation_event_step_count": 0,
        "window_action_event_step_count": 0,
        "applied_action_event_step_count": 0,
    }
    applications = {}
    for step, record in service._history.items():
        for application in record["applications"]:
            applications.setdefault(application["event_id"], {}).setdefault(
                application["kind"], set()
            ).add(step)

    rows = []
    for event in service.events:
        enabled = service.enabled and service._module_enabled(event.module)
        scheduled = enabled and event.end_time_step >= start and event.start_time_step <= end
        observation = enabled and (
            event.module in {"observation", "forecast"}
            or event.module == "asset" and event.target_feature in service.TELEMETRY_FEATURES
        )
        action = enabled and (
            event.module == "action"
            or event.module == "asset" and event.target_feature in service.CONTROL_FEATURES
        )
        applied = applications.get(event.event_id, {})
        observation_steps = applied.get("observation", set()) | applied.get("forecast", set())
        row = {
            "event_id": event.event_id,
            "module": event.module,
            "target_type": event.target_type,
            "target_id": event.target_id,
            "target_feature": event.target_feature,
            "start_time_step": event.start_time_step,
            "end_time_step": event.end_time_step,
            "enabled": bool(enabled),
            "scheduled_in_episode": bool(scheduled),
            "window_observation_step_count": sum(
                event.start_time_step <= step <= event.end_time_step for step in observed
            ) if observation else 0,
            "applied_observation_step_count": len(observation_steps & observed),
            "window_action_step_count": max(
                0, min(current - 1, event.end_time_step) - max(start, event.start_time_step) + 1
            ) if action else 0,
            "applied_action_step_count": sum(start <= step < current for step in applied.get("action", set())),
        }
        district["enabled_event_count"] += int(enabled)
        district["scheduled_event_count"] += int(scheduled)
        for kind in ("observation", "action"):
            numerator = row[f"applied_{kind}_step_count"]
            denominator = row[f"window_{kind}_step_count"]
            row[f"{kind}_application_coverage_ratio"] = numerator / denominator if denominator else None
            district[f"window_{kind}_event_step_count"] += denominator
            district[f"applied_{kind}_event_step_count"] += numerator
        rows.append(row)
    for kind in ("observation", "action"):
        denominator = district[f"window_{kind}_event_step_count"]
        district[f"{kind}_application_coverage_ratio"] = (
            district[f"applied_{kind}_event_step_count"] / denominator if denominator else None
        )
    return {
        **metadata(),
        "enabled": bool(service.enabled),
        "district": district,
        "events": rows,
        "legacy": {"buildings": legacy_buildings, "district": legacy_district},
        "executed_intervals": {"buildings": executed_buildings, "district": executed_district},
    }
