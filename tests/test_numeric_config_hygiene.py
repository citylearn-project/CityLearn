"""Numeric and configuration hygiene (#228, #242, #251, #252, #253, #254, #255).

Each test failed on 3.6.0: non-finite actions and states passed silently, EV deadline features left their
observation bounds, importing CityLearn reconfigured the host program, CLI exit codes were wrong, invalid
configuration was ignored, exports landed inside the installed package and checkpoints were fully unpickled.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import pickle
import subprocess
import sys
import textwrap
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("gymnasium")

from citylearn.base import EpisodeTracker
from citylearn.citylearn import CityLearnEnv
from citylearn.energy_model import Battery
from citylearn.internal.physics_invariants import PhysicsInvariantError

ROOT = Path(__file__).resolve().parents[1]
MINUTE_EV_DEMO = ROOT / "tests" / "data" / "minute_ev_demo" / "schema.json"
PLUS_EVS = ROOT / "data" / "datasets" / "citylearn_challenge_2022_phase_all_plus_evs" / "schema.json"
DYNAMIC_DEMO = ROOT / "data" / "datasets" / "citylearn_three_phase_dynamic_topology_demo" / "schema.json"


def _schema(path: Path) -> dict:
    schema = json.loads(path.read_text(encoding="utf-8"))
    schema["root_directory"] = str(path.parent)
    return schema


def _run_python(code: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, *args, "-c", textwrap.dedent(code)],
        capture_output=True, text=True, cwd=ROOT, timeout=300,
    )


# #228 Non-finite actions and states


@pytest.mark.parametrize("interface", ["flat", "entity"])
@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_storage_action_is_rejected(interface, bad):
    env = CityLearnEnv(str(MINUTE_EV_DEMO), interface=interface, central_agent=False, episode_time_steps=4, random_seed=0)
    env.reset()
    soc_before = float(env.buildings[0].electrical_storage.soc[0])

    if interface == "flat":
        names = env.action_names[0]
        action = [0.0] * len(names)
        action[names.index("electrical_storage")] = bad
        actions = [action]
    else:
        actions = {"tables": {k: np.zeros(v.shape, dtype=v.dtype) for k, v in env.action_space["tables"].spaces.items()}}
        features = env.entity_specs["actions"]["building"]["features"]
        actions["tables"]["building"][0, features.index("electrical_storage")] = bad

    with pytest.raises(ValueError, match="must be finite"):
        env.step(actions)

    # Rejected before any device model ran.
    assert float(env.buildings[0].electrical_storage.soc[0]) == soc_before
    assert env.time_step == 0


def test_storage_charge_rejects_non_finite_energy():
    tracker = EpisodeTracker(0, 9)
    tracker.next_episode(10, False, False, 0)
    battery = Battery(capacity=5.0, nominal_power=5.0, initial_soc=0.5, episode_tracker=tracker, random_seed=0)
    battery.reset()

    with pytest.raises(ValueError, match="non-finite energy"):
        battery.charge(float("nan"))

    assert battery.soc[0] == pytest.approx(0.5)


def _checked_env():
    env = CityLearnEnv(str(MINUTE_EV_DEMO), central_agent=False, episode_time_steps=4, random_seed=0, physics_invariant_checks=True)
    env.reset()
    env.step([[0.0] * len(env.action_names[0])])
    return env


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_invariant_checker_treats_non_finite_state_as_a_violation(bad):
    env = _checked_env()
    t = env.time_step - 1
    env.buildings[0].electrical_storage.soc[t] = bad

    with pytest.raises(PhysicsInvariantError, match="Non-finite"):
        env._physics_invariant_service.assert_step_invariants(t)


def test_invariant_errors_remain_assertion_errors():
    env = _checked_env()
    t = env.time_step - 1
    env.buildings[0].electrical_storage.soc[t] = 1.5

    with pytest.raises(AssertionError, match="SOC out of bounds"):
        env._physics_invariant_service.assert_step_invariants(t)


def test_invariant_checks_still_run_under_python_optimize():
    code = f"""
        from citylearn.citylearn import CityLearnEnv
        from citylearn.internal.physics_invariants import PhysicsInvariantError
        env = CityLearnEnv({str(MINUTE_EV_DEMO)!r}, central_agent=False, episode_time_steps=4, random_seed=0,
                           physics_invariant_checks=True, offline=True)
        env.reset()
        env.step([[0.0] * len(env.action_names[0])])
        env.buildings[0].electrical_storage.soc[0] = 1.5
        try:
            env._physics_invariant_service.assert_step_invariants(0)
        except PhysicsInvariantError:
            print('RAISED')
    """
    result = _run_python(code, "-O")
    assert result.returncode == 0, result.stderr[-2000:]
    assert "RAISED" in result.stdout


# #242 EV deadline features


def test_ev_deadline_features_stay_within_their_observation_bounds():
    env = CityLearnEnv(str(PLUS_EVS), interface="entity", central_agent=True, episode_time_steps=41, random_seed=0)
    observations, _ = env.reset()
    space = env.observation_space["tables"]["charger"]
    features = env.entity_specs["tables"]["charger"]["features"]
    rng = np.random.default_rng(0)
    departures_with_gap = 0

    for _ in range(40):
        actions = {"tables": {k: rng.uniform(v.low, v.high).astype(v.dtype) for k, v in env.action_space["tables"].spaces.items()}}
        observations, *_ = env.step(actions)
        table = observations["tables"]["charger"]
        assert np.all(table <= space.high + 1e-6), [
            (features[c], float(table[:, c].max())) for c in range(table.shape[1]) if np.any(table[:, c] > space.high[:, c] + 1e-6)
        ]
        assert np.all(table >= space.low - 1e-6)
        hours = table[:, features.index("hours_until_departure")] if "hours_until_departure" in features else None
        if hours is not None:
            gap = table[:, features.index("energy_to_required_soc_kwh")]
            departures_with_gap += int(np.sum((hours == 0.0) & (gap > 0.0)))

    # The run includes departure steps with energy still missing, where the features used to reach ~1e7.
    assert departures_with_gap > 0


def test_departure_now_with_missing_energy_still_reads_as_more_than_full_power():
    env = CityLearnEnv(str(PLUS_EVS), interface="entity", central_agent=True, episode_time_steps=41, random_seed=0)
    observations, _ = env.reset()
    features = env.entity_specs["tables"]["charger"]["features"]
    if "hours_until_departure" not in features:
        pytest.skip("core bundle features not active")
    checked = 0

    for _ in range(40):
        actions = {"tables": {k: np.zeros(v.shape, dtype=v.dtype) for k, v in env.action_space["tables"].spaces.items()}}
        observations, *_ = env.step(actions)
        table = observations["tables"]["charger"]
        for row in table:
            if row[features.index("hours_until_departure")] == 0.0 and row[features.index("energy_to_required_soc_kwh")] > 0.0:
                assert row[features.index("min_required_action_normalized")] >= 1.0
                assert row[features.index("departure_feasibility_ratio")] > 1.0
                assert row[features.index("charging_slack_kw")] < 0.0
                checked += 1

    assert checked > 0


# #251 Process-wide state


def test_importing_citylearn_leaves_root_logging_and_numpy_errors_alone():
    code = """
        import logging, json, numpy as np
        root = logging.getLogger()
        before = (root.level, len(root.handlers), np.geterr())
        import citylearn.citylearn
        from citylearn.data import DataSet
        DataSet(offline=True)
        after = (root.level, len(root.handlers), np.geterr())
        print(json.dumps([before == after, logging.getLogger('citylearn').level]))
    """
    result = _run_python(code)
    assert result.returncode == 0, result.stderr[-2000:]
    # Root logger and NumPy untouched, and DataSet() without logging_level leaves the citylearn level alone.
    assert json.loads(result.stdout.strip().splitlines()[-1]) == [True, logging.NOTSET]


def test_library_warnings_still_reach_stderr_without_logging_configuration():
    result = _run_python("""
        import citylearn.citylearn, logging
        logging.getLogger('citylearn.citylearn').warning('visible warning')
        logging.getLogger('citylearn.citylearn').info('hidden info')
    """)
    assert result.returncode == 0, result.stderr[-2000:]
    assert 'visible warning' in result.stderr and 'hidden info' not in result.stderr


def test_building_an_env_keeps_the_applications_citylearn_log_level():
    logger = logging.getLogger("citylearn")
    previous = logger.level
    try:
        logger.setLevel(logging.WARNING)
        CityLearnEnv(str(MINUTE_EV_DEMO), episode_time_steps=4).reset()
        assert logger.level == logging.WARNING
    finally:
        logger.setLevel(previous)


# #252 CLI


def test_cli_list_command_prints_to_stdout_and_exits_zero():
    result = subprocess.run(
        [sys.executable, "-m", "citylearn", "list_default_time_series_variables"],
        capture_output=True, text=True, cwd=ROOT, timeout=300,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    lines = result.stdout.strip().splitlines()
    assert len(lines) > 1 and not result.stdout.lstrip().startswith("[")


def test_run_work_order_returns_non_zero_when_a_job_fails(tmp_path):
    from citylearn.__main__ import run_work_order

    ok = tmp_path / "ok.txt"
    work_order = tmp_path / "work_order.sh"
    work_order.write_text(f"touch {ok}\nexit 3\n", encoding="utf-8")
    assert run_work_order(work_order, max_workers=1, windows_system=False) == 1
    assert ok.is_file()

    work_order.write_text(f"touch {ok}\n", encoding="utf-8")
    assert run_work_order(work_order, max_workers=1, windows_system=False) == 0


def test_cli_exit_code_helper():
    from citylearn.__main__ import _exit_code

    assert _exit_code(None) == 0
    assert _exit_code(["a", "b"]) == 0
    assert _exit_code(2) == 2


# #253 Invalid configuration


def test_unknown_constructor_argument_is_rejected_with_a_suggestion():
    with pytest.raises(TypeError, match=r"physics_invariants_checks.*did you mean 'physics_invariant_checks'"):
        CityLearnEnv(str(MINUTE_EV_DEMO), physics_invariants_checks=True)


@pytest.mark.parametrize("window", [[(5, 2)], [(-3, 3)], [(1, 2, 3)], [("a", 2)]])
def test_invalid_episode_windows_are_rejected(window):
    with pytest.raises(ValueError, match="[Ee]pisode window"):
        CityLearnEnv(str(MINUTE_EV_DEMO), episode_time_steps=window)


@pytest.mark.parametrize("value, expected", [(False, False), ("false", False), ("no", False), ("0", False), ("true", True), (True, True)])
def test_local_trading_flag_parses_strings(value, expected):
    schema = _schema(PLUS_EVS)
    schema.setdefault("community_market", {})
    schema["community_market"]["enabled"] = True
    schema["community_market"]["local_trading_enabled"] = value
    env = CityLearnEnv(schema, episode_time_steps=4)
    assert env.community_market_local_enabled is expected


def _dynamic_schema_with(event_changes) -> dict:
    schema = _schema(DYNAMIC_DEMO)
    schema["topology_events"] = copy.deepcopy(schema["topology_events"])
    event_changes(schema["topology_events"])
    return schema


def test_topology_event_with_unknown_member_fails_at_construction():
    def change(events):
        events.append({"id": "bad_remove", "time_step": events[-1]["time_step"], "operation": "remove_member", "target_member_id": "Building_999"})

    with pytest.raises(ValueError, match="Unknown target_member_id 'Building_999'.*bad_remove"):
        CityLearnEnv(_dynamic_schema_with(change), interface="entity", topology_mode="dynamic", episode_time_steps=4)


def test_topology_events_for_members_not_loaded_are_still_accepted():
    schema = ROOT / "data" / "datasets" / "pt_rec_30" / "evaluation" / "rec_30_topology.json"
    env = CityLearnEnv(str(schema), buildings=["Member_002", "Member_003"], simulation_end_time_step=95, episode_time_steps=96)
    env.reset()
    assert [b.name for b in env.buildings] == ["Member_002", "Member_003"]


def test_invalid_topology_override_value_fails_at_construction():
    def change(events):
        event = next(e for e in events if e.get("operation") == "add_asset" and e.get("target_asset_type") == "electrical_storage")
        event.setdefault("overrides", {})["capacity"] = -5.0

    with pytest.raises(ValueError, match="Invalid override capacity"):
        CityLearnEnv(_dynamic_schema_with(change), interface="entity", topology_mode="dynamic", episode_time_steps=4)


def test_topology_override_with_unknown_key_fails_at_construction():
    def change(events):
        event = next(e for e in events if e.get("operation") == "add_asset" and e.get("target_asset_type") in {"pv", "electrical_storage"})
        event.setdefault("overrides", {})["nominal_powr"] = 99.0

    with pytest.raises(ValueError, match="Unknown override.*nominal_powr"):
        CityLearnEnv(_dynamic_schema_with(change), interface="entity", topology_mode="dynamic", episode_time_steps=4)


def test_invalid_override_value_raises_instead_of_being_ignored():
    from citylearn.internal.topology import CityLearnTopologyService

    tracker = EpisodeTracker(0, 9)
    tracker.next_episode(10, False, False, 0)
    battery = Battery(capacity=5.0, nominal_power=5.0, episode_tracker=tracker, random_seed=0)

    with pytest.raises(ValueError, match="Invalid override"):
        CityLearnTopologyService._apply_object_overrides(battery, {"capacity": -5.0})


def test_balance_audit_reads_the_parsed_local_trading_flag():
    from citylearn.internal.balance_audit import IndependentBalanceAudit

    schema = _schema(PLUS_EVS)
    schema.setdefault("community_market", {})
    schema["community_market"]["enabled"] = True
    schema["community_market"]["local_trading_enabled"] = "false"
    env = CityLearnEnv(schema, episode_time_steps=6, central_agent=False, random_seed=0)
    env.reset()
    with IndependentBalanceAudit(env) as audit:
        while not env.terminated:
            env.step([[0.5] * len(names) for names in env.action_names])
        assert audit.finish()["status"] == "pass"


def test_null_local_trading_flag_keeps_its_previous_meaning():
    schema = _schema(PLUS_EVS)
    schema.setdefault("community_market", {})
    schema["community_market"]["enabled"] = True
    schema["community_market"]["local_trading_enabled"] = None
    assert CityLearnEnv(schema, episode_time_steps=4).community_market_local_enabled is False


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_non_finite_entity_map_override_is_rejected(bad):
    env = CityLearnEnv(str(MINUTE_EV_DEMO), interface="entity", central_agent=False, episode_time_steps=4, random_seed=0)
    env.reset()

    with pytest.raises(ValueError, match="must be finite"):
        env.step({"map": {"building:Building_1": {"electrical_storage": bad}}})


# #254 Render directory


def test_render_output_defaults_to_the_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    env = CityLearnEnv(str(MINUTE_EV_DEMO), episode_time_steps=4)
    assert Path(env.render_output_root) == (tmp_path / "render_logs").resolve()

    env = CityLearnEnv(str(MINUTE_EV_DEMO), episode_time_steps=4, render_directory="my_runs")
    assert Path(env.render_output_root) == (tmp_path / "my_runs").resolve()


def test_multi_community_render_directory_resolves_against_the_working_directory(tmp_path, monkeypatch):
    from citylearn.multi_community import MultiCommunityEnv

    monkeypatch.chdir(tmp_path)
    assert MultiCommunityEnv._resolve_render_directory(None) == (tmp_path / "render_logs").resolve()
    assert MultiCommunityEnv._resolve_render_directory("runs") == (tmp_path / "runs").resolve()


# #255 Checkpoint loading


def test_lstm_checkpoints_load_tensors_only(tmp_path):
    torch = pytest.importorskip("torch")
    from citylearn.dynamics import LSTMDynamics

    state = {"weight": torch.ones(2)}
    wrapped = tmp_path / "wrapped.pth"
    torch.save({"model_state_dict": state}, wrapped)
    plain = tmp_path / "plain.pth"
    torch.save(state, plain)

    assert torch.equal(LSTMDynamics._load_checkpoint_state_dict(wrapped)["weight"], state["weight"])
    assert torch.equal(LSTMDynamics._load_checkpoint_state_dict(plain)["weight"], state["weight"])

    class _Payload:
        def __reduce__(self):
            return (os.system, ("echo PAYLOAD",))

    malicious = tmp_path / "malicious.pth"
    with open(malicious, "wb") as f:
        pickle.dump({"model_state_dict": _Payload()}, f)

    with pytest.raises(pickle.UnpicklingError):
        LSTMDynamics._load_checkpoint_state_dict(malicious)
