from __future__ import annotations

import copy
import json
import pickle
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from citylearn.agents.llm import GenerativeBuildingAgent, LLMAgent
from citylearn.citylearn import CityLearnEnv
from citylearn.llm import (
    AgentArtifactStorage,
    BuildingSeedGenerator,
    CallableChatAPI,
    HuggingfaceChatAPI,
    OpenAICompatibleChatAPI,
    PlanningModule,
    ProfileModule,
    RuleGuidedMockChatAPI,
    extract_json_from,
    extract_json_from_polluted_string,
)

ROOT = Path(__file__).resolve().parents[1]
MINUTE_EV_SCHEMA = ROOT / "tests" / "data" / "minute_ev_demo" / "schema.json"
PHASE_ALL_EVS_SCHEMA = (
    ROOT / "data" / "datasets" / "citylearn_challenge_2022_phase_all_plus_evs" / "schema.json"
)
DYNAMIC_DEMO_SCHEMA = (
    ROOT / "data" / "datasets" / "citylearn_three_phase_dynamic_topology_demo" / "schema.json"
)


class TestJsonExtraction:
    def test_extracts_from_think_tags_and_code_fence(self):
        polluted = (
            "<think>\nLet us check battery SoC (0.42) and price {high: 0.31}.\n</think>\n"
            "Here is my control decision:\n"
            "```json\n"
            '{"decisions": [{"action_name": "electrical_storage", "reasoning": "Discharge {peak}", "value": -0.25}]}\n'
            "```\n"
            "Hope this helps!"
        )
        parsed = extract_json_from_polluted_string(polluted)
        assert parsed["decisions"][0]["action_name"] == "electrical_storage"
        assert parsed["decisions"][0]["value"] == pytest.approx(-0.25)
        assert extract_json_from(polluted) == parsed

    def test_repairs_trailing_commas_and_handles_nested_braces_in_strings(self):
        noisy = (
            'Reasoning summary before JSON: '
            '{"persona_description": "Household {A} with PV & EV", '
            '"energy_priorities": ["PV self-consumption", "EV readiness",],}'
        )
        parsed = extract_json_from(noisy)
        assert parsed["persona_description"] == "Household {A} with PV & EV"
        assert len(parsed["energy_priorities"]) == 2

    def test_raises_value_error_on_non_json_output(self):
        with pytest.raises(ValueError, match="Could not extract valid JSON"):
            extract_json_from_polluted_string("No braces or JSON payload anywhere here.")


class TestChatBackends:
    def test_openai_compatible_chat_api_posts_and_parses_completion(self):
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "choices": [
                {"message": {"content": '{"decisions": [{"action_name": "electrical_storage", "value": 0.2, "reasoning": "Solar"}]}'}}
            ]
        }
        client = OpenAICompatibleChatAPI(
            base_url="http://localhost:11434/v1/",
            model_id="qwen2.5:7b-instruct",
            api_key="test-key",
            temperature=0.1,
            n_predict=256,
        )
        with patch("citylearn.llm.client.requests.post", return_value=mock_response) as post_mock:
            out = client.get_completion("Select action")

        assert '"electrical_storage"' in out
        called_url = post_mock.call_args[0][0]
        assert called_url == "http://localhost:11434/v1/chat/completions"
        headers = post_mock.call_args[1]["headers"]
        assert headers["Authorization"] == "Bearer test-key"

    def test_huggingface_chat_api_injected_pipeline_and_pickle_roundtrip(self):
        fake_pipe = MagicMock(
            return_value=[
                {
                    "generated_text": [
                        {"role": "system", "content": "sys"},
                        {"role": "user", "content": "prompt"},
                        {"role": "assistant", "content": '{"persona_description": "Solar prosumer"}'},
                    ]
                }
            ]
        )
        hf_client = HuggingfaceChatAPI(
            model_id="Qwen/Qwen3-4B-Instruct-2507",
            n_predict=128,
            temperature=0.0,
            pipeline_instance=fake_pipe,
        )
        text = hf_client.get_completion("Describe building")
        assert extract_json_from(text)["persona_description"] == "Solar prosumer"

        # Pickling drops live pipeline cleanly so --save_agent works.
        restored = pickle.loads(pickle.dumps(hf_client))
        assert restored.model_id == "Qwen/Qwen3-4B-Instruct-2507"
        assert restored._pipeline is None


class TestProfileAndPlanningFallback:
    def test_malformed_llm_outputs_trigger_safe_bounded_fallbacks(self):
        broken_client = CallableChatAPI(lambda prompt: "I refuse to output valid JSON!")
        env = CityLearnEnv(str(MINUTE_EV_SCHEMA), episode_time_steps=4, render_mode="none")
        try:
            building = env.buildings[0]
            seed_gen = BuildingSeedGenerator(
                persona_overrides={building.name: {"occupant_archetype": "custom commuter"}}
            )
            prof_mod = ProfileModule(broken_client, seed_generator=seed_gen, max_retries=0)
            profile = prof_mod.get_or_create_profile(building)
            assert profile.used_fallback is True
            assert "custom commuter" in profile.persona_description

            plan_mod = PlanningModule(broken_client, max_retries=0)
            obs = building.observations(include_all=False, normalize=False, periodic_normalization=False)
            day_plan = plan_mod.plan_day_schedule(profile=profile, day_index=0, observations=obs)
            assert day_plan.used_fallback is True
            assert len(day_plan.description_of_today) >= 1

            specs = [
                {"action_name": "electrical_storage", "low": -0.5, "high": 0.5},
                {"action_name": "positive_only_device", "low": 0.2, "high": 0.8},
            ]
            vec, record = plan_mod.select_actions(
                profile=profile,
                day_plan=day_plan,
                time_step=0,
                observations=obs,
                action_specs=specs,
            )
            assert vec == [pytest.approx(0.0), pytest.approx(0.2)]
            assert all(d.used_fallback for d in record.decisions)
        finally:
            env.close()

    def test_out_of_bounds_llm_actions_are_clamped_to_action_space(self):
        extreme_client = CallableChatAPI(
            lambda prompt: json.dumps(
                {
                    "decisions": [
                        {"action_name": "electrical_storage", "value": 9.5, "reasoning": "Overcharge"},
                        {"action_name": "cooling_storage", "value": -4.0, "reasoning": "Overdischarge"},
                    ]
                }
            )
        )
        env = CityLearnEnv(str(MINUTE_EV_SCHEMA), episode_time_steps=3, render_mode="none")
        try:
            building = env.buildings[0]
            profile = ProfileModule(RuleGuidedMockChatAPI()).get_or_create_profile(building)
            plan_mod = PlanningModule(extreme_client, max_retries=0)
            specs = [
                {"action_name": "electrical_storage", "low": -0.6, "high": 0.6},
                {"action_name": "cooling_storage", "low": -0.4, "high": 0.4},
            ]
            vec, record = plan_mod.select_actions(
                profile=profile,
                day_plan=None,
                time_step=1,
                observations={"hour": 14.0, "day_type": 2.0},
                action_specs=specs,
            )
            assert vec == [pytest.approx(0.6), pytest.approx(-0.4)]
            assert all(d.clamped for d in record.decisions)
        finally:
            env.close()


class TestLLMAgentIntegration:
    def test_decentralized_rollout_writes_gta_artifacts_and_evaluates_kpis(self, tmp_path: Path):
        storage_dir = tmp_path / "gta_artifacts"
        env = CityLearnEnv(
            str(PHASE_ALL_EVS_SCHEMA),
            buildings=["Building_1", "Building_2"],
            episode_time_steps=6,
            central_agent=False,
            interface="flat",
            render_mode="none",
        )
        try:
            agent = LLMAgent(
                env,
                backend="mock",
                storage_dir=storage_dir,
                enable_day_planning=True,
            )
            assert GenerativeBuildingAgent is LLMAgent
            identity = agent.comparison_identity()
            assert identity["observation_access"] == "active_only"

            obs, _ = env.reset(seed=0)
            while not (env.terminated or env.truncated):
                actions = agent.predict(obs)
                assert len(actions) == 2
                for b_idx, vec in enumerate(actions):
                    space = env.action_space[b_idx]
                    assert len(vec) == space.shape[0]
                    for val, low, high in zip(vec, space.low, space.high):
                        assert float(low) - 1e-6 <= val <= float(high) + 1e-6
                obs, _, _, _, _ = env.step(actions)

            assert (storage_dir / AgentArtifactStorage.DESCRIPTIONS_FILENAME).is_file()
            assert (storage_dir / AgentArtifactStorage.DAY_SCHEDULES_FILENAME).is_file()
            assert (storage_dir / AgentArtifactStorage.DECISIONS_FILENAME).is_file()

            descriptions = json.loads((storage_dir / "1_descriptions.json").read_text(encoding="utf-8"))
            schedules = json.loads((storage_dir / "2_day_schedules.json").read_text(encoding="utf-8"))
            decisions = json.loads((storage_dir / "3_decisions.json").read_text(encoding="utf-8"))

            assert set(descriptions.keys()) == {"Building_1", "Building_2"}
            assert len(schedules) == 2
            assert len(decisions) == 2 * 5

            kpis = env.evaluate_v2()
            assert not kpis.empty
        finally:
            env.close()

    def test_central_agent_entity_interface_and_decision_interval(self):
        call_counter = {"action_calls": 0}
        mock_api = RuleGuidedMockChatAPI()

        def counting_callable(prompt: str, system_prompt: str) -> str:
            if '"prompt_stage": "action_selection"' in prompt:
                call_counter["action_calls"] += 1
            return mock_api.get_completion(prompt, system_prompt=system_prompt)

        env = CityLearnEnv(
            str(MINUTE_EV_SCHEMA),
            central_agent=True,
            episode_time_steps=7,
            interface="entity",
            render_mode="none",
        )
        try:
            agent = LLMAgent(
                env,
                llm_client=counting_callable,
                enable_day_planning=False,
                decision_interval_steps=3,
            )
            obs, _ = env.reset(seed=0)
            steps_executed = 0
            while not (env.terminated or env.truncated):
                actions = agent.predict(obs)
                assert len(actions) == 1
                obs, _, _, _, _ = env.step(actions)
                steps_executed += 1

            assert steps_executed == 6
            # For 6 steps (t=0..5) with interval=3, LLM is queried only at t=0 and t=3 per building.
            expected_calls = 2 * len(env.buildings)
            assert call_counter["action_calls"] == expected_calls
            reused_flags = [rec["reused_previous_step"] for rec in agent.storage.decisions]
            assert any(reused_flags)
        finally:
            env.close()

    def test_dynamic_topology_lazily_profiles_newly_joined_buildings(self):
        dyn_schema = json.loads(DYNAMIC_DEMO_SCHEMA.read_text(encoding="utf-8"))
        dyn_schema["root_directory"] = str(DYNAMIC_DEMO_SCHEMA.parent)
        dyn_schema["topology_mode"] = "dynamic"
        for event, step in zip(dyn_schema.get("topology_events", []), [2, 3, 4, 5, 6, 7, 8, 9]):
            event["time_step"] = step

        env = CityLearnEnv(
            dyn_schema,
            episode_time_steps=10,
            interface="entity",
            render_mode="none",
        )
        try:
            agent = LLMAgent(env, backend="mock", enable_day_planning=True)
            obs, _ = env.reset(seed=0)
            initial_buildings = set(agent.storage.descriptions.keys())

            while not (env.terminated or env.truncated):
                actions = agent.predict(obs)
                obs, _, _, _, _ = env.step(actions)

            final_buildings = set(agent.storage.descriptions.keys())
            assert len(final_buildings) > len(initial_buildings)
        finally:
            env.close()

    def test_schema_load_agent_instantiates_llm_agent(self, tmp_path: Path):
        schema: Dict[str, Any] = json.loads(MINUTE_EV_SCHEMA.read_text(encoding="utf-8"))
        schema = copy.deepcopy(schema)
        schema["root_directory"] = str(MINUTE_EV_SCHEMA.parent)
        schema["agent"] = {
            "type": "citylearn.agents.llm.LLMAgent",
            "attributes": {
                "backend": "mock",
                "storage_dir": str(tmp_path / "loaded_agent_logs"),
                "enable_day_planning": True,
            },
        }
        env = CityLearnEnv(schema, episode_time_steps=4, render_mode="none")
        try:
            agent = env.load_agent()
            assert isinstance(agent, LLMAgent)
            agent.learn(episodes=1)
            assert (tmp_path / "loaded_agent_logs" / "3_decisions.json").is_file()
        finally:
            env.close()
