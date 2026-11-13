from __future__ import annotations

import abc
import inspect
import json
import math
import os
import time
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

import requests

from citylearn.llm.prompts import (
    CONTEXT_END_MARKER,
    CONTEXT_START_MARKER,
    DEFAULT_SYSTEM_PROMPT,
)


class BaseChatAPI(abc.ABC):
    """Abstract interface for LLM chat backends used by CityLearn generative agents."""

    def __init__(self, system_prompt: Optional[str] = None):
        self.system_prompt = DEFAULT_SYSTEM_PROMPT if system_prompt is None else str(system_prompt)

    @abc.abstractmethod
    def get_completion(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """Generate a completion string for a single user prompt."""

    def get_completions(
        self,
        prompts: Sequence[str],
        system_prompt: Optional[str] = None,
    ) -> List[str]:
        """Generate completions for a batch of prompts."""
        return [self.get_completion(prompt, system_prompt=system_prompt) for prompt in prompts]


class HuggingfaceChatAPI(BaseChatAPI):
    """Local HuggingFace ``transformers`` chat backend modeled after Generative-Traffic-Agents.

    Defaults to ``Qwen/Qwen3-4B-Instruct-2507`` and loads ``transformers`` + ``torch``
    lazily on first inference so agent construction and unpickling remain lightweight.
    """

    DEFAULT_MODEL_ID = "Qwen/Qwen3-4B-Instruct-2507"

    def __init__(
        self,
        model_id: Optional[str] = None,
        system_prompt: Optional[str] = None,
        n_predict: int = 700,
        gpu_id: int = 0,
        temperature: float = 0.2,
        do_sample: Optional[bool] = None,
        device_map: Optional[str] = None,
        torch_dtype: Any = "auto",
        pipeline_instance: Any = None,
    ):
        super().__init__(system_prompt=system_prompt)
        self.model_id = self.DEFAULT_MODEL_ID if not model_id else str(model_id)
        self.n_predict = max(int(n_predict), 16)
        self.gpu_id = int(gpu_id)
        self.temperature = max(float(temperature), 0.0)
        self.do_sample = (self.temperature > 0.0) if do_sample is None else bool(do_sample)
        self.device_map = device_map
        self.torch_dtype = torch_dtype
        self._pipeline = pipeline_instance

    def _ensure_pipeline(self) -> Any:
        if self._pipeline is not None:
            return self._pipeline

        try:
            import torch
            from transformers import pipeline
        except ImportError as exc:
            raise ImportError(
                "HuggingfaceChatAPI requires `transformers` (and `torch`). "
                "Install optional LLM dependencies with `pip install citylearn[llm]`."
            ) from exc

        pipe_kwargs: Dict[str, Any] = {
            "task": "text-generation",
            "model": self.model_id,
            "torch_dtype": self.torch_dtype,
        }
        if self.device_map is not None:
            pipe_kwargs["device_map"] = self.device_map
        elif torch.cuda.is_available() and self.gpu_id >= 0:
            pipe_kwargs["device"] = self.gpu_id
        else:
            pipe_kwargs["device"] = -1

        self._pipeline = pipeline(**pipe_kwargs)
        return self._pipeline

    def _build_messages(self, prompt: str, system_prompt: Optional[str] = None) -> List[Dict[str, str]]:
        active_system = self.system_prompt if system_prompt is None else str(system_prompt)
        return [
            {"role": "system", "content": active_system},
            {"role": "user", "content": str(prompt)},
        ]

    @staticmethod
    def _extract_generated_content(output: Any) -> str:
        item = output[0] if isinstance(output, list) and len(output) > 0 else output
        if isinstance(item, Mapping):
            generated = item.get("generated_text", "")
            if isinstance(generated, list) and len(generated) > 0:
                last_msg = generated[-1]
                if isinstance(last_msg, Mapping):
                    return str(last_msg.get("content", ""))
                return str(last_msg)
            return str(generated)
        return str(item)

    def get_completion(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        pipe = self._ensure_pipeline()
        messages = self._build_messages(prompt, system_prompt=system_prompt)
        gen_kwargs: Dict[str, Any] = {
            "max_new_tokens": self.n_predict,
            "do_sample": self.do_sample,
        }
        if self.do_sample and self.temperature > 0.0:
            gen_kwargs["temperature"] = self.temperature

        try:
            import torch

            ctx = torch.inference_mode()
        except ImportError:
            ctx = None

        if ctx is not None:
            with ctx:
                raw_out = pipe(messages, **gen_kwargs)
        else:
            raw_out = pipe(messages, **gen_kwargs)
        return self._extract_generated_content(raw_out)

    def get_completions(
        self,
        prompts: Sequence[str],
        system_prompt: Optional[str] = None,
    ) -> List[str]:
        if len(prompts) == 0:
            return []
        pipe = self._ensure_pipeline()
        batch_messages = [self._build_messages(p, system_prompt=system_prompt) for p in prompts]
        gen_kwargs: Dict[str, Any] = {
            "max_new_tokens": self.n_predict,
            "do_sample": self.do_sample,
        }
        if self.do_sample and self.temperature > 0.0:
            gen_kwargs["temperature"] = self.temperature

        try:
            import torch

            with torch.inference_mode():
                outputs = pipe(batch_messages, **gen_kwargs)
        except ImportError:
            outputs = pipe(batch_messages, **gen_kwargs)

        return [self._extract_generated_content(out) for out in outputs]

    def __getstate__(self) -> Dict[str, Any]:
        state = dict(self.__dict__)
        state["_pipeline"] = None
        return state

    def __setstate__(self, state: Dict[str, Any]) -> None:
        self.__dict__.update(state)
        self._pipeline = None


class OpenAICompatibleChatAPI(BaseChatAPI):
    """HTTP client for OpenAI, Ollama, vLLM, LiteLLM, or OpenRouter ``/chat/completions``."""

    DEFAULT_BASE_URL = "http://localhost:11434/v1"
    DEFAULT_MODEL_ID = "qwen2.5:7b-instruct"

    def __init__(
        self,
        model_id: Optional[str] = None,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        system_prompt: Optional[str] = None,
        n_predict: int = 700,
        temperature: float = 0.2,
        timeout_seconds: float = 60.0,
        max_http_retries: int = 2,
        extra_body: Optional[Mapping[str, Any]] = None,
    ):
        super().__init__(system_prompt=system_prompt)
        env_url = os.environ.get("CITYLEARN_LLM_BASE_URL") or os.environ.get("OPENAI_BASE_URL")
        resolved_url = base_url or env_url or self.DEFAULT_BASE_URL
        self.base_url = str(resolved_url).rstrip("/")
        env_model = os.environ.get("CITYLEARN_LLM_MODEL")
        self.model_id = str(model_id or env_model or self.DEFAULT_MODEL_ID)
        self.api_key = (
            api_key
            if api_key is not None
            else (os.environ.get("CITYLEARN_LLM_API_KEY") or os.environ.get("OPENAI_API_KEY") or "")
        )
        self.n_predict = max(int(n_predict), 16)
        self.temperature = max(float(temperature), 0.0)
        self.timeout_seconds = max(float(timeout_seconds), 1.0)
        self.max_http_retries = max(int(max_http_retries), 0)
        self.extra_body = {} if extra_body is None else dict(extra_body)

    def get_completion(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        active_system = self.system_prompt if system_prompt is None else str(system_prompt)
        endpoint = (
            self.base_url
            if self.base_url.endswith("/chat/completions")
            else f"{self.base_url}/chat/completions"
        )
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload: Dict[str, Any] = {
            "model": self.model_id,
            "messages": [
                {"role": "system", "content": active_system},
                {"role": "user", "content": str(prompt)},
            ],
            "temperature": self.temperature,
            "max_tokens": self.n_predict,
            **self.extra_body,
        }

        last_exc: Optional[Exception] = None
        for attempt in range(self.max_http_retries + 1):
            try:
                response = requests.post(
                    endpoint,
                    headers=headers,
                    json=payload,
                    timeout=self.timeout_seconds,
                )
                response.raise_for_status()
                body = response.json()
                choices = body.get("choices") or []
                if not choices:
                    raise ValueError(f"Empty choices in LLM response: {body!r}")
                message = choices[0].get("message") or {}
                if "content" in message and message["content"] is not None:
                    return str(message["content"])
                if "text" in choices[0]:
                    return str(choices[0]["text"])
                raise ValueError(f"Missing completion content in LLM response: {body!r}")
            except Exception as exc:
                last_exc = exc
                if attempt < self.max_http_retries:
                    time.sleep(min(0.5 * (2 ** attempt), 2.0))
        raise RuntimeError(f"OpenAICompatibleChatAPI request to {endpoint} failed: {last_exc}") from last_exc


class CallableChatAPI(BaseChatAPI):
    """Wrap a custom Python callable as a ``BaseChatAPI`` client."""

    def __init__(self, fn: Callable[..., str], system_prompt: Optional[str] = None):
        if not callable(fn):
            raise TypeError("CallableChatAPI requires a callable `fn`.")
        super().__init__(system_prompt=system_prompt)
        self._fn = fn
        try:
            sig = inspect.signature(fn)
            params = list(sig.parameters.values())
            self._accepts_system = any(
                p.kind == inspect.Parameter.VAR_KEYWORD for p in params
            ) or len(params) >= 2
        except (TypeError, ValueError):
            self._accepts_system = False

    def get_completion(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        active_system = self.system_prompt if system_prompt is None else str(system_prompt)
        if self._accepts_system:
            return str(self._fn(prompt, active_system))
        return str(self._fn(prompt))


class RuleGuidedMockChatAPI(BaseChatAPI):
    """Deterministic, physics-grounded offline responder speaking the GTA JSON protocol.

    Enables out-of-the-box runnable examples, schema/CLI simulations, and CI tests
    without requiring external API keys or multi-gigabyte model downloads.
    """

    @staticmethod
    def _extract_context(prompt: str) -> Dict[str, Any]:
        if CONTEXT_START_MARKER in prompt and CONTEXT_END_MARKER in prompt:
            start = prompt.index(CONTEXT_START_MARKER) + len(CONTEXT_START_MARKER)
            end = prompt.index(CONTEXT_END_MARKER, start)
            try:
                return json.loads(prompt[start:end].strip())
            except json.JSONDecodeError:
                return {}
        return {}

    def get_completion(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        ctx = self._extract_context(prompt)
        stage = str(ctx.get("prompt_stage", ""))

        if stage == "persona_description":
            return json.dumps(self._build_persona(ctx), indent=2)
        if stage == "day_schedule":
            return json.dumps(self._build_day_schedule(ctx), indent=2)
        return json.dumps(self._build_action_decisions(ctx), indent=2)

    @staticmethod
    def _build_persona(ctx: Mapping[str, Any]) -> Dict[str, Any]:
        seed = ctx.get("seed_profile") or {}
        name = seed.get("building_name", "Building")
        archetype = seed.get("occupant_archetype", "residential prosumer")
        pv_kw = float(seed.get("pv_nominal_power_kw", 0.0) or 0.0)
        bess_kwh = float(seed.get("battery_capacity_kwh", 0.0) or 0.0)
        chargers = seed.get("ev_chargers") or []
        deferrables = seed.get("deferrable_appliances") or []

        assets = []
        if pv_kw > 0.0:
            assets.append(f"{pv_kw:.1f} kWp rooftop PV")
        if bess_kwh > 0.0:
            assets.append(f"{bess_kwh:.1f} kWh battery storage")
        if chargers:
            assets.append(f"{len(chargers)} EV charger(s)")
        if deferrables:
            assets.append(f"{len(deferrables)} deferrable appliance(s)")
        asset_text = ", ".join(assets) if assets else "standard building HVAC and plug loads"

        return {
            "persona_description": (
                f"{name} represents a {archetype} equipped with {asset_text}. "
                f"Occupants prioritize indoor comfort and reliable EV departure readiness "
                f"while shifting flexible charging and storage to solar surplus and low-tariff hours."
            ),
            "energy_priorities": [
                "Meet EV departure SoC targets without violating service limits",
                "Store midday solar surplus and low-tariff power in battery/thermal storage",
                "Discharge storage during evening high-price and high-carbon periods",
            ],
            "comfort_preference": "Maintain indoor temperature near comfort setpoints with proactive thermal storage.",
            "ev_flexibility_preference": "Guarantee departure SoC before deadline while preferring solar or off-peak charging.",
        }

    @staticmethod
    def _build_day_schedule(ctx: Mapping[str, Any]) -> Dict[str, Any]:
        day_type = int(ctx.get("day_type", 1) or 1)
        is_weekend = day_type in {6, 7}
        pattern = "weekend daytime occupancy" if is_weekend else "weekday commuter occupancy"
        return {
            "description_of_today": [
                f"00:00-06:00: Maintain overnight reserve and top up connected EVs during off-peak tariffs ({pattern}).",
                "06:00-10:00: Support morning load ramp and complete urgent EV charging before departure.",
                "10:00-16:00: Absorb solar PV surplus into battery and thermal storage; run deferrable appliances.",
                "16:00-22:00: Discharge battery during peak electricity price hours while respecting reserve SoC.",
                "22:00-24:00: Rebalance storage and stage overnight EV charging.",
            ],
            "solar_charging_window": "10:00-16:00 targeting 85% battery SoC when PV exceeds building load.",
            "peak_avoidance_strategy": "Discharge battery between 17:00-21:00 or when current price exceeds 6h/24h forecast.",
            "ev_charging_plan": "Charge urgently when remaining hours approach required energy; otherwise opportunistically on solar/low price.",
        }

    @classmethod
    def _build_action_decisions(cls, ctx: Mapping[str, Any]) -> Dict[str, Any]:
        obs = ctx.get("observations") or {}
        specs = ctx.get("action_specs") or []
        hour = float(obs.get("hour", 12.0))
        price = float(obs.get("electricity_pricing", 0.0))
        price_6h = float(obs.get("electricity_pricing_predicted_1", obs.get("electricity_pricing_predicted_6h", price)))
        price_24h = float(obs.get("electricity_pricing_predicted_3", obs.get("electricity_pricing_predicted_24h", price)))
        ref_price = 0.5 * (price_6h + price_24h) if (price_6h > 0.0 or price_24h > 0.0) else price

        solar_gen = abs(float(obs.get("solar_generation", 0.0)))
        non_shiftable = float(obs.get("non_shiftable_load", 0.0))
        net_surplus = solar_gen - non_shiftable

        decisions: List[Dict[str, Any]] = []
        for spec in specs:
            name = str(spec.get("action_name", ""))
            low = float(spec.get("low", -1.0))
            high = float(spec.get("high", 1.0))
            val, reason = cls._decide_single_action(
                name=name,
                low=low,
                high=high,
                spec=spec,
                obs=obs,
                hour=hour,
                price=price,
                ref_price=ref_price,
                net_surplus=net_surplus,
            )
            clipped = max(low, min(high, float(val)))
            decisions.append(
                {
                    "action_name": name,
                    "reasoning": reason,
                    "value": round(clipped, 4),
                }
            )
        return {"decisions": decisions}

    @staticmethod
    def _decide_single_action(
        *,
        name: str,
        low: float,
        high: float,
        spec: Mapping[str, Any],
        obs: Mapping[str, Any],
        hour: float,
        price: float,
        ref_price: float,
        net_surplus: float,
    ) -> tuple[float, str]:
        if name.startswith("electric_vehicle_storage_"):
            charger_id = name[len("electric_vehicle_storage_") :]
            state = float(obs.get(f"electric_vehicle_charger_{charger_id}_connected_state", 1.0))
            soc = float(obs.get(f"electric_vehicle_charger_{charger_id}_soc", 0.5))
            req_soc = float(obs.get(f"electric_vehicle_charger_{charger_id}_required_soc_departure", 0.85))
            dep_hours = float(obs.get(f"electric_vehicle_charger_{charger_id}_estimated_departure_time", 6.0))
            min_eff = float(spec.get("min_effective_action", 0.0) or 0.0)

            if state < 0.5 or math.isnan(soc) or soc < 0.0:
                return 0.0, "No EV currently connected requiring active charging."
            target_soc = max(min(req_soc + 0.05, 1.0), 0.80)
            deficit = max(target_soc - soc, 0.0)
            if deficit <= 0.01:
                return 0.0, f"Connected EV SoC ({soc:.2f}) already meets target ({target_soc:.2f})."
            if dep_hours <= 3.0 or deficit >= 0.35:
                cmd = max(min(high, 0.85), min_eff)
                return cmd, f"EV needs {deficit:.2f} SoC within {dep_hours:.1f}h; charging actively above deadband."
            if net_surplus > 0.05 or (ref_price > 0.0 and price <= 0.95 * ref_price) or hour <= 6.0:
                cmd = max(min(high, 0.55), min_eff)
                return cmd, "Favorable solar/off-peak conditions for steady EV charging."
            cmd = max(min(high, 0.25), min_eff) if dep_hours <= 8.0 else 0.0
            return cmd, "Moderate EV charging pace while awaiting cheaper or solar hours."

        if name == "electrical_storage":
            soc = float(obs.get("electrical_storage_soc", 0.5))
            min_soc = float(spec.get("min_soc", 0.20) or 0.20)
            if net_surplus > 0.05 and soc < 0.90:
                rate = min(high, max(0.15, min(0.45, net_surplus * 0.1)))
                return rate, f"Solar generation exceeds base load (net surplus {net_surplus:.2f}); charging battery."
            if ref_price > 0.0 and price <= 0.88 * ref_price and soc < 0.80:
                return min(high, 0.25), f"Current tariff ({price:.3f}) is below forecast average ({ref_price:.3f}); pre-charging."
            if soc > min_soc + 0.05 and (
                (ref_price > 0.0 and price >= 1.08 * ref_price) or (17.0 <= hour <= 21.0 and net_surplus < 0.0)
            ):
                return max(low, -0.30), f"Peak period at hour {hour:.0f} with battery SoC {soc:.2f}; discharging to shave grid import."
            return 0.0, f"Holding battery SoC ({soc:.2f}) steady under balanced price/load conditions."

        if name.startswith("deferrable_appliance_"):
            if net_surplus > 0.0 or (10.0 <= hour <= 15.0) or (ref_price > 0.0 and price <= 0.92 * ref_price) or hour >= 21.0:
                return min(high, 1.0), "Running deferrable cycle during favorable solar/tariff window."
            return max(low, 0.0), "Deferring cycle away from higher-tariff window."

        if name in {"cooling_storage", "heating_storage", "dhw_storage"}:
            soc = float(obs.get(f"{name}_soc", 0.5))
            if (net_surplus > 0.0 or (10.0 <= hour <= 15.0)) and soc < 0.85:
                return min(high, 0.25), f"Pre-charging {name} during solar/midday window."
            if (17.0 <= hour <= 21.0) and soc > 0.25:
                return max(low, -0.25), f"Discharging {name} to reduce evening HVAC/DHW peak power."
            return 0.0, f"Maintaining {name} reserve."

        if name == "cooling_or_heating_device":
            indoor = float(obs.get("indoor_dry_bulb_temperature", 22.0))
            cool_sp = float(obs.get("indoor_dry_bulb_temperature_cooling_set_point", 24.0))
            heat_sp = float(obs.get("indoor_dry_bulb_temperature_heating_set_point", 20.0))
            if indoor > cool_sp + 0.3 and low < 0.0:
                return max(low, -0.45), f"Indoor temp ({indoor:.1f}C) above cooling setpoint ({cool_sp:.1f}C); cooling."
            if indoor < heat_sp - 0.3 and high > 0.0:
                return min(high, 0.45), f"Indoor temp ({indoor:.1f}C) below heating setpoint ({heat_sp:.1f}C); heating."
            return 0.0, "Indoor temperature is within thermal comfort band."

        if name == "cooling_device":
            indoor = float(obs.get("indoor_dry_bulb_temperature", 22.0))
            cool_sp = float(obs.get("indoor_dry_bulb_temperature_cooling_set_point", 24.0))
            if indoor > cool_sp + 0.2:
                return min(high, 0.5), "Cooling active to maintain comfort setpoint."
            return max(low, 0.0), "No active cooling needed."

        if name == "heating_device":
            indoor = float(obs.get("indoor_dry_bulb_temperature", 22.0))
            heat_sp = float(obs.get("indoor_dry_bulb_temperature_heating_set_point", 20.0))
            if indoor < heat_sp - 0.2:
                return min(high, 0.5), "Heating active to maintain comfort setpoint."
            return max(low, 0.0), "No active heating needed."

        default_zero = max(low, min(high, 0.0))
        return default_zero, "Neutral safe action within physical bounds."
