from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import hashlib
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Mapping, Optional, Sequence, Tuple

from gymnasium import spaces
import numpy as np
import pandas as pd

from citylearn.utilities import parse_bool
from citylearn.internal.robustness_history import RobustnessHistory

if TYPE_CHECKING:
    from citylearn.citylearn import CityLearnEnv


REQUIRED_EVENT_COLUMNS = {
    "event_id",
    "module",
    "target_type",
    "target_id",
    "target_feature",
    "start_time_step",
    "end_time_step",
    "mode",
}


@dataclass(frozen=True)
class RobustnessEvent:
    """Canonical robustness event loaded from a dataset file."""

    event_id: str
    module: str
    target_type: str
    target_id: str
    target_feature: str
    start_time_step: int
    end_time_step: int
    mode: str
    event_domain: str
    value: Optional[float]
    std: Optional[float]
    min_value: Optional[float]
    max_value: Optional[float]
    replacement_value: Optional[float]
    delay_steps: int
    order: int


class CityLearnRobustnessService:
    """Dataset-driven robustness perturbations for observations, actions and asset availability."""

    DEFAULT_MISSING_REPLACEMENT_VALUE = -9999.0
    MODULE_ALIASES = {
        "observation": "observations",
        "forecast": "forecasts",
        "action": "actions",
        "asset": "assets",
    }
    VALID_MODES = {
        "observation": {"missing", "noise", "bias", "stuck", "clip"},
        "forecast": {"missing", "noise", "bias", "stuck", "clip"},
        "action": {"dropout", "noise", "bias", "stuck", "delay", "clip"},
        "asset": {"unavailable"},
    }
    VALID_TARGET_TYPES = {
        "district",
        "building",
        "storage",
        "charger",
        "ev",
        "pv",
        "deferrable_appliance",
    }
    VALID_EVENT_DOMAINS = {
        "ASSET_CONNECTION",
        "ASSET_AVAILABILITY",
        "SENSOR_CHANNEL",
        "ACTUATOR_CHANNEL",
        "COMMUNICATION_LINK",
        "VALUE_QUALITY",
    }
    TELEMETRY_FEATURES = {"telemetry", "both", "*"}
    CONTROL_FEATURES = {"control", "both", "*"}
    KPI_KEYS = (
        "robustness_events_count",
        "robustness_active_time_step_count",
        "robustness_observation_corruption_count",
        "robustness_forecast_corruption_count",
        "robustness_action_corruption_count",
        "robustness_asset_unavailable_time_step_count",
        "robustness_missing_observation_count",
        "robustness_action_dropout_count",
    )

    def __init__(self, env: "CityLearnEnv"):
        self.env = env
        self.enabled = False
        self.events_file: Optional[str] = None
        self.random_seed = 0
        self.missing_replacement_value = self.DEFAULT_MISSING_REPLACEMENT_VALUE
        self.modules_enabled: Dict[str, bool] = {
            "observations": False,
            "forecasts": False,
            "actions": False,
            "assets": False,
        }
        self._events: List[RobustnessEvent] = []
        self._cursor = 0
        self._active_cache_step: Optional[int] = None
        self._active_cache: List[RobustnessEvent] = []
        self._history = RobustnessHistory()
        self._stuck_values: Dict[Tuple[str, str], float] = {}
        self._action_history: Dict[str, List[Tuple[int, float]]] = {}
        self._flat_layout_cache = None
        self._validated_layout_signature = None
        self._declared_target_validator = None
        self._observed_steps = set()
        self._max_delay_steps = 1
        self._configure()

    @property
    def events(self) -> Sequence[RobustnessEvent]:
        return tuple(self._events)

    @property
    def history(self) -> Mapping[int, Mapping[str, Any]]:
        return {key: self._public_record(value) for key, value in sorted(self._history.items())}

    def iter_history(self, start=None, stop=None):
        """Yield detached public records in [start, stop), without a full copy."""
        for step in sorted(self._history):
            if (start is None or step >= start) and (stop is None or step < stop):
                yield step, deepcopy(self._public_record(self._history[step]))

    def history_window(self, start=None, stop=None):
        """Return a detached public snapshot of the requested step window."""
        return dict(self.iter_history(start, stop))

    def initialize(self):
        """Load event definitions after `env.root_directory` is available."""

        if not self.enabled:
            self._events = []
            return

        if not self.events_file:
            raise ValueError("robustness.events_file is required when robustness.enabled=true.")

        path = Path(str(self.events_file)).expanduser()
        if not path.is_absolute():
            path = Path(str(getattr(self.env, "root_directory", "") or "")) / path

        if not path.is_file():
            raise FileNotFoundError(f"robustness.events_file does not exist: {path}")

        suffix = path.suffix.lower()
        if suffix in {".parquet", ".pq"}:
            frame = pd.read_parquet(path)
        elif suffix in {".csv", ".txt"}:
            # Preserve explicit "nan"/"inf" parameters for validation; only
            # empty fields represent omitted CSV parameters.
            frame = pd.read_csv(path, keep_default_na=False)
        else:
            raise ValueError("robustness.events_file must be a CSV or Parquet file.")

        self._events = self._parse_events(frame)
        self._max_delay_steps = max((event.delay_steps for event in self._events), default=1)

    def reset(self):
        """Reset episode-local state without reloading event definitions."""

        if (self.env.schema.get('robustness') or {}).get('random_seed') is None:
            self.random_seed = int(self.env.random_seed)
        self._cursor = 0
        self._active_cache_step = None
        self._active_cache = []
        self._history = RobustnessHistory()
        self._stuck_values = {}
        self._action_history = {}
        self._flat_layout_cache = None
        self._validated_layout_signature = None
        self._declared_target_validator = None
        self._observed_steps = set()

    def get_metadata(self) -> Mapping[str, Any]:
        from citylearn.internal.observation_contract import configuration
        from citylearn.internal.robustness_audit import metadata as audit_metadata
        return {
            'agent_observation_contract': configuration(self.env),
            'counter_contract': audit_metadata(),
            "enabled": bool(self.enabled),
            "events_file": self.events_file,
            "random_seed": int(self.random_seed),
            "missing_replacement_value": float(self.missing_replacement_value),
            "modules": {
                key: {"enabled": bool(value)}
                for key, value in self.modules_enabled.items()
            },
            "event_count": int(len(self._events)),
        }

    def observation_values(self) -> Mapping[str, float]:
        """Return entity robustness bundle values for the district table."""

        if not self.enabled:
            return self._zero_observation_values()

        current_step = self._global_time_step()
        previous = self._counts_for_step(current_step - 1)
        active = [event for event in self._active_events(current_step) if self._module_enabled(event.module)]
        active_asset_count = sum(1 for event in active if event.module == "asset")

        return {
            "robustness_active": 1.0 if active else 0.0,
            "robustness_observation_corruption_count_previous": float(previous["observation"]),
            "robustness_forecast_corruption_count_previous": float(previous["forecast"]),
            "robustness_action_corruption_count_previous": float(previous["action"]),
            "robustness_asset_unavailable_count": float(active_asset_count),
        }

    def observation_meta(self, *, current_step: Optional[int] = None) -> Mapping[str, Any]:
        step = self._global_time_step() if current_step is None else int(current_step)
        active = [event for event in self._active_events(step) if self._module_enabled(event.module)]
        counts = self._counts_for_step(step)
        return {
            "enabled": bool(self.enabled),
            "active_event_ids": [event.event_id for event in active],
            "active_modules": sorted({event.module for event in active}),
            "applied_event_ids": sorted(self._history.get(step, {}).get("event_ids", set())),
            "last_step_counts": {
                "observation": counts["observation"],
                "forecast": counts["forecast"],
                "action": counts["action"],
                "asset": counts["asset"],
                "missing_observation": counts["missing"],
                "action_dropout": counts["dropout"],
            },
        }

    def runtime_status(self, *, current_step: Optional[int] = None) -> Mapping[str, Any]:
        """Return raw runtime evidence without deriving TI-MARL health.

        ``fault_mode`` is deliberately preserved as the simulator cause.  The
        consumer decides whether the same evidence is healthy, degraded,
        stale, missing or failed for its own semantic contract.
        """

        step = self._global_time_step() if current_step is None else int(current_step)
        active = [
            event
            for event in self._active_events(step)
            if self._module_enabled(event.module)
        ]
        payload: Dict[str, Any] = {
            "version": "runtime_status_v1",
            "emits_health_state": False,
            "active_events": [self._runtime_event_record(event, step) for event in active],
            "asset_connections": [],
            "asset_availability": [],
            "sensor_channels": [],
            "actuator_channels": [],
            "communication_links": [],
            "value_quality": [],
        }
        collection_by_domain = {
            "ASSET_AVAILABILITY": "asset_availability",
            "SENSOR_CHANNEL": "sensor_channels",
            "ACTUATOR_CHANNEL": "actuator_channels",
            "COMMUNICATION_LINK": "communication_links",
            "VALUE_QUALITY": "value_quality",
        }
        for event in active:
            collection = collection_by_domain.get(event.event_domain)
            if collection is None:
                # ASSET_CONNECTION is represented from actual entity relations
                # by the entity-interface service, not inferred from a fault.
                continue
            payload[collection].extend(self._resolved_runtime_status_records(event, step))

        for key in collection_by_domain.values():
            payload[key].sort(
                key=lambda row: (
                    str(row.get("target_type", "")),
                    str(row.get("target_id", "")),
                    str(row.get("target_feature", "")),
                    str(row.get("event_id", "")),
                )
            )
        return payload

    def apply_observations(self, observations: Any) -> Any:
        from citylearn.internal.observation_contract import apply
        if self.enabled:
            self._observed_steps.add(self._global_time_step())
        return apply(self, self._apply_observation_events(observations))

    def _apply_observation_events(self, observations: Any) -> Any:
        """Apply observation/forecast/telemetry events to the agent-facing payload."""

        if not self.enabled:
            return observations

        step = self._global_time_step()
        active = [
            event for event in self._active_events(step)
            if self._module_enabled(event.module)
            and (
                event.module in {"observation", "forecast"}
                or (event.module == "asset" and event.target_feature in self.TELEMETRY_FEATURES)
            )
        ]

        if not active:
            return observations

        if getattr(self.env, "interface", "flat") == "entity" and isinstance(observations, Mapping):
            self._apply_entity_observation_events(observations, active, step)
            meta = observations.setdefault("meta", {})
            if isinstance(meta, dict):
                meta["robustness"] = self.observation_meta(current_step=step)
            return observations

        self._apply_flat_observation_events(observations, active, step)
        return observations

    def apply_actions(self, parsed_actions: Sequence[Mapping[str, Any]]) -> Sequence[Mapping[str, Any]]:
        """Apply action-channel and asset-control events to parsed action dictionaries."""

        if not self.enabled:
            return parsed_actions

        step = self._global_time_step()
        active = [
            event for event in self._active_events(step)
            if self._module_enabled(event.module)
            and (
                event.module == "action"
                or (event.module == "asset" and event.target_feature in self.CONTROL_FEATURES)
            )
        ]
        delay_events = [
            event for event in self._events
            if event.module == "action"
            and event.mode == "delay"
            and self._module_enabled(event.module)
        ]

        if not active and not delay_events:
            return parsed_actions

        actions = deepcopy(parsed_actions)
        descriptors = self._action_descriptors(actions)

        for descriptor in descriptors:
            if any(self._action_event_matches(event, descriptor) for event in delay_events):
                self._append_action_history(descriptor["target_key"], step, descriptor["get"]())

        if not active:
            return actions

        # Channel transforms keep file order (e.g. bias then clip). Asset
        # availability is a final control constraint, never a transform that
        # a later channel event can undo.
        channel_events = [event for event in active if event.module == "action"]
        availability_events = [event for event in active if event.module == "asset"]
        for event in channel_events + availability_events:
            for descriptor in descriptors:
                if event.module == "asset":
                    if not self._asset_control_event_matches(event, descriptor):
                        continue
                    descriptor["set"](0.0)
                    self._record_application(event, "action", descriptor, mode="dropout")
                    self._record_application(event, "asset", descriptor, mode="unavailable")
                    continue

                if not self._action_event_matches(event, descriptor):
                    continue

                original = descriptor["get"]()
                updated = self._apply_action_value(event, original, descriptor["target_key"], step)
                descriptor["set"](updated)
                mode = "dropout" if event.mode == "dropout" else event.mode
                self._record_application(event, "action", descriptor, mode=mode)

        return actions

    def adjust_observation_space(self, observation_space: Any) -> Any:
        """Describe configured corruptions without changing sensor values."""

        from citylearn.internal.observation_contract import configuration
        contract = configuration(self.env)
        if contract['mode'] == 'hidden_faults':
            return self._adjust_space_bounds(observation_space, -np.inf, np.inf)
        if not self.enabled:
            return observation_space
        from citylearn.internal.robustness_spaces import adjusted_space
        return adjusted_space(self, observation_space)

    def audit_summary(self):
        from citylearn.internal.robustness_audit import summary
        return summary(self)

    def _target_validator(self):
        if self._declared_target_validator is None:
            from citylearn.internal.robustness_targets import declared_target_view
            self._declared_target_validator = declared_target_view(self)
        return self._declared_target_validator

    def summarize(self, building_names: Sequence[str], *, executed_only: bool = False) -> Tuple[Mapping[str, Mapping[str, float]], Mapping[str, float]]:
        return self._history.summary(
            [str(name) for name in building_names],
            executed_before=self._global_time_step() if executed_only else None,
        )

    def validate_targets(self):
        """Validate enabled events against the current flat/entity layout."""
        from citylearn.internal.observation_contract import validate
        validate(self)

        if not self.enabled:
            return

        signature = self._layout_signature()
        if self._validated_layout_signature == signature:
            return

        for event in self._events:
            if not self._module_enabled(event.module):
                continue
            if not self._event_has_target(event):
                if self.env.topology_mode == "dynamic":
                    if self._target_validator()._event_has_target(event):
                        continue
                raise ValueError(
                    "robustness event "
                    f"'{event.event_id}' target does not match any declared {event.module} target."
                )

        self._validated_layout_signature = signature

    def _configure(self):
        schema = self.env.schema if isinstance(self.env.schema, Mapping) else {}
        config = schema.get("robustness", {}) if isinstance(schema, Mapping) else {}
        if not isinstance(config, Mapping):
            config = {}

        self.enabled = parse_bool(config.get("enabled", False), default=False, path="robustness.enabled")
        self.events_file = config.get("events_file")
        seed = config.get("random_seed")
        if seed is None:
            seed = getattr(self.env, "random_seed", None)
        self.random_seed = self._int_required(
            0 if seed is None else seed, path="robustness.random_seed"
        )
        replacement = config.get("missing_replacement_value")
        self.missing_replacement_value = self._finite_float(
            self.DEFAULT_MISSING_REPLACEMENT_VALUE if replacement is None else replacement,
            path="robustness.missing_replacement_value",
        )

        raw_modules = config.get("modules", {}) if isinstance(config, Mapping) else {}
        if not isinstance(raw_modules, Mapping):
            raw_modules = {}

        for plural in self.modules_enabled:
            value = raw_modules.get(plural, {"enabled": True})
            if isinstance(value, Mapping):
                value = value.get("enabled", True)
            self.modules_enabled[plural] = parse_bool(value, default=True, path=f"robustness.modules.{plural}.enabled")

        if not self.enabled:
            for key in self.modules_enabled:
                self.modules_enabled[key] = False

    def _parse_events(self, frame: pd.DataFrame) -> List[RobustnessEvent]:
        missing = REQUIRED_EVENT_COLUMNS.difference(set(frame.columns))
        if missing:
            raise ValueError(f"robustness.events_file is missing columns: {sorted(missing)}.")

        events: List[RobustnessEvent] = []
        event_ids = set()
        for order, row in frame.reset_index(drop=True).iterrows():
            event_id = str(row["event_id"]).strip()
            if self._parameter_missing(row["event_id"]) or event_id.lower() == "nan":
                raise ValueError(f"robustness event at row {order} has an empty event_id.")
            if event_id in event_ids:
                raise ValueError(f"robustness event '{event_id}'.event_id must be unique (duplicate at row {order}).")
            event_ids.add(event_id)
            event_path = f"robustness event '{event_id}'"

            module = str(row["module"]).strip().lower()
            if module not in self.MODULE_ALIASES:
                raise ValueError(f"robustness event '{event_id}' module must be one of {sorted(self.MODULE_ALIASES)}.")

            target_type = str(row["target_type"]).strip().lower()
            if target_type not in self.VALID_TARGET_TYPES:
                raise ValueError(f"robustness event '{event_id}' target_type must be one of {sorted(self.VALID_TARGET_TYPES)}.")

            target_id = str(row["target_id"]).strip()
            if target_id == "" or target_id.lower() == "nan":
                target_id = "*"

            target_feature = str(row["target_feature"]).strip()
            if target_feature == "" or target_feature.lower() == "nan":
                target_feature = "*"
            target_feature = target_feature.lower()

            start = self._int_required(row["start_time_step"], path=f"robustness event '{event_id}'.start_time_step")
            end = self._int_required(row["end_time_step"], path=f"robustness event '{event_id}'.end_time_step")
            if start < 0:
                raise ValueError(f"{event_path}.start_time_step must be non-negative.")
            if end < 0:
                raise ValueError(f"{event_path}.end_time_step must be non-negative.")
            if end < start:
                raise ValueError(f"{event_path}.end_time_step cannot be earlier than start_time_step.")

            mode = str(row["mode"]).strip().lower()
            if mode not in self.VALID_MODES[module]:
                raise ValueError(
                    f"robustness event '{event_id}' mode must be one of {sorted(self.VALID_MODES[module])} "
                    f"for module '{module}'."
                )

            raw_event_domain = row.get("event_domain")
            if raw_event_domain is None or str(raw_event_domain).strip().lower() in {"", "nan"}:
                event_domain = self._default_event_domain(module, mode)
            else:
                event_domain = str(raw_event_domain).strip().upper()
            if event_domain not in self.VALID_EVENT_DOMAINS:
                raise ValueError(
                    f"robustness event '{event_id}' event_domain must be one of "
                    f"{sorted(self.VALID_EVENT_DOMAINS)}."
                )
            self._validate_event_domain(
                event_id=event_id,
                module=module,
                mode=mode,
                event_domain=event_domain,
            )

            raw_delay = row.get("delay_steps")
            delay_steps = 1 if self._parameter_missing(raw_delay) else self._int_required(
                raw_delay, path=f"{event_path}.delay_steps"
            )
            if delay_steps < 1:
                raise ValueError(f"{event_path}.delay_steps must be a positive integer.")

            parameters = {
                name: self._optional_float(row.get(name), path=f"{event_path}.{name}")
                for name in ("value", "std", "min_value", "max_value", "replacement_value")
            }
            if parameters["std"] is not None and parameters["std"] < 0.0:
                raise ValueError(f"{event_path}.std must be non-negative.")
            if (
                parameters["min_value"] is not None
                and parameters["max_value"] is not None
                and parameters["min_value"] > parameters["max_value"]
            ):
                raise ValueError(f"{event_path}.max_value cannot be less than min_value.")

            events.append(
                RobustnessEvent(
                    event_id=event_id,
                    module=module,
                    target_type=target_type,
                    target_id=target_id,
                    target_feature=target_feature,
                    start_time_step=start,
                    end_time_step=end,
                    mode=mode,
                    event_domain=event_domain,
                    **parameters,
                    delay_steps=delay_steps,
                    order=int(order),
                )
            )

        return sorted(events, key=lambda item: (item.start_time_step, item.end_time_step, item.order))

    @staticmethod
    def _default_event_domain(module: str, mode: str) -> str:
        if module == "asset":
            return "ASSET_AVAILABILITY"
        if module == "action" and mode in {"dropout", "delay", "stuck"}:
            return "ACTUATOR_CHANNEL"
        return "VALUE_QUALITY"

    @staticmethod
    def _validate_event_domain(*, event_id: str, module: str, mode: str, event_domain: str) -> None:
        if event_domain == "ASSET_CONNECTION":
            raise ValueError(
                f"robustness event '{event_id}' cannot declare ASSET_CONNECTION; "
                "asset connection is reported from actual entity relations."
            )
        allowed_modules = {
            "ASSET_CONNECTION": set(),
            "ASSET_AVAILABILITY": {"asset"},
            "SENSOR_CHANNEL": {"observation", "forecast"},
            "ACTUATOR_CHANNEL": {"action"},
            "COMMUNICATION_LINK": {"observation", "forecast"},
            "VALUE_QUALITY": {"observation", "forecast", "action"},
        }
        if module not in allowed_modules[event_domain]:
            raise ValueError(
                f"robustness event '{event_id}' event_domain='{event_domain}' "
                f"is incompatible with module='{module}'."
            )
        loss_modes = {
            "SENSOR_CHANNEL": {"missing", "stuck"},
            "ACTUATOR_CHANNEL": {"dropout", "delay", "stuck"},
            "COMMUNICATION_LINK": {"missing", "stuck"},
            "ASSET_AVAILABILITY": {"unavailable"},
            "ASSET_CONNECTION": {"unavailable"},
        }
        if event_domain in loss_modes and mode not in loss_modes[event_domain]:
            raise ValueError(
                f"robustness event '{event_id}' mode='{mode}' is incompatible "
                f"with event_domain='{event_domain}'."
            )

    def _runtime_event_record(self, event: RobustnessEvent, step: int) -> Mapping[str, Any]:
        return {
            "event_id": event.event_id,
            "event_domain": event.event_domain,
            "fault_mode": event.mode,
            "target_type": event.target_type,
            "target_id": event.target_id,
            "target_feature": event.target_feature,
            "start_time_step": int(event.start_time_step),
            "end_time_step": int(event.end_time_step),
            "active_duration_steps": max(int(step) - int(event.start_time_step) + 1, 0),
        }

    def _resolved_runtime_status_records(
        self,
        event: RobustnessEvent,
        step: int,
    ) -> List[Mapping[str, Any]]:
        descriptors: List[Mapping[str, Any]] = []
        if event.module in {"observation", "forecast"}:
            specs = self.env.entity_specs
            table_spec = specs.get("tables", {}).get(event.target_type, {})
            ids = list(table_spec.get("ids", []))
            features = list(table_spec.get("features", []))
            for row_index in self._matching_entity_rows(event, event.target_type, ids):
                for feature_index in self._matching_feature_indices(event, features):
                    if feature_index >= len(features):
                        continue
                    descriptors.append(
                        self._entity_observation_descriptor(
                            event.target_type,
                            ids,
                            row_index,
                            features[feature_index],
                        )
                    )
        elif event.module in {"action", "asset"}:
            descriptors = [
                descriptor
                for descriptor in self._validation_action_descriptors()
                if (
                    self._action_event_matches(event, descriptor)
                    if event.module == "action"
                    else self._asset_control_event_matches(event, descriptor)
                )
            ]
            if event.module == "asset" and not descriptors:
                specs = self.env.entity_specs
                table_spec = specs.get("tables", {}).get(event.target_type, {})
                ids = list(table_spec.get("ids", []))
                for row_index in self._matching_entity_rows(event, event.target_type, ids):
                    descriptors.append(
                        self._entity_observation_descriptor(
                            event.target_type,
                            ids,
                            row_index,
                            event.target_feature,
                        )
                    )

        status = self._runtime_quality_fields(event, step)
        records: List[Mapping[str, Any]] = []
        seen = set()
        for descriptor in descriptors:
            target_id = str(descriptor.get("global_id") or descriptor.get("target_id") or "")
            target_feature = str(descriptor.get("target_feature") or event.target_feature)
            key = (target_id, target_feature)
            if key in seen:
                continue
            seen.add(key)
            records.append(
                {
                    "event_id": event.event_id,
                    "event_ids": [event.event_id],
                    "event_domain": event.event_domain,
                    "fault_mode": event.mode,
                    "target_type": str(descriptor.get("target_type") or event.target_type),
                    "target_id": target_id,
                    "target_feature": target_feature,
                    "building_id": descriptor.get("building"),
                    **status,
                }
            )
        return records

    @staticmethod
    def _runtime_quality_fields(event: RobustnessEvent, step: int) -> Mapping[str, Any]:
        unavailable = event.mode in {"missing", "dropout", "unavailable"}
        if event.mode == "stuck":
            last_fresh = int(event.start_time_step)
        elif event.mode == "delay":
            last_fresh = max(int(step) - max(int(event.delay_steps), 1), 0)
        elif unavailable or event.mode in {"noise", "bias", "clip"}:
            last_fresh = max(int(event.start_time_step) - 1, 0)
        else:
            last_fresh = int(step)
        last_update = max(int(event.start_time_step) - 1, 0) if unavailable else int(step)
        return {
            "availability": "UNAVAILABLE" if unavailable else "AVAILABLE",
            "connection": "NOT_APPLICABLE",
            "quality": "INVALID" if unavailable else "IMPAIRED",
            "last_update_time_step": last_update,
            "last_fresh_time_step": last_fresh,
            "age_steps": max(int(step) - last_fresh, 0),
        }

    def _active_events(self, global_time_step: int) -> List[RobustnessEvent]:
        if not self.enabled or len(self._events) == 0:
            return []

        t = int(global_time_step)
        if self._active_cache_step == t:
            return list(self._active_cache)

        if self._active_cache_step is not None and t < self._active_cache_step:
            self._cursor = 0
            self._active_cache = []

        active = [
            event for event in self._active_cache
            if event.end_time_step >= t
        ]

        while self._cursor < len(self._events) and self._events[self._cursor].start_time_step <= t:
            event = self._events[self._cursor]
            if event.end_time_step >= t:
                active.append(event)
            self._cursor += 1

        active.sort(key=lambda item: item.order)
        self._active_cache_step = t
        self._active_cache = active
        return list(active)

    def _apply_flat_observation_events(self, observations: Any, events: Sequence[RobustnessEvent], step: int):
        layout = self._flat_observation_layout()
        if not isinstance(observations, list):
            return

        for event in events:
            for agent_index, agent_observations in enumerate(observations):
                if agent_index >= len(layout):
                    continue
                if not isinstance(agent_observations, list):
                    continue
                for feature_index, descriptor in enumerate(layout[agent_index]):
                    if feature_index >= len(agent_observations):
                        continue
                    if not self._observation_event_matches(event, descriptor):
                        continue
                    original = float(agent_observations[feature_index])
                    updated = self._apply_observation_value(event, original, descriptor["target_key"], step)
                    agent_observations[feature_index] = updated
                    kind = "forecast" if event.module == "forecast" else "observation"
                    if event.module == "asset":
                        kind = "observation"
                        self._record_application(event, "asset", descriptor, mode="unavailable")
                    self._record_application(event, kind, descriptor, mode=event.mode)

    def _apply_entity_observation_events(self, payload: Mapping[str, Any], events: Sequence[RobustnessEvent], step: int):
        tables = payload.get("tables", {}) if isinstance(payload, Mapping) else {}
        if not isinstance(tables, Mapping):
            return

        specs = self.env.entity_specs
        for event in events:
            table_name = event.target_type
            if table_name not in tables or table_name not in specs.get("tables", {}):
                continue

            table = tables[table_name]
            if not isinstance(table, np.ndarray) or table.ndim != 2:
                continue

            table_spec = specs["tables"][table_name]
            features = list(table_spec.get("features", []))
            ids = list(table_spec.get("ids", []))
            row_indices = self._matching_entity_rows(event, table_name, ids)
            if not row_indices:
                continue

            if event.module == "asset":
                feature_indices = list(range(len(features)))
            else:
                feature_indices = self._matching_feature_indices(event, features)
            if not feature_indices:
                continue

            for row_index in row_indices:
                for feature_index in feature_indices:
                    if row_index >= table.shape[0] or feature_index >= table.shape[1]:
                        continue
                    feature = features[feature_index]
                    descriptor = self._entity_observation_descriptor(table_name, ids, row_index, feature)
                    if event.module in {"observation", "forecast"} and not self._observation_feature_allowed(event, feature):
                        continue
                    original = float(table[row_index, feature_index])
                    updated = self._apply_observation_value(event, original, descriptor["target_key"], step)
                    table[row_index, feature_index] = updated
                    kind = "forecast" if event.module == "forecast" else "observation"
                    if event.module == "asset":
                        kind = "observation"
                        self._record_application(event, "asset", descriptor, mode="unavailable")
                    self._record_application(event, kind, descriptor, mode=event.mode)

    def _apply_observation_value(self, event: RobustnessEvent, original: float, target_key: str, step: int) -> float:
        if event.module == "asset":
            return self._event_replacement_value(event)

        if event.mode == "missing":
            return self._event_replacement_value(event)
        if event.mode == "noise":
            std = 0.0 if event.std is None else float(event.std)
            return float(original) + float(self._noise(event, target_key, step, std))
        if event.mode == "bias":
            return float(original) + (0.0 if event.value is None else float(event.value))
        if event.mode == "stuck":
            key = (event.event_id, target_key)
            if key not in self._stuck_values:
                self._stuck_values[key] = float(original)
            return self._stuck_values[key]
        if event.mode == "clip":
            low = -np.inf if event.min_value is None else float(event.min_value)
            high = np.inf if event.max_value is None else float(event.max_value)
            return float(np.clip(original, low, high))

        return float(original)

    def _apply_action_value(self, event: RobustnessEvent, original: float, target_key: str, step: int) -> float:
        if event.mode == "dropout":
            return 0.0
        if event.mode == "noise":
            std = 0.0 if event.std is None else float(event.std)
            return float(original) + float(self._noise(event, target_key, step, std))
        if event.mode == "bias":
            return float(original) + (0.0 if event.value is None else float(event.value))
        if event.mode == "stuck":
            key = (event.event_id, target_key)
            if key not in self._stuck_values:
                self._stuck_values[key] = float(original)
            return self._stuck_values[key]
        if event.mode == "delay":
            history = self._action_history.get(target_key, [])
            target_step = int(step) - max(int(event.delay_steps), 1)
            candidates = [value for t, value in history if t <= target_step]
            return float(candidates[-1]) if candidates else 0.0
        if event.mode == "clip":
            low = -np.inf if event.min_value is None else float(event.min_value)
            high = np.inf if event.max_value is None else float(event.max_value)
            return float(np.clip(original, low, high))

        return float(original)

    def _flat_observation_layout(self) -> List[List[Mapping[str, Any]]]:
        signature = self._layout_signature()
        if self._flat_layout_cache is not None and self._flat_layout_cache[0] == signature:
            return self._flat_layout_cache[1]

        env = self.env
        shared = set(getattr(env, "shared_observations", []) or [])
        layout: List[List[Mapping[str, Any]]] = []

        if env.central_agent:
            agent_layout: List[Mapping[str, Any]] = []
            seen_shared = set()
            for building in env.buildings:
                for feature in building.active_observations:
                    if feature in shared and feature in seen_shared:
                        continue
                    is_shared = feature in shared
                    target_type = "district" if is_shared else "building"
                    target_id = "District" if is_shared else building.name
                    building_name = None if is_shared else building.name
                    agent_layout.append(
                        self._observation_descriptor(target_type, target_id, feature, building_name=building_name)
                    )
                    if is_shared:
                        seen_shared.add(feature)
            layout.append(agent_layout)
        else:
            for building in env.buildings:
                agent_layout = []
                for feature in building.active_observations:
                    is_shared = feature in shared
                    target_type = "district" if is_shared else "building"
                    target_id = "District" if is_shared else building.name
                    building_name = None if is_shared else building.name
                    agent_layout.append(
                        self._observation_descriptor(target_type, target_id, feature, building_name=building_name)
                    )
                layout.append(agent_layout)

        self._flat_layout_cache = (signature, layout)
        return layout

    def _action_descriptors(self, actions: Sequence[Mapping[str, Any]]) -> List[Mapping[str, Any]]:
        descriptors: List[Mapping[str, Any]] = []

        for building_index, action_dict in enumerate(actions):
            if building_index >= len(self.env.buildings) or not isinstance(action_dict, Mapping):
                continue

            building = self.env.buildings[building_index]
            mutable = action_dict

            for key, value in list(mutable.items()):
                if not key.endswith("_action"):
                    continue
                feature = key[:-len("_action")]

                def getter(container=mutable, action_key=key):
                    return float(container.get(action_key, 0.0))

                def setter(updated, container=mutable, action_key=key):
                    container[action_key] = float(updated)

                target_type = "storage" if feature == "electrical_storage" else "building"
                target_id = building.name
                descriptors.append(
                    {
                        "target_type": target_type,
                        "target_id": target_id,
                        "target_feature": feature,
                        "building": building.name,
                        "raw_id": feature,
                        "global_id": f"{building.name}/{feature}" if target_type == "storage" else building.name,
                        "target_key": f"{target_type}:{target_id}:{feature}",
                        "get": getter,
                        "set": setter,
                    }
                )

            ev_actions = mutable.get("electric_vehicle_storage_actions", {})
            if isinstance(ev_actions, Mapping):
                for charger_id in list(ev_actions.keys()):
                    def getter(container=ev_actions, action_key=charger_id):
                        return float(container.get(action_key, 0.0))

                    def setter(updated, container=ev_actions, action_key=charger_id):
                        container[action_key] = float(updated)

                    descriptors.append(
                        {
                            "target_type": "charger",
                            "target_id": str(charger_id),
                            "target_feature": "electric_vehicle_storage",
                            "building": building.name,
                            "raw_id": str(charger_id),
                            "global_id": f"{building.name}/{charger_id}",
                            "target_key": f"charger:{building.name}:{charger_id}:electric_vehicle_storage",
                            "get": getter,
                            "set": setter,
                        }
                    )

            deferrable_actions = mutable.get("deferrable_appliance_actions", {})
            if isinstance(deferrable_actions, Mapping):
                for action_name in list(deferrable_actions.keys()):
                    appliance_id = str(action_name).replace("deferrable_appliance_", "")

                    def getter(container=deferrable_actions, action_key=action_name):
                        return float(container.get(action_key, 0.0))

                    def setter(updated, container=deferrable_actions, action_key=action_name):
                        container[action_key] = float(updated)

                    descriptors.append(
                        {
                            "target_type": "deferrable_appliance",
                            "target_id": appliance_id,
                            "target_feature": "start",
                            "building": building.name,
                            "raw_id": appliance_id,
                            "global_id": f"{building.name}/{appliance_id}",
                            "target_key": f"deferrable_appliance:{building.name}:{appliance_id}:start",
                            "get": getter,
                            "set": setter,
                        }
                    )

        return descriptors

    def _event_has_target(self, event: RobustnessEvent) -> bool:
        if event.module in {"observation", "forecast"}:
            if getattr(self.env, "interface", "flat") == "entity":
                specs = self.env.entity_specs
                table_spec = specs.get("tables", {}).get(event.target_type)
                if not table_spec:
                    return False
                ids = list(table_spec.get("ids", []))
                features = list(table_spec.get("features", []))
                return bool(self._matching_entity_rows(event, event.target_type, ids)) and bool(
                    self._matching_feature_indices(event, features)
                )
            return any(
                self._observation_event_matches(event, descriptor)
                for agent_layout in self._flat_observation_layout()
                for descriptor in agent_layout
            )

        if event.module == "asset" and event.target_feature in self.TELEMETRY_FEATURES:
            if getattr(self.env, "interface", "flat") == "entity":
                specs = self.env.entity_specs
                table_spec = specs.get("tables", {}).get(event.target_type)
                if not table_spec:
                    return False
                return bool(self._matching_entity_rows(event, event.target_type, list(table_spec.get("ids", []))))
            if event.target_type in {"building", "district"}:
                return any(
                    self._observation_event_matches(event, descriptor)
                    for agent in self._flat_observation_layout() for descriptor in agent
                )

        if event.module == "action":
            descriptors = self._validation_action_descriptors()
            return any(self._action_event_matches(event, descriptor) for descriptor in descriptors)

        if event.module == "asset" and event.target_feature in self.CONTROL_FEATURES:
            descriptors = self._validation_action_descriptors()
            return any(self._asset_control_event_matches(event, descriptor) for descriptor in descriptors)

        return False

    def _validation_action_descriptors(self) -> List[Mapping[str, Any]]:
        zero_actions = []
        for building in self.env.buildings:
            action_dict = {}
            ev_actions = {}
            deferrable_actions = {}
            for action_name in building.active_actions:
                if action_name.startswith("electric_vehicle_storage_"):
                    ev_actions[action_name.replace("electric_vehicle_storage_", "")] = 0.0
                elif action_name.startswith("deferrable_appliance_"):
                    deferrable_actions[action_name] = 0.0
                else:
                    action_dict[f"{action_name}_action"] = 0.0
            if ev_actions:
                action_dict["electric_vehicle_storage_actions"] = ev_actions
            if deferrable_actions:
                action_dict["deferrable_appliance_actions"] = deferrable_actions
            zero_actions.append(action_dict)
        return self._action_descriptors(zero_actions)

    def _observation_event_matches(self, event: RobustnessEvent, descriptor: Mapping[str, Any]) -> bool:
        if event.module == "asset":
            if event.mode != "unavailable" or event.target_feature not in self.TELEMETRY_FEATURES:
                return False
            return self._target_matches(event, descriptor)

        if not self._observation_feature_allowed(event, descriptor["target_feature"]):
            return False
        return self._target_matches(event, descriptor)

    def _action_event_matches(self, event: RobustnessEvent, descriptor: Mapping[str, Any]) -> bool:
        if event.module != "action":
            return False
        if not self._target_matches(event, descriptor):
            return False
        return self._feature_matches(event.target_feature, descriptor["target_feature"])

    def _asset_control_event_matches(self, event: RobustnessEvent, descriptor: Mapping[str, Any]) -> bool:
        if event.module != "asset" or event.mode != "unavailable" or event.target_feature not in self.CONTROL_FEATURES:
            return False
        return self._target_matches(event, descriptor)

    def _target_matches(self, event: RobustnessEvent, descriptor: Mapping[str, Any]) -> bool:
        descriptor_type = str(descriptor.get("target_type", "")).lower()
        if event.target_type != descriptor_type:
            if event.target_type == "building" and descriptor.get("building") == event.target_id:
                return True
            return False

        if event.target_id == "*":
            return True

        candidate_ids = {
            str(descriptor.get("target_id", "")),
            str(descriptor.get("building", "")),
            str(descriptor.get("raw_id", "")),
            str(descriptor.get("global_id", "")),
        }
        if event.target_type == "district":
            candidate_ids.update({"District", "district_0", "district"})

        return event.target_id in candidate_ids

    @staticmethod
    def _feature_matches(event_feature: str, candidate: str) -> bool:
        if event_feature in {"", "*"}:
            return True
        event_feature = str(event_feature).replace("_action", "")
        candidate = str(candidate).replace("_action", "")
        return event_feature == candidate

    def _observation_feature_allowed(self, event: RobustnessEvent, feature: str) -> bool:
        is_forecast = self._is_forecast_feature(feature)
        if event.module == "forecast" and not is_forecast:
            return False
        if event.module == "observation" and is_forecast:
            return False
        return self._feature_matches(event.target_feature, feature)

    @staticmethod
    def _is_forecast_feature(feature: str) -> bool:
        feature = str(feature)
        return "_predicted_" in feature or feature.startswith("forecast_")

    def _matching_entity_rows(self, event: RobustnessEvent, table_name: str, ids: Sequence[str]) -> List[int]:
        if event.target_id == "*":
            return list(range(len(ids)))
        rows = []
        for idx, entity_id in enumerate(ids):
            descriptor = self._entity_observation_descriptor(table_name, ids, idx, "*")
            if self._target_matches(event, descriptor):
                rows.append(idx)
        return rows

    def _matching_feature_indices(self, event: RobustnessEvent, features: Sequence[str]) -> List[int]:
        return [
            idx for idx, feature in enumerate(features)
            if self._observation_feature_allowed(event, feature)
        ]

    def _entity_observation_descriptor(self, table_name: str, ids: Sequence[str], row_index: int, feature: str) -> Mapping[str, Any]:
        entity_id = str(ids[row_index]) if row_index < len(ids) else ""
        building = self._building_for_entity(table_name, entity_id)
        raw_id = entity_id.split(":")[-1] if ":" in entity_id else entity_id
        return self._observation_descriptor(
            table_name,
            entity_id,
            feature,
            building_name=building,
            raw_id=raw_id,
            global_id=entity_id,
        )

    def _observation_descriptor(
        self,
        target_type: str,
        target_id: str,
        feature: str,
        *,
        building_name: Optional[str] = None,
        raw_id: str = "",
        global_id: str = "",
    ) -> Mapping[str, Any]:
        return {
            "target_type": str(target_type),
            "target_id": str(target_id),
            "target_feature": str(feature),
            "building": building_name,
            "raw_id": raw_id,
            "global_id": global_id,
            "target_key": f"{target_type}:{target_id}:{feature}",
        }

    def _building_for_entity(self, table_name: str, entity_id: str) -> Optional[str]:
        if table_name == "building":
            return entity_id
        raw = str(entity_id)
        if "/" in raw:
            return raw.split("/", 1)[0]
        parts = raw.split(":")
        if len(parts) >= 2:
            return parts[1]
        return None

    def _record_application(self, event: RobustnessEvent, kind: str, descriptor: Mapping[str, Any], *, mode: str):
        step = self._global_time_step()
        record = self._history.writable_record(step)
        target_key = str(descriptor.get("target_key", ""))
        if kind == "asset":
            # An availability event is applied to every observation field and
            # control port of the affected asset.  Those field-level effects
            # remain separate observation/action corruption records, but the
            # asset-time KPI must count the physical entity once per step.
            asset_identity = str(
                descriptor.get("global_id")
                or descriptor.get("raw_id")
                or descriptor.get("target_id")
                or target_key
            )
            application_key = f"{event.event_id}:{kind}:{asset_identity}"
        else:
            application_key = f"{event.event_id}:{kind}:{target_key}"
        already_recorded = application_key in record.get(kind, set())
        record["event_ids"].add(event.event_id)
        record["modules"].add(event.module)
        if kind in {"observation", "forecast", "action", "asset"}:
            record[kind].add(application_key)
        if mode == "missing" or (event.module == "asset" and kind == "observation"):
            record["missing"].add(application_key)
        if mode == "dropout" or (event.module == "asset" and kind == "action"):
            record["dropout"].add(application_key)
        if already_recorded:
            return
        record["applications"].append(
            {
                "event_id": event.event_id,
                "module": event.module,
                "kind": kind,
                "mode": mode,
                "target_key": target_key,
                "building": descriptor.get("building"),
            }
        )

    def _counts_for_step(self, step: int) -> Mapping[str, int]:
        return self._history.counts(int(step))

    def _accumulate_summary_sets(self, target: Dict[str, float], record: Mapping[str, Any]):
        target["robustness_observation_corruption_count"] += float(len(record.get("observation", set())))
        target["robustness_forecast_corruption_count"] += float(len(record.get("forecast", set())))
        target["robustness_action_corruption_count"] += float(len(record.get("action", set())))
        target["robustness_asset_unavailable_time_step_count"] += float(len(record.get("asset", set())))
        target["robustness_missing_observation_count"] += float(len(record.get("missing", set())))
        target["robustness_action_dropout_count"] += float(len(record.get("dropout", set())))

    @staticmethod
    def _accumulate_building_application(target: Dict[str, float], application: Mapping[str, Any]):
        kind = application.get("kind")
        mode = application.get("mode")
        if kind == "observation":
            target["robustness_observation_corruption_count"] += 1.0
        elif kind == "forecast":
            target["robustness_forecast_corruption_count"] += 1.0
        elif kind == "action":
            target["robustness_action_corruption_count"] += 1.0
        elif kind == "asset":
            target["robustness_asset_unavailable_time_step_count"] += 1.0
        if mode == "missing" or (application.get("module") == "asset" and kind == "observation"):
            target["robustness_missing_observation_count"] += 1.0
        if mode == "dropout" or (application.get("module") == "asset" and kind == "action"):
            target["robustness_action_dropout_count"] += 1.0

    @classmethod
    def _empty_summary(cls) -> Dict[str, float]:
        return {key: 0.0 for key in cls.KPI_KEYS}

    @staticmethod
    def _record_has_any_application(record: Mapping[str, Any]) -> bool:
        return any(
            len(record.get(key, set())) > 0
            for key in ("observation", "forecast", "action", "asset")
        )

    @staticmethod
    def _public_record(record: Mapping[str, Any]) -> Mapping[str, Any]:
        result = {}
        for key in record:
            if key == "applications":
                continue
            value = record[key]
            result[key] = sorted(value) if isinstance(value, set) else value
        result["applications"] = list(record.get("applications", []))
        return result

    def _zero_observation_values(self) -> Mapping[str, float]:
        return {
            "robustness_active": 0.0,
            "robustness_observation_corruption_count_previous": 0.0,
            "robustness_forecast_corruption_count_previous": 0.0,
            "robustness_action_corruption_count_previous": 0.0,
            "robustness_asset_unavailable_count": 0.0,
        }

    def _append_action_history(self, target_key: str, step: int, value: float):
        history = self._action_history.setdefault(target_key, [])
        if history and history[-1][0] == int(step):
            history[-1] = (int(step), float(value))
        else:
            history.append((int(step), float(value)))
        max_len = max(self._max_delay_steps + 2, 3)
        if len(history) > max_len:
            del history[:-max_len]

    def _noise(self, event: RobustnessEvent, target_key: str, step: int, std: float) -> float:
        if std == 0.0:
            return 0.0
        payload = f"{self.random_seed}:{event.event_id}:{step}:{target_key}".encode("utf-8")
        seed = int.from_bytes(hashlib.sha256(payload).digest()[:4], "little")
        return float(np.random.RandomState(seed).normal(0.0, std))

    def _event_replacement_value(self, event: RobustnessEvent) -> float:
        if event.replacement_value is not None and np.isfinite(event.replacement_value):
            return float(event.replacement_value)
        return float(self.missing_replacement_value)

    def _module_enabled(self, module: str) -> bool:
        return bool(self.modules_enabled.get(self.MODULE_ALIASES.get(module, module), False))

    def _global_time_step(self) -> int:
        start = int(getattr(getattr(self.env, "episode_tracker", None), "episode_start_time_step", 0) or 0)
        return start + int(getattr(self.env, "time_step", 0) or 0)

    def _layout_signature(self):
        building_names = tuple(building.name for building in getattr(self.env, "buildings", []))
        action_names = tuple(tuple(building.active_actions) for building in getattr(self.env, "buildings", []))
        observation_names = tuple(tuple(building.active_observations) for building in getattr(self.env, "buildings", []))
        topology_version = int(getattr(self.env, "topology_version", 0) or 0)
        return building_names, action_names, observation_names, topology_version, getattr(self.env, "interface", "flat")

    @staticmethod
    def _adjust_space_bounds(space: Any, low_value: float, high_value: float):
        if isinstance(space, list):
            return [CityLearnRobustnessService._adjust_space_bounds(item, low_value, high_value) for item in space]

        if isinstance(space, spaces.Dict):
            if "tables" in space.spaces and "edges" in space.spaces:
                return spaces.Dict(
                    {
                        key: (
                            CityLearnRobustnessService._adjust_space_bounds(value, low_value, high_value)
                            if key == "tables"
                            else value
                        )
                        for key, value in space.spaces.items()
                    }
                )
            return spaces.Dict(
                {
                    key: CityLearnRobustnessService._adjust_space_bounds(value, low_value, high_value)
                    for key, value in space.spaces.items()
                }
            )

        if isinstance(space, spaces.Box) and np.issubdtype(space.dtype, np.floating):
            low = np.minimum(space.low, low_value).astype(space.dtype)
            high = np.maximum(space.high, high_value).astype(space.dtype)
            return spaces.Box(low=low, high=high, dtype=space.dtype)

        return space

    @staticmethod
    def _parameter_missing(value: Any) -> bool:
        if isinstance(value, str):
            return value.strip() == ""
        return value is None or (pd.api.types.is_scalar(value) and bool(pd.isna(value)))

    @classmethod
    def _optional_float(cls, value: Any, *, path: str) -> Optional[float]:
        if cls._parameter_missing(value):
            return None
        return cls._finite_float(value, path=path)

    @staticmethod
    def _finite_float(value: Any, *, path: str) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"{path} must be a finite number when supplied.") from exc
        if isinstance(value, (bool, np.bool_)) or not np.isfinite(parsed):
            raise ValueError(f"{path} must be a finite number when supplied.")
        return parsed

    @staticmethod
    def _int_required(value: Any, *, path: str) -> int:
        try:
            parsed = Decimal(str(value))
        except InvalidOperation as exc:
            raise ValueError(f"{path} must be a finite integer.") from exc
        if not parsed.is_finite() or parsed != parsed.to_integral_value():
            raise ValueError(f"{path} must be a finite integer.")
        return int(parsed)
