from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from citylearn.utilities import parse_bool

if TYPE_CHECKING:
    from citylearn.citylearn import CityLearnEnv


REQUIRED_REQUEST_COLUMNS = {
    "request_id",
    "issuer",
    "direction",
    "start_time_step",
    "end_time_step",
    "target_power_kw",
    "activation_price_eur_per_kwh",
    "shortfall_penalty_eur_per_kwh",
}


@dataclass(frozen=True)
class DemandResponseRequest:
    """Canonical demand-response request loaded from a dataset file."""

    request_id: str
    issuer: str
    direction: str
    start_time_step: int
    end_time_step: int
    target_power_kw: float
    activation_price_eur_per_kwh: float
    shortfall_penalty_eur_per_kwh: float
    tolerance_power_kw: float
    order: int
    purpose: str = 'unspecified'


class CityLearnDemandResponseService:
    """Dataset-driven demand response requests and settlement."""

    ISSUER_CODES = {"dso": 1.0, "tso": 2.0}
    DIRECTION_CODES = {"up": 1.0, "down": -1.0}
    DEFAULT_BASELINE_METHOD = "rolling_pre_event_average"
    DEFAULT_BASELINE_WINDOW_SECONDS = 3600.0

    def __init__(self, env: "CityLearnEnv"):
        self.env = env
        self.enabled = False
        self.requests_file: Optional[str] = None
        self.baseline_method = self.DEFAULT_BASELINE_METHOD
        self.baseline_window_seconds = self.DEFAULT_BASELINE_WINDOW_SECONDS
        self.allow_overlapping_requests = False
        self._requests: List[DemandResponseRequest] = []
        self._cursor = 0
        self._baseline_by_request_id: Dict[str, Mapping[str, Any]] = {}
        self._settlement_by_time_step: Dict[int, Mapping[str, Any]] = {}
        self._last_settlement: Optional[Mapping[str, Any]] = None
        self._configure()

    @property
    def requests(self) -> Sequence[DemandResponseRequest]:
        return tuple(self._requests)

    @property
    def settlement_history(self) -> Sequence[Mapping[str, Any]]:
        return tuple(
            self._settlement_by_time_step[key]
            for key in sorted(self._settlement_by_time_step.keys())
        )

    def initialize(self):
        """Load request definitions after `env.root_directory` is available."""

        if not self.enabled:
            self._requests = []
            return

        if not self.requests_file:
            raise ValueError("demand_response.requests_file is required when demand_response.enabled=true.")

        path = Path(str(self.requests_file)).expanduser()
        if not path.is_absolute():
            path = Path(str(getattr(self.env, "root_directory", "") or "")) / path

        if not path.is_file():
            raise FileNotFoundError(f"demand_response.requests_file does not exist: {path}")

        suffix = path.suffix.lower()
        if suffix in {".parquet", ".pq"}:
            frame = pd.read_parquet(path)
        elif suffix in {".csv", ".txt"}:
            frame = pd.read_csv(path)
        else:
            raise ValueError("demand_response.requests_file must be a CSV or Parquet file.")

        self._requests = self._parse_requests(frame)
        self._validate_overlaps()

    def reset(self):
        """Reset episode-local state without reloading the dataset file."""

        self._cursor = 0
        self._baseline_by_request_id = {}
        self._settlement_by_time_step = {}
        self._last_settlement = None

    def get_metadata(self) -> Mapping[str, Any]:
        return {
            "definition_version": "demand-response-audit-v1",
            "enabled": bool(self.enabled),
            "requests_file": self.requests_file,
            "baseline_method": self.baseline_method,
            "baseline_window_seconds": float(self.baseline_window_seconds),
            "allow_overlapping_requests": bool(self.allow_overlapping_requests),
            "request_count": int(len(self._requests)),
            "baseline_required_steps": self._baseline_window_steps(),
            "effective_baseline_seconds": self._baseline_window_steps()*self._step_hours()*3600.,
            "population_rule": "stable_topology_from_preparation_through_settled_interval",
            "purpose_rule": "explicit_service_stress_or_unspecified; never_inferred_from_shortfall",
            "aggregation": {"signed_delivery_and_cash": "additive", "member_credit": "uncapped_positive_contribution", "member_shortfall": "equal_share_without_district_tolerance; not_additive"},
        }

    def observation_values(self) -> Mapping[str, float]:
        """Return current active DR fields for entity district observations."""

        request = self._active_request_for_current_time()
        if request is None:
            return self._zero_observation_values()

        baseline = self._ensure_baseline(request)
        previous = self._previous_settlement()
        step_hours = self._step_hours()
        global_time_step = self._global_time_step()
        time_remaining_hours = max(request.end_time_step - global_time_step + 1, 0) * step_hours

        return {
            "dr_active": 1.0,
            "dr_issuer_code": float(self.ISSUER_CODES.get(request.issuer, 0.0)),
            "dr_direction": float(self.DIRECTION_CODES.get(request.direction, 0.0)),
            "dr_target_power_kw": float(request.target_power_kw),
            "dr_baseline_power_kw": float(baseline.get("baseline_power_kw", 0.0)) if baseline.get("valid") else 0.0,
            "dr_time_remaining_hours": float(time_remaining_hours),
            "dr_activation_price_eur_per_kwh": float(request.activation_price_eur_per_kwh),
            "dr_shortfall_penalty_eur_per_kwh": float(request.shortfall_penalty_eur_per_kwh),
            "dr_previous_delivered_power_kw": float(previous.get("delivered_power_kw", 0.0)) if previous else 0.0,
            "dr_previous_shortfall_power_kw": float(previous.get("shortfall_power_kw", 0.0)) if previous else 0.0,
        }

    def observation_meta(self) -> Mapping[str, Any]:
        request = self._active_request_for_current_time()
        baseline = self._ensure_baseline(request) if request is not None else None
        return {
            "enabled": bool(self.enabled),
            "active_request_id": None if request is None else request.request_id,
            "active_request": None if request is None else {
                "request_id": request.request_id,
                "issuer": request.issuer,
                "direction": request.direction,
                "start_time_step": request.start_time_step,
                "end_time_step": request.end_time_step,
                "target_power_kw": request.target_power_kw,
            },
            "baseline_valid": bool(baseline.get("valid", False)) if baseline is not None else False,
        }

    def settle_current_time_step(self):
        """Measure and settle the current step after physical variables are updated."""

        if not self.enabled:
            return None

        request = self._active_request_for_current_time()
        if request is None:
            return None

        t = int(getattr(self.env, "time_step", 0))
        baseline = self._ensure_baseline(request)
        row = self._settlement_row(request, baseline)
        self._settlement_by_time_step[t] = row
        self._last_settlement = row
        return row

    def summarize(self, building_names: Sequence[str]) -> Tuple[Mapping[str, Mapping[str, float]], Mapping[str, float]]:
        building_names = [str(name) for name in building_names]
        by_building = {
            name: self._empty_summary()
            for name in building_names
        }
        district = self._empty_summary()
        district_event_ids = set()
        building_event_ids = {name: set() for name in building_names}

        for row in self.settlement_history:
            event_id = str(row.get("request_id", ""))
            if event_id:
                district_event_ids.add(event_id)
            self._accumulate_summary(district, row)

            allocations = row.get("building_allocations", []) or []
            for allocation in allocations:
                name = str(allocation.get("building", ""))
                if name not in by_building:
                    continue
                if event_id:
                    building_event_ids[name].add(event_id)
                self._accumulate_summary(by_building[name], allocation)

        district["demand_response_events_count"] = float(len(district_event_ids))
        self._finalize_summary(district)
        for name, summary in by_building.items():
            summary["demand_response_events_count"] = float(len(building_event_ids.get(name, set())))
            self._finalize_summary(summary)

        return by_building, district

    def _configure(self):
        schema = self.env.schema if isinstance(self.env.schema, Mapping) else {}
        config = schema.get("demand_response", {}) if isinstance(schema, Mapping) else {}
        if not isinstance(config, Mapping):
            config = {}

        self.enabled = parse_bool(
            config.get("enabled", False),
            default=False,
            path="demand_response.enabled",
        )
        if self.enabled and getattr(self.env, "interface", "flat") != "entity":
            raise ValueError("demand_response.enabled=true requires interface='entity'.")

        self.requests_file = config.get("requests_file")
        self.baseline_method = str(config.get("baseline_method", self.DEFAULT_BASELINE_METHOD)).strip().lower()
        if self.baseline_method != self.DEFAULT_BASELINE_METHOD:
            raise ValueError("demand_response.baseline_method must be 'rolling_pre_event_average' in v1.")

        self.baseline_window_seconds = self._non_negative_float(
            config.get("baseline_window_seconds", self.DEFAULT_BASELINE_WINDOW_SECONDS),
            default=self.DEFAULT_BASELINE_WINDOW_SECONDS,
            path="demand_response.baseline_window_seconds",
        )
        self.allow_overlapping_requests = parse_bool(
            config.get("allow_overlapping_requests", False),
            default=False,
            path="demand_response.allow_overlapping_requests",
        )

    def _parse_requests(self, frame: pd.DataFrame) -> List[DemandResponseRequest]:
        missing = REQUIRED_REQUEST_COLUMNS.difference(set(frame.columns))
        if missing:
            raise ValueError(f"demand_response.requests_file is missing columns: {sorted(missing)}.")

        requests: List[DemandResponseRequest] = []
        ids = set()
        purposes = (self.env.schema.get('demand_response') or {}).get('request_purposes') or {}
        for order, row in frame.reset_index(drop=True).iterrows():
            request_id = str(row["request_id"]).strip()
            if request_id == "" or request_id.lower() == "nan":
                raise ValueError(f"demand_response request at row {order} has an empty request_id.")
            if request_id in ids:
                raise ValueError(f"duplicate demand_response request_id: {request_id}; IDs must be unique.")
            ids.add(request_id)
            purpose = purposes.get(request_id, row.get('purpose', 'unspecified'))
            purpose = 'unspecified' if pd.isna(purpose) else str(purpose).strip().lower()
            if purpose not in {'service', 'stress', 'unspecified'}:
                raise ValueError('DR purpose must be service, stress or unspecified.')

            issuer = str(row["issuer"]).strip().lower()
            if issuer not in self.ISSUER_CODES:
                raise ValueError(f"demand_response request '{request_id}' issuer must be one of {sorted(self.ISSUER_CODES)}.")

            direction = str(row["direction"]).strip().lower()
            if direction not in self.DIRECTION_CODES:
                raise ValueError(f"demand_response request '{request_id}' direction must be one of {sorted(self.DIRECTION_CODES)}.")

            start = self._int_value(row["start_time_step"], path=f"demand_response request '{request_id}'.start_time_step")
            end = self._int_value(row["end_time_step"], path=f"demand_response request '{request_id}'.end_time_step")
            if end < start:
                raise ValueError(f"demand_response request '{request_id}' end_time_step cannot be earlier than start_time_step.")

            target_power = self._non_negative_float(row["target_power_kw"], path=f"demand_response request '{request_id}'.target_power_kw")
            activation_price = self._non_negative_float(
                row["activation_price_eur_per_kwh"],
                path=f"demand_response request '{request_id}'.activation_price_eur_per_kwh",
            )
            shortfall_penalty = self._non_negative_float(
                row["shortfall_penalty_eur_per_kwh"],
                path=f"demand_response request '{request_id}'.shortfall_penalty_eur_per_kwh",
            )
            tolerance = self._non_negative_float(
                row.get("tolerance_power_kw", 0.0),
                default=0.0,
                path=f"demand_response request '{request_id}'.tolerance_power_kw",
            )

            requests.append(
                DemandResponseRequest(
                    request_id=request_id,
                    issuer=issuer,
                    direction=direction,
                    start_time_step=start,
                    end_time_step=end,
                    target_power_kw=target_power,
                    activation_price_eur_per_kwh=activation_price,
                    shortfall_penalty_eur_per_kwh=shortfall_penalty,
                    tolerance_power_kw=tolerance,
                    order=int(order),
                    purpose=purpose,
                )
            )

        if set(purposes)-ids:
            raise ValueError('request_purposes references unknown request IDs.')
        return sorted(requests, key=lambda item: (item.start_time_step, item.end_time_step, item.order))

    def _validate_overlaps(self):
        previous: Optional[DemandResponseRequest] = None
        for request in self._requests:
            if previous is not None and request.start_time_step <= previous.end_time_step:
                if self.allow_overlapping_requests:
                    raise NotImplementedError("Overlapping demand_response requests are not supported in v1.")
                raise ValueError(
                    "Overlapping demand_response requests are not allowed when "
                    "demand_response.allow_overlapping_requests=false."
                )
            previous = request

    def _active_request_for_current_time(self) -> Optional[DemandResponseRequest]:
        if not self.enabled or len(self._requests) == 0:
            return None

        global_time_step = self._global_time_step()
        while self._cursor < len(self._requests) and self._requests[self._cursor].end_time_step < global_time_step:
            self._cursor += 1

        if self._cursor >= len(self._requests):
            return None

        request = self._requests[self._cursor]
        if request.start_time_step <= global_time_step <= request.end_time_step:
            return request

        return None

    def _ensure_baseline(self, request: DemandResponseRequest) -> Mapping[str, Any]:
        local_start = request.start_time_step - self._episode_start_time_step()
        window_steps = self._baseline_window_steps()
        start_index = int(local_start) - window_steps
        end_index = int(local_start) - 1

        if local_start < 0 or start_index < 0 or end_index < start_index:
            baseline = self._invalid_baseline()
            self._baseline_by_request_id[request.request_id] = baseline
            return baseline

        topology = getattr(self.env, '_topology_service', None)
        if getattr(self.env, 'topology_mode', 'static') == 'dynamic' and topology is not None:
            versions = {topology.topology_version_at(t) for t in range(start_index, int(self.env.time_step)+1)}
            if len(versions) != 1:
                baseline = self._invalid_baseline('topology_changed')
                self._baseline_by_request_id[request.request_id] = baseline
                return baseline
        cached = self._baseline_by_request_id.get(request.request_id)
        if cached is not None:
            return cached

        building_baselines: Dict[str, float] = {}
        valid = True
        for building in self.env.buildings:
            values = getattr(building, "net_electricity_consumption", [])
            samples = []
            for idx in range(start_index, end_index + 1):
                try:
                    value = float(values[idx])
                except Exception:
                    valid = False
                    break
                if not np.isfinite(value):
                    valid = False
                    break
                samples.append(value)
            if not valid:
                break
            building_baselines[building.name] = float(np.mean(samples)) / self._step_hours()

        if not valid or len(building_baselines) == 0:
            baseline = self._invalid_baseline('nonfinite_history' if not valid else 'no_members')
        else:
            baseline = {
                "valid": True,
                "reason": None,
                "baseline_power_kw": float(sum(building_baselines.values())),
                "building_baseline_power_kw": building_baselines,
                "window_start_time_step": int(start_index),
                "window_end_time_step": int(end_index),
            }

        self._baseline_by_request_id[request.request_id] = baseline
        return baseline

    def _settlement_row(self, request: DemandResponseRequest, baseline: Mapping[str, Any]) -> Mapping[str, Any]:
        t = int(getattr(self.env, "time_step", 0))
        step_hours = self._step_hours()
        requested_kwh = float(request.target_power_kw * step_hours)

        if not baseline.get("valid", False):
            allocations = self._invalid_building_allocations(requested_kwh)
            return {
                "time_step": t,
                "global_time_step": self._global_time_step(),
                "request_id": request.request_id,
                "issuer": request.issuer,
                "direction": request.direction,
                "baseline_valid": False,
                "baseline_reason": baseline.get('reason'),
                "purpose": request.purpose,
                "requested_kwh": requested_kwh,
                "valid_requested_kwh": 0.0,
                "baseline_power_kw": 0.0,
                "actual_power_kw": self._current_district_power_kw(t),
                "delivered_power_kw": 0.0,
                "shortfall_power_kw": 0.0,
                "delivered_kwh": 0.0,
                "credited_kwh": 0.0,
                "shortfall_kwh": 0.0,
                "revenue_eur": 0.0,
                "penalty_eur": 0.0,
                "net_revenue_eur": 0.0,
                "building_allocations": allocations,
            }

        baseline_power = float(baseline.get("baseline_power_kw", 0.0))
        actual_power = self._current_district_power_kw(t)
        delivered_power = (
            actual_power - baseline_power
            if request.direction == "up"
            else baseline_power - actual_power
        )
        shortfall_power = max(request.target_power_kw - delivered_power - request.tolerance_power_kw, 0.0)
        credited_power = min(max(delivered_power, 0.0), request.target_power_kw)
        delivered_kwh = delivered_power * step_hours
        credited_kwh = credited_power * step_hours
        shortfall_kwh = shortfall_power * step_hours
        revenue = credited_kwh * request.activation_price_eur_per_kwh
        penalty = shortfall_kwh * request.shortfall_penalty_eur_per_kwh
        allocations = self._building_allocations(
            request=request,
            baseline=baseline,
            requested_kwh=requested_kwh,
            revenue_eur=revenue,
            penalty_eur=penalty,
            time_step=t,
        )

        return {
            "time_step": t,
            "global_time_step": self._global_time_step(),
            "request_id": request.request_id,
            "issuer": request.issuer,
            "direction": request.direction,
            "baseline_valid": True,
            "baseline_reason": None,
            "purpose": request.purpose,
            "requested_kwh": requested_kwh,
            "valid_requested_kwh": requested_kwh,
            "baseline_power_kw": baseline_power,
            "actual_power_kw": actual_power,
            "delivered_power_kw": delivered_power,
            "shortfall_power_kw": shortfall_power,
            "delivered_kwh": delivered_kwh,
            "credited_kwh": credited_kwh,
            "shortfall_kwh": shortfall_kwh,
            "revenue_eur": revenue,
            "penalty_eur": penalty,
            "net_revenue_eur": revenue - penalty,
            "building_allocations": allocations,
        }

    def _building_allocations(
        self,
        *,
        request: DemandResponseRequest,
        baseline: Mapping[str, Any],
        requested_kwh: float,
        revenue_eur: float,
        penalty_eur: float,
        time_step: int,
    ) -> List[Mapping[str, Any]]:
        step_hours = self._step_hours()
        baselines = dict(baseline.get("building_baseline_power_kw", {}) or {})
        active_buildings = list(self.env.buildings)
        count = len(active_buildings)
        if count == 0:
            return []

        contributions: Dict[str, float] = {}
        for building in active_buildings:
            baseline_power = float(baselines.get(building.name, 0.0))
            actual_power = self._building_power_kw(building, time_step)
            contribution = (
                actual_power - baseline_power
                if request.direction == "up"
                else baseline_power - actual_power
            )
            contributions[building.name] = float(contribution)

        positive_sum = sum(max(value, 0.0) for value in contributions.values())
        negative_sum = sum(max(-value, 0.0) for value in contributions.values())
        baseline_abs_sum = sum(abs(float(baselines.get(building.name, 0.0))) for building in active_buildings)

        rows = []
        for building in active_buildings:
            name = building.name
            contribution_power = contributions.get(name, 0.0)
            contribution_kwh = contribution_power * step_hours
            revenue_weight = (
                max(contribution_power, 0.0) / positive_sum
                if positive_sum > 1.0e-12
                else 1.0 / count
            )
            if negative_sum > 1.0e-12:
                penalty_weight = max(-contribution_power, 0.0) / negative_sum
            elif baseline_abs_sum > 1.0e-12:
                penalty_weight = abs(float(baselines.get(name, 0.0))) / baseline_abs_sum
            else:
                penalty_weight = 1.0 / count

            building_revenue = revenue_eur * revenue_weight
            building_penalty = penalty_eur * penalty_weight
            rows.append(
                {
                    "building": name,
                    "baseline_valid": True,
                    "requested_kwh": requested_kwh / count,
                    "valid_requested_kwh": requested_kwh / count,
                    "delivered_kwh": contribution_kwh,
                    "credited_kwh": max(contribution_kwh, 0.0),
                    "shortfall_kwh": max(0.0, requested_kwh / count - contribution_kwh),
                    "revenue_eur": building_revenue,
                    "penalty_eur": building_penalty,
                    "net_revenue_eur": building_revenue - building_penalty,
                    "invalid_baseline": 0.0,
                }
            )

        return rows

    def _invalid_building_allocations(self, requested_kwh: float) -> List[Mapping[str, Any]]:
        buildings = list(self.env.buildings)
        count = max(len(buildings), 1)
        rows = []
        for building in buildings:
            rows.append(
                {
                    "building": building.name,
                    "baseline_valid": False,
                    "requested_kwh": requested_kwh / count,
                    "valid_requested_kwh": 0.0,
                    "delivered_kwh": 0.0,
                    "credited_kwh": 0.0,
                    "shortfall_kwh": 0.0,
                    "revenue_eur": 0.0,
                    "penalty_eur": 0.0,
                    "net_revenue_eur": 0.0,
                    "invalid_baseline": 1.0,
                }
            )
        return rows

    def _previous_settlement(self) -> Optional[Mapping[str, Any]]:
        if self._last_settlement is None:
            return None
        expected = int(getattr(self.env, "time_step", 0)) - 1
        return self._last_settlement if int(self._last_settlement.get("time_step", -1)) == expected else None

    def _current_district_power_kw(self, time_step: int) -> float:
        try:
            energy = float(self.env.net_electricity_consumption[time_step])
        except Exception:
            energy = 0.0
        return energy / self._step_hours()

    def _building_power_kw(self, building, time_step: int) -> float:
        try:
            energy = float(building.net_electricity_consumption[time_step])
        except Exception:
            energy = 0.0
        if not np.isfinite(energy):
            energy = 0.0
        return energy / self._step_hours()

    def _zero_observation_values(self) -> Mapping[str, float]:
        return {
            "dr_active": 0.0,
            "dr_issuer_code": 0.0,
            "dr_direction": 0.0,
            "dr_target_power_kw": 0.0,
            "dr_baseline_power_kw": 0.0,
            "dr_time_remaining_hours": 0.0,
            "dr_activation_price_eur_per_kwh": 0.0,
            "dr_shortfall_penalty_eur_per_kwh": 0.0,
            "dr_previous_delivered_power_kw": 0.0,
            "dr_previous_shortfall_power_kw": 0.0,
        }

    @staticmethod
    def _invalid_baseline(reason='insufficient_history') -> Mapping[str, Any]:
        return {
            "valid": False,
            "reason": reason,
            "baseline_power_kw": 0.0,
            "building_baseline_power_kw": {},
            "window_start_time_step": None,
            "window_end_time_step": None,
        }

    def _global_time_step(self) -> int:
        return self._episode_start_time_step() + int(getattr(self.env, "time_step", 0))

    def _episode_start_time_step(self) -> int:
        tracker = getattr(self.env, "episode_tracker", None)
        return int(getattr(tracker, "episode_start_time_step", 0) or 0)

    def _baseline_window_steps(self) -> int:
        seconds = max(float(getattr(self.env, "seconds_per_time_step", 3600.0) or 3600.0), 1.0)
        return max(1, int(math.ceil(float(self.baseline_window_seconds) / seconds)))

    def audit_summary(self):
        """District service quality by declared purpose, without inferring feasibility."""
        result = {}
        for purpose in ('all', 'service', 'stress', 'unspecified'):
            rows = [r for r in self.settlement_history if purpose == 'all' or r.get('purpose', 'unspecified') == purpose]
            valid = [r for r in rows if r['baseline_valid']]
            totals = {key: sum(float(r[key]) for r in rows) for key in ('requested_kwh', 'valid_requested_kwh', 'delivered_kwh', 'credited_kwh', 'shortfall_kwh', 'revenue_eur', 'penalty_eur', 'net_revenue_eur')}
            totals.update(events_count=float(len({r['request_id'] for r in rows})),
                          active_intervals_count=float(len(rows)), valid_intervals_count=float(len(valid)),
                          baseline_coverage_ratio=len(valid)/len(rows) if rows else None,
                          requested_energy_coverage_ratio=totals['valid_requested_kwh']/totals['requested_kwh'] if totals['requested_kwh']>0 else None,
                          compliance_ratio=min(max(totals['credited_kwh']/totals['valid_requested_kwh'],0.),1.) if totals['valid_requested_kwh']>0 else None)
            for reason in ('insufficient_history', 'nonfinite_history', 'no_members', 'topology_changed'):
                totals['excluded_'+reason+'_intervals_count'] = float(sum(r.get('baseline_reason') == reason for r in rows))
            result[purpose] = totals
        return result

    def _step_hours(self) -> float:
        return max(float(getattr(self.env, "seconds_per_time_step", 3600.0) or 3600.0) / 3600.0, 1.0e-12)

    @staticmethod
    def _empty_summary() -> Dict[str, float]:
        return {
            "demand_response_events_count": 0.0,
            "demand_response_active_time_step_count": 0.0,
            "demand_response_requested_total_kwh": 0.0,
            "demand_response_valid_requested_total_kwh": 0.0,
            "demand_response_delivered_total_kwh": 0.0,
            "demand_response_credited_total_kwh": 0.0,
            "demand_response_shortfall_total_kwh": 0.0,
            "demand_response_revenue_total_eur": 0.0,
            "demand_response_penalty_total_eur": 0.0,
            "demand_response_net_revenue_total_eur": 0.0,
            "demand_response_invalid_baseline_time_step_count": 0.0,
            "demand_response_compliance_ratio": None,
        }

    @staticmethod
    def _accumulate_summary(target: Dict[str, float], row: Mapping[str, Any]):
        target["demand_response_active_time_step_count"] += 1.0
        target["demand_response_requested_total_kwh"] += CityLearnDemandResponseService._to_float(row.get("requested_kwh"), 0.0)
        target["demand_response_valid_requested_total_kwh"] += CityLearnDemandResponseService._to_float(row.get("valid_requested_kwh"), 0.0)
        target["demand_response_delivered_total_kwh"] += CityLearnDemandResponseService._to_float(row.get("delivered_kwh"), 0.0)
        target["demand_response_credited_total_kwh"] += CityLearnDemandResponseService._to_float(row.get("credited_kwh"), 0.0)
        target["demand_response_shortfall_total_kwh"] += CityLearnDemandResponseService._to_float(row.get("shortfall_kwh"), 0.0)
        target["demand_response_revenue_total_eur"] += CityLearnDemandResponseService._to_float(row.get("revenue_eur"), 0.0)
        target["demand_response_penalty_total_eur"] += CityLearnDemandResponseService._to_float(row.get("penalty_eur"), 0.0)
        target["demand_response_net_revenue_total_eur"] += CityLearnDemandResponseService._to_float(row.get("net_revenue_eur"), 0.0)
        invalid = row.get("invalid_baseline")
        if invalid is None:
            invalid = 0.0 if bool(row.get("baseline_valid", False)) else 1.0
        target["demand_response_invalid_baseline_time_step_count"] += CityLearnDemandResponseService._to_float(invalid, 0.0)

    @staticmethod
    def _finalize_summary(summary: Dict[str, float]):
        valid_requested = CityLearnDemandResponseService._to_float(
            summary.get("demand_response_valid_requested_total_kwh"),
            0.0,
        )
        if valid_requested <= 1.0e-12:
            summary["demand_response_compliance_ratio"] = None
        else:
            credited = CityLearnDemandResponseService._to_float(summary.get("demand_response_credited_total_kwh"), 0.0)
            summary["demand_response_compliance_ratio"] = float(np.clip(credited / valid_requested, 0.0, 1.0))

    @staticmethod
    def _to_float(value, default: float = 0.0) -> float:
        try:
            scalar = float(value)
        except (TypeError, ValueError):
            return float(default)
        if not np.isfinite(scalar):
            return float(default)
        return scalar

    @staticmethod
    def _non_negative_float(value, default: float = 0.0, *, path: str) -> float:
        try:
            scalar = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{path} must be a non-negative finite number.") from exc
        if not np.isfinite(scalar) or scalar < 0.0:
            raise ValueError(f"{path} must be a non-negative finite number.")
        return scalar

    @staticmethod
    def _int_value(value, *, path: str) -> int:
        try:
            scalar = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{path} must be an integer.") from exc
        return scalar
