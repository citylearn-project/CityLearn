from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Mapping, Optional

from citylearn.llm.client import BaseChatAPI
from citylearn.llm.json_parser import extract_json_from_polluted_string
from citylearn.llm.models import BuildingProfile, BuildingSeedProfile
from citylearn.llm.prompts import get_description_prompt

LOGGER = logging.getLogger(__name__)


def _clean_float(val: Any, default: float = 0.0) -> float:
    try:
        scalar = float(val)
    except (TypeError, ValueError):
        return float(default)
    return scalar if math.isfinite(scalar) else float(default)


class BuildingSeedGenerator:
    """Extract grounded static attributes from a CityLearn ``Building`` instance.

    Analogous to GTA's ``agent_seed_generator``: inspects installed equipment
    ratings, annual demand estimates, EV chargers, deferrable appliances, and
    active action bounds without accessing future step trajectories.
    """

    def __init__(self, persona_overrides: Optional[Mapping[str, Mapping[str, Any]]] = None):
        self.persona_overrides: Dict[str, Dict[str, Any]] = {
            str(k): dict(v) for k, v in (persona_overrides or {}).items()
        }

    def generate_seed(self, building: Any) -> BuildingSeedProfile:
        metadata = building.get_metadata() if hasattr(building, "get_metadata") else {}
        name = str(getattr(building, "name", metadata.get("name", "Building")))
        override = dict(self.persona_overrides.get(name, {}))

        pv_meta = metadata.get("pv") or {}
        pv_kw = _clean_float(pv_meta.get("nominal_power", getattr(getattr(building, "pv", None), "nominal_power", 0.0)))

        bess_obj = getattr(building, "electrical_storage", None)
        bess_meta = metadata.get("electrical_storage") or {}
        bess_kwh = _clean_float(bess_meta.get("capacity", getattr(bess_obj, "capacity", 0.0)))
        bess_kw = _clean_float(bess_meta.get("nominal_power", getattr(bess_obj, "nominal_power", 0.0)))
        dod = _clean_float(getattr(bess_obj, "depth_of_discharge", 1.0), 1.0)
        bess_min_soc = max(0.0, min(1.0, 1.0 - dod)) if 0.0 <= dod <= 1.0 else 0.0

        ev_chargers: List[Dict[str, Any]] = []
        for charger in getattr(building, "electric_vehicle_chargers", None) or []:
            max_p = _clean_float(getattr(charger, "max_charging_power", 0.0))
            min_p = _clean_float(getattr(charger, "min_charging_power", 0.0))
            ev_chargers.append(
                {
                    "charger_id": str(getattr(charger, "charger_id", "")),
                    "max_charging_power_kw": max_p,
                    "min_charging_power_kw": min_p,
                    "max_discharging_power_kw": _clean_float(getattr(charger, "max_discharging_power", 0.0)),
                    "min_effective_action": (min_p / max_p) if max_p > 0.0 and min_p > 0.0 else 0.0,
                }
            )

        deferrables: List[Dict[str, Any]] = []
        for idx, app in enumerate(getattr(building, "deferrable_appliances", None) or []):
            deferrables.append(
                {
                    "index": idx,
                    "name": str(getattr(app, "name", f"deferrable_appliance_{idx}")),
                    "nominal_power_kw": _clean_float(getattr(app, "nominal_power", 0.0)),
                }
            )

        active_actions = list(getattr(building, "active_actions", []) or [])
        action_bounds: Dict[str, List[float]] = {}
        space = getattr(building, "action_space", None)
        if space is not None and hasattr(space, "low") and hasattr(space, "high"):
            for idx, act_name in enumerate(active_actions):
                if idx < len(space.low):
                    action_bounds[str(act_name)] = [
                        _clean_float(space.low[idx], -1.0),
                        _clean_float(space.high[idx], 1.0),
                    ]

        annual_demands = {
            "non_shiftable_load_kwh": round(_clean_float(metadata.get("annual_non_shiftable_load_estimate", 0.0)), 2),
            "cooling_demand_kwh": round(_clean_float(metadata.get("annual_cooling_demand_estimate", 0.0)), 2),
            "heating_demand_kwh": round(_clean_float(metadata.get("annual_heating_demand_estimate", 0.0)), 2),
            "dhw_demand_kwh": round(_clean_float(metadata.get("annual_dhw_demand_estimate", 0.0)), 2),
            "solar_generation_kwh": round(_clean_float(metadata.get("annual_solar_generation_estimate", 0.0)), 2),
        }

        equipment_summary = {
            "has_pv": pv_kw > 0.0,
            "has_electrical_storage": bess_kwh > 0.0,
            "cooling_storage_kwh": _clean_float((metadata.get("cooling_storage") or {}).get("capacity", 0.0)),
            "heating_storage_kwh": _clean_float((metadata.get("heating_storage") or {}).get("capacity", 0.0)),
            "dhw_storage_kwh": _clean_float((metadata.get("dhw_storage") or {}).get("capacity", 0.0)),
            "ev_charger_count": len(ev_chargers),
            "deferrable_appliance_count": len(deferrables),
        }

        default_archetype = (
            "EV-equipped solar-plus-storage prosumer"
            if (pv_kw > 0.0 and bess_kwh > 0.0 and len(ev_chargers) > 0)
            else "solar-plus-storage prosumer"
            if (pv_kw > 0.0 and bess_kwh > 0.0)
            else "flexible residential/commercial building"
        )
        archetype = str(override.pop("occupant_archetype", default_archetype))

        return BuildingSeedProfile(
            building_name=name,
            occupant_archetype=archetype,
            equipment_summary=equipment_summary,
            active_actions=active_actions,
            action_bounds=action_bounds,
            annual_demands_kwh=annual_demands,
            pv_nominal_power_kw=pv_kw,
            battery_capacity_kwh=bess_kwh,
            battery_nominal_power_kw=bess_kw,
            battery_min_soc=bess_min_soc,
            ev_chargers=ev_chargers,
            deferrable_appliances=deferrables,
            custom_attributes=override,
        )


class ProfileModule:
    """Stage-1 persona synthesis module modeled directly after GTA's ``ProfileModule``."""

    def __init__(
        self,
        llm_client: BaseChatAPI,
        *,
        seed_generator: Optional[BuildingSeedGenerator] = None,
        max_retries: int = 1,
    ):
        self.llm_client = llm_client
        self.seed_generator = seed_generator or BuildingSeedGenerator()
        self.max_retries = max(int(max_retries), 0)
        self._profiles: Dict[str, BuildingProfile] = {}

    @property
    def profiles(self) -> Dict[str, BuildingProfile]:
        return dict(self._profiles)

    def clear(self) -> None:
        self._profiles.clear()

    def get_or_create_profile(self, building: Any) -> BuildingProfile:
        name = str(getattr(building, "name", "Building"))
        if name in self._profiles:
            return self._profiles[name]

        seed = self.seed_generator.generate_seed(building)
        prompt = get_description_prompt(seed)
        raw_text = ""

        for _ in range(self.max_retries + 1):
            try:
                raw_text = self.llm_client.get_completion(prompt)
                parsed = extract_json_from_polluted_string(raw_text)
                if isinstance(parsed, Mapping) and str(parsed.get("persona_description", "")).strip():
                    priorities_raw = parsed.get("energy_priorities") or []
                    if isinstance(priorities_raw, str):
                        priorities = [priorities_raw]
                    elif isinstance(priorities_raw, list):
                        priorities = [str(item) for item in priorities_raw if str(item).strip()]
                    else:
                        priorities = []

                    profile = BuildingProfile(
                        building_name=name,
                        persona_description=str(parsed["persona_description"]).strip(),
                        energy_priorities=priorities or [
                            "Maximize solar self-consumption",
                            "Protect occupant comfort and EV readiness",
                        ],
                        comfort_preference=str(
                            parsed.get(
                                "comfort_preference",
                                "Maintain indoor comfort within setpoint band.",
                            )
                        ),
                        ev_flexibility_preference=str(
                            parsed.get(
                                "ev_flexibility_preference",
                                "Ensure EV departure SoC target before scheduled departure.",
                            )
                        ),
                        seed_profile=seed,
                        raw_response=raw_text,
                        used_fallback=False,
                    )
                    self._profiles[name] = profile
                    return profile
            except Exception as exc:
                LOGGER.debug("ProfileModule fallback retry for %s: %s", name, exc)

        fallback = self._fallback_profile(seed, raw_response=raw_text)
        self._profiles[name] = fallback
        return fallback

    @staticmethod
    def _fallback_profile(seed: BuildingSeedProfile, raw_response: str = "") -> BuildingProfile:
        return BuildingProfile(
            building_name=seed.building_name,
            persona_description=(
                f"{seed.building_name} is a {seed.occupant_archetype} managing "
                f"{seed.pv_nominal_power_kw:.1f} kWp PV and {seed.battery_capacity_kwh:.1f} kWh storage "
                f"to balance comfort, EV departure readiness, and grid cost."
            ),
            energy_priorities=[
                "Meet EV departure SoC targets reliably",
                "Store solar surplus and low-price electricity",
                "Reduce peak grid imports",
            ],
            comfort_preference="Keep indoor temperature comfortable around setpoints.",
            ev_flexibility_preference="Prioritize timely EV charging above charger minimum power.",
            seed_profile=seed,
            raw_response=raw_response,
            used_fallback=True,
        )
