"""Per-step histories live in preallocated buffers while public attributes return isolated lists (#290)."""

import copy
import gc
import json
import logging
import pickle
import subprocess
import sys
import tracemalloc
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("gymnasium")

from citylearn.__main__ import Simulator
from citylearn.citylearn import CityLearnEnv
from citylearn.internal.histories import RowHistory, ScalarHistory, _TrackedList
from citylearn.reward_function import RewardFunction

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "data/datasets/citylearn_challenge_2022_phase_all_plus_evs/schema.json"
PHASE_ALL_SCHEMA = ROOT / "data/datasets/citylearn_challenge_2022_phase_all/schema.json"
MINUTE_EV_SCHEMA = Path(__file__).resolve().parent / "data/minute_ev_demo/schema.json"
DYNAMIC_SCHEMA = ROOT / "data/datasets/citylearn_three_phase_dynamic_topology_demo/schema.json"


def _run(env, steps, rng=None):
    rewards = []

    for _ in range(steps):
        if rng is None:
            actions = [np.zeros(s.shape, dtype="float32") for s in env.action_space]
        else:
            actions = [rng.uniform(s.low, s.high).astype("float32") for s in env.action_space]

        _, reward, *_ = env.step(actions)
        rewards.append(reward)

    return rewards


# ---------------------------------------------------------------- unit tests of the containers


def test_scalar_history_matches_list_semantics():
    history, reference = ScalarHistory(2), []
    assert history.last() is None

    # append, overwrite the last entry, grow beyond the preallocated capacity
    for index, value in [(0, 1.5), (0, 2.5), (1, 3.5), (2, -0.0), (3, np.nan), (4, 7.0)]:
        value = np.float64(value)
        history.put(index, value)

        if len(reference) == index:
            reference.append(value)
        else:
            reference[index] = value

    assert len(history) == len(reference) == 5
    public = history.to_list()
    assert isinstance(public, list)
    assert [v.tobytes() for v in public] == [np.float64(v).tobytes() for v in (2.5, 3.5, -0.0, np.nan, 7.0)]
    assert all(type(v) is np.float64 for v in public)
    assert np.signbit(history[2]) and history[-1] == 7.0 and history.last() == 7.0
    assert type(history.last()) is np.float64
    assert history.to_list() is public
    public.append(99.0)
    assert history.to_list() is not public
    assert len(history.to_list()) == 5
    assert [v.tobytes() for v in history] == [v.tobytes() for v in reference]
    assert history.as_array().tobytes() == np.array(reference, dtype="float64").tobytes()


def test_scalar_history_irregular_writes_fall_back_to_list():
    history = ScalarHistory(4)
    history.put(0, np.float64(1.0))
    edited = history.to_list()
    edited[0] = 99.0
    edited.append(88.0)
    assert history.to_list() == [1.0]
    # Overwriting a buffered entry after reading to_list() invalidates the cache.
    cached = history.to_list()
    assert cached == [1.0]
    history.put(0, np.float64(1.5))
    assert history.to_list() == [1.5]
    history.put(0, np.float64(1.0))
    history.put(3, np.float64(4.0))  # gap: list rule pads with 0.0 from authoritative buffer
    assert history.to_list() == [1.0, 0.0, 0.0, 4.0]
    history.put(1, 5.0)  # a Python float is not stored in the buffer; list rule truncates after index 1
    assert history.to_list() == [1.0, 0.0, 5.0]
    post_fallback = history.to_list()
    post_fallback[0] = -77.0
    post_fallback.clear()
    assert history.to_list() == [1.0, 0.0, 5.0]
    assert history.last() == 5.0
    assert len(history) == 3


def test_row_history_returns_exactly_what_was_appended():
    history = RowHistory(1)
    assert history.last() is None
    rows = [[], [1.0, 2.0], [np.float64(3.0)] * 3, [float("inf")], [], [-0.0, 1e-320, 5e300, 0.1, 0.2]]

    for row in rows:
        history.append(row)

    out = history.to_list()
    assert out == rows and isinstance(out, list)
    assert all(isinstance(r, list) for r in out)
    assert out is history.to_list()
    assert [[type(v) for v in row] for row in out] == [[type(v) for v in row] for row in rows]
    assert np.signbit(out[-1][0])
    assert len(history) == len(rows) and list(history.rows(2)) == rows[2:]
    assert history[1] == [1.0, 2.0] and history[-1] == rows[-1] and history.last() == rows[-1]
    out[1][0] = 999.0
    assert history.to_list() is not out
    assert history.to_list() == rows


def test_row_history_unsupported_rows_fall_back_to_list():
    history = RowHistory(4)
    odd = np.array([1.0, 2.0])
    history.append([1.0])
    history.append(odd)  # not a list: triggers fallback and stores an isolated copy
    odd[0] = -5.0
    history.append([1, 2.5])  # mixed element types
    history.append([2.0])
    out = history.to_list()
    assert out[0] == [1.0] and type(out[1]) is np.ndarray and np.array_equal(out[1], np.array([1.0, 2.0]))
    assert out[2] == [1, 2.5] and out[3] == [2.0]
    assert type(out[2][0]) is int
    out[1][0] = 999.0
    out[2][0] = 888
    assert np.array_equal(history.to_list()[1], np.array([1.0, 2.0]))
    assert history.to_list()[2] == [1, 2.5]


def test_history_list_detaches_across_all_mutating_list_methods():
    ops = [
        lambda lst: lst.__setitem__(0, -1.0),
        lambda lst: lst.__delitem__(0),
        lambda lst: lst.append(9.0),
        lambda lst: lst.extend([9.0]),
        lambda lst: lst.insert(0, 9.0),
        lambda lst: lst.pop(),
        lambda lst: lst.remove(lst[0]),
        lambda lst: lst.clear(),
        lambda lst: lst.reverse(),
        lambda lst: lst.sort(),
        lambda lst: lst.__iadd__([9.0]),
        lambda lst: lst.__imul__(2),
    ]

    for op in ops:
        scalar = ScalarHistory(4)
        scalar.put(0, np.float64(2.0))
        scalar.put(1, np.float64(1.0))
        s_view = scalar.to_list()
        op(s_view)
        assert scalar.to_list() == [2.0, 1.0]

        rows = RowHistory(4)
        rows.append([2.0, 1.0])
        r_view = rows.to_list()
        op(r_view[0])
        assert rows.to_list() == [[2.0, 1.0]]

    rows = RowHistory(4)
    rows.append([1.0, 2.0])
    shallow = copy.copy(rows.to_list())
    deep = copy.deepcopy(rows.to_list())
    assert type(shallow) is list and type(deep) is list
    deep[0][0] = 77.0
    assert rows.to_list() == [[1.0, 2.0]]


def test_history_list_is_isolated_before_and_after_writes():
    scalar, rows = ScalarHistory(4), RowHistory(4)
    scalar.put(0, np.float64(1.0))
    rows.append([1.0, 2.0])
    s_ref = scalar.to_list()
    s_ref.append(99.0)
    s_ref[0] = 7.0
    r_ref = rows.to_list()
    r_ref[0].append(9.0)
    r_ref[0][0] = 8.0
    # Even before the next write, subsequent reads must return the unedited authoritative values.
    assert scalar.to_list() == [1.0]
    assert rows.to_list() == [[1.0, 2.0]]
    scalar.put(1, np.float64(2.0))
    rows.append([3.0])
    assert scalar.to_list() == [1.0, 2.0]
    assert rows.to_list() == [[1.0, 2.0], [3.0]]


def test_incremental_monitoring_reads_extend_in_constant_time_per_step(monkeypatch):
    rows = RowHistory(256)
    rows.append([])
    net = ScalarHistory(256)

    row_builds = 0
    orig_tracked_row = RowHistory._tracked_row

    def _counting_tracked_row(self, index, owner):
        nonlocal row_builds
        row_builds += 1
        return orig_tracked_row(self, index, owner)

    monkeypatch.setattr(RowHistory, "_tracked_row", _counting_tracked_row)

    for t in range(200):
        rows.append([float(t), float(t + 1)])
        net.put(t, np.float64(t * 1.5))
        assert rows.to_list()[-1] == [float(t), float(t + 1)]
        assert net.to_list()[-1] == np.float64(t * 1.5)

    # Initial read built rows 0 and 1; each of the remaining 199 steps built only its 1 new row.
    assert row_builds == 201


def test_row_history_widening_copies_only_executed_prefix():
    script = """
import json
import os
import sys
from citylearn.internal.histories import RowHistory

def rss_bytes():
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
                ("PrivateUsage", ctypes.c_size_t),
            ]

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        k32.K32GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(PROCESS_MEMORY_COUNTERS_EX),
            wintypes.DWORD,
        ]
        k32.K32GetProcessMemoryInfo.restype = wintypes.BOOL
        pmc = PROCESS_MEMORY_COUNTERS_EX()
        pmc.cb = ctypes.sizeof(pmc)
        assert k32.K32GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb)
        return int(pmc.WorkingSetSize), int(pmc.PeakWorkingSetSize)

    status = "/proc/self/status"
    if os.path.exists(status):
        vals = {}
        with open(status, encoding="utf-8") as fh:
            for line in fh:
                if line.startswith(("VmRSS:", "VmHWM:")):
                    k, v = line.split(":", 1)
                    vals[k] = int(v.strip().split()[0]) * 1024
        if "VmRSS" in vals and "VmHWM" in vals:
            return vals["VmRSS"], vals["VmHWM"]

    import resource
    peak = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    if sys.platform != "darwin":
        peak *= 1024
    return peak, peak

rss0, peak0 = rss_bytes()
rows = RowHistory(2_102_400)
rows.append([0.0] * 17)
rows.append([0.0] * 18)
rss1, peak1 = rss_bytes()
assert len(rows) == 2
assert rows[0] == [0.0] * 17
assert rows[1] == [0.0] * 18
print(json.dumps({"rss_delta": rss1 - rss0, "peak_delta": peak1 - peak0}))
"""
    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=True,
    )
    stats = json.loads(proc.stdout.strip().splitlines()[-1])
    # Widening 2,102,400 reserved rows from 17 to 18 columns used to fault ~289 MiB of RSS.
    assert stats["rss_delta"] < 16 * 1024 * 1024
    assert stats["peak_delta"] < 16 * 1024 * 1024


# ---------------------------------------------------------------- environment behaviour


@pytest.fixture(scope="module")
def stepped_env():
    env = CityLearnEnv(str(SCHEMA), episode_time_steps=8, random_seed=0)
    env.reset(seed=0)
    step_rewards = _run(env, 5, np.random.default_rng(0))
    yield env, step_rewards
    env.close()


def test_public_histories_are_lists_with_executed_length(stepped_env):
    env, _ = stepped_env
    assert isinstance(env.rewards, list) and type(env.rewards) is _TrackedList
    assert type(env.rewards) is not list and len(env.rewards) == 6
    assert env.rewards[0] == []

    for series in (env.net_electricity_consumption, env.net_electricity_consumption_cost,
                   env.net_electricity_consumption_emission):
        assert isinstance(series, list) and type(series) is _TrackedList
        assert type(series) is not list and len(series) == 5
        assert all(type(v) is np.float64 for v in series)

    assert isinstance(env.rewards[1], list) and type(env.rewards[1]) is _TrackedList
    assert all(type(v) is float for v in env.rewards[1])
    assert len(env.rewards[1]) == len(env.buildings)


def test_histories_support_list_operations(stepped_env):
    env, _ = stepped_env
    assert env.rewards[1:3] == [env.rewards[1], env.rewards[2]]
    assert env.net_electricity_consumption[-2:] == env.net_electricity_consumption[3:]
    assert env.net_electricity_consumption == list(env.net_electricity_consumption)
    assert json.loads(json.dumps(env.rewards)) == env.rewards
    assert json.loads(json.dumps(env.net_electricity_consumption)) == [float(v) for v in env.net_electricity_consumption]
    assert env.net_electricity_consumption.copy() == env.net_electricity_consumption


def test_histories_equal_the_values_the_simulation_returned(stepped_env):
    env, step_rewards = stepped_env
    # exact equality with what step() returned and with the sum of the building series
    assert env.rewards[1:] == [list(r) for r in step_rewards]

    for t in range(5):
        for name in ("net_electricity_consumption", "net_electricity_consumption_cost",
                     "net_electricity_consumption_emission"):
            expected = sum((getattr(b, name)[t] for b in env.buildings), np.float64(0))
            assert getattr(env, name)[t].tobytes() == np.float64(expected).tobytes()


def test_mutating_a_returned_list_does_not_change_the_environment():
    env = CityLearnEnv(str(SCHEMA), episode_time_steps=6, random_seed=0)

    try:
        env.reset(seed=0)
        _run(env, 2)
        expected = [list(r) for r in env.rewards]
        net = list(env.net_electricity_consumption)
        r_mut = env.rewards
        r_mut.append([1.0])
        r_mut[1][0] = 1e9
        env.rewards[-1][0] = 1e9
        n_mut = env.net_electricity_consumption
        n_mut.clear()
        # Immediate public reads before the next step stay unedited.
        assert env.rewards == expected
        assert env.net_electricity_consumption == net
        _run(env, 1)
        assert len(env.rewards) == 4 and env.rewards[1:3] == expected[1:3]
        assert env.net_electricity_consumption[:2] == net[:2]
        assert len(env.net_electricity_consumption) == 3
    finally:
        env.close()


class _MixedTypeCentralReward(RewardFunction):
    """Returns [1.0], then [2], then [2] across three executed central-agent actions."""

    def __init__(self, env_metadata):
        super().__init__(env_metadata)
        self._step = 0

    def reset(self):
        self._step = 0

    def calculate(self, observations):
        self._step += 1
        return [1.0] if self._step == 1 else [2]


def test_fallback_transition_and_post_fallback_edits_keep_histories_and_summary_intact():
    env = CityLearnEnv(
        str(SCHEMA),
        central_agent=True,
        episode_time_steps=4,
        reward_function=_MixedTypeCentralReward,
        random_seed=0,
    )

    try:
        env.reset(seed=0)
        zero_action = [np.zeros(s.shape, dtype="float32") for s in env.action_space]

        # Action 1 -> [1.0], stored in the float64 buffer.
        env.step(zero_action)
        assert env._rewards_history._items is None
        env.rewards[-1][0] = 99.0
        cached_attempt = env.rewards
        cached_attempt[-1][0] = 88.0
        cached_attempt.append([77.0])
        assert env.rewards == [[], [1.0]]
        assert env.rewards[-1] == [1.0]

        # Action 2 -> [2] (int), triggering _fallback() to plain-list storage.
        env.step(zero_action)
        assert env._rewards_history._items is not None
        assert env._rewards_history._buffer is None
        assert env.rewards == [[], [1.0], [2]]
        assert type(env.rewards[-1][0]) is int

        # Edits after transitioning to list storage must also leave internal history untouched.
        post_fallback = env.rewards
        post_fallback[1][0] = 66.0
        post_fallback[-1][0] = 55
        post_fallback.append([44])
        env.rewards[-1][0] = 33
        last_edit = env.rewards[-1]
        last_edit[0] = 22
        assert env.rewards == [[], [1.0], [2]]
        assert env.rewards[-1] == [2]

        # Action 3 -> [2], completing the episode; summary sum must be 1.0 + 2 + 2 == 5.0.
        env.step(zero_action)
        assert env.terminated
        assert env.rewards == [[], [1.0], [2], [2]]
        assert env.episode_rewards[-1]["sum"] == pytest.approx(5.0)

        # Edits after episode termination also do not affect subsequent public reads.
        env.rewards[-1][0] = 99.0
        assert env.rewards == [[], [1.0], [2], [2]]
    finally:
        env.close()


class _CustomRewardRow(list):
    pass


class _CustomRowRewardFunction(RewardFunction):
    def __init__(self, env_metadata):
        super().__init__(env_metadata)
        self._step = 0

    def reset(self):
        self._step = 0

    def calculate(self, observations):
        self._step += 1
        return _CustomRewardRow([float(self._step)])


def test_custom_list_subclass_reward_rows_preserve_type_and_isolation():
    env = CityLearnEnv(
        str(MINUTE_EV_SCHEMA),
        central_agent=True,
        episode_time_steps=4,
        reward_function=_CustomRowRewardFunction,
        random_seed=5,
    )

    try:
        env.reset(seed=5)
        zero_action = [np.zeros(s.shape, dtype="float32") for s in env.action_space]

        _, step_r1, *_ = env.step(zero_action)
        assert type(step_r1) is _CustomRewardRow and step_r1 == [1.0]
        assert env._rewards_history._items is not None
        assert type(env.rewards[-1]) is _CustomRewardRow and env.rewards[-1] == [1.0]
        assert type(env.rewards[-1]) is _CustomRewardRow and env.rewards[-1] == [1.0]

        # Mutate the step return, public history row, outer list, and rewards[-1] copy.
        step_r1[0] = 999.0
        step_r1.append(555.0)
        last_view = env.rewards[-1]
        last_view[0] = 888.0
        last_view.append(444.0)
        full_view = env.rewards
        full_view.append(_CustomRewardRow([777.0]))
        env.rewards[-1][0] = 666.0

        assert env.rewards == [[], _CustomRewardRow([1.0])]
        assert type(env.rewards[-1]) is _CustomRewardRow
        assert env.rewards[-1] == _CustomRewardRow([1.0])
        assert type(env.rewards[-1]) is _CustomRewardRow

        env.step(zero_action)
        env.step(zero_action)
        assert env.terminated
        assert [type(r) for r in env.rewards] == [list, _CustomRewardRow, _CustomRewardRow, _CustomRewardRow]
        assert env.rewards == [[], [1.0], [2.0], [3.0]]
        assert env.episode_rewards[-1]["sum"] == pytest.approx(6.0)
    finally:
        env.close()


def test_subclass_public_district_series_override_honored_across_evaluator_and_shortcuts(tmp_path, caplog):
    class _ScaledDistrictEnv(CityLearnEnv):
        reporting_scale = 1.0

        @property
        def net_electricity_consumption(self):
            base = super().net_electricity_consumption
            return None if base is None else [v * self.reporting_scale for v in base]

        @property
        def net_electricity_consumption_cost(self):
            base = super().net_electricity_consumption_cost
            return None if base is None else [v * self.reporting_scale for v in base]

        @property
        def net_electricity_consumption_emission(self):
            base = super().net_electricity_consumption_emission
            return None if base is None else [v * self.reporting_scale for v in base]

        @property
        def rewards(self):
            base = super().rewards
            if base is None:
                return None
            return [
                [v * self.reporting_scale for v in row]
                for row in base
            ]

    env = _ScaledDistrictEnv(
        str(MINUTE_EV_SCHEMA),
        episode_time_steps=5,
        random_seed=5,
        render_mode="end",
        render_directory=str(tmp_path),
        metrics_log_interval=1,
    )

    try:
        env.reset(seed=5)
        zero_actions = [np.zeros(s.shape, dtype="float32") for s in env.action_space]
        while not env.terminated:
            env.step(zero_actions)

        base_import = sum(max(float(v), 0.0) for v in env.net_electricity_consumption)
        assert base_import == pytest.approx(4.2, abs=1e-4)

        # Enable post-rollout reporting scale on the subclass getter.
        env.reporting_scale = 2.0
        scaled_import = sum(max(float(v), 0.0) for v in env.net_electricity_consumption)
        assert scaled_import == pytest.approx(8.4, abs=1e-4)

        df = env.evaluate_v2(include_business_as_usual=False)
        import_row = df[
            (df["level"] == "district")
            & (df["cost_function"] == "district_energy_grid_total_import_control_kwh")
        ]
        assert float(import_row["value"].iloc[0]) == pytest.approx(scaled_import, rel=1e-6)

        # Console / dict rendering, BAU district row helper, DR power lookup, and periodic logging.
        state_dict = env.as_dict()
        assert state_dict["Net Electricity Consumption-kWh"] == pytest.approx(float(env.net_electricity_consumption[-1]))
        assert state_dict["Price-$"] == pytest.approx(float(env.net_electricity_consumption_cost[-1]))
        assert state_dict["CO2-kg_co2"] == pytest.approx(float(env.net_electricity_consumption_emission[-1]))

        district_row = env._episode_exporter._business_as_usual_district_row(env, 0, rows=[])
        assert district_row["net_electricity_consumption_kwh"] == pytest.approx(float(env.net_electricity_consumption[0]))
        assert district_row["net_electricity_consumption_cost"] == pytest.approx(float(env.net_electricity_consumption_cost[0]))
        assert district_row["net_electricity_consumption_emission_kgco2"] == pytest.approx(
            float(env.net_electricity_consumption_emission[0])
        )

        step_hours = float(env.seconds_per_time_step) / 3600.0
        assert env._demand_response_service._current_district_power_kw(0) == pytest.approx(
            float(env.net_electricity_consumption[0]) / step_hours
        )

        with caplog.at_level(logging.INFO, logger="citylearn.citylearn"):
            env._maybe_log_periodic_metrics()
        expected_net = float(env.net_electricity_consumption[-1])
        assert any(f"net_kwh={expected_net:.5f}" in rec.message for rec in caplog.records)

        # Episode render export and terminal reward summary also honor subclass getters.
        env._export_episode_render_data(env.time_step - 1)
        community_csv = next(tmp_path.rglob("exported_data_community_ep*.csv")).read_text(encoding="utf-8")
        assert f"{float(env.net_electricity_consumption[0])}" in community_csv

        unscaled_sum = float(env.episode_rewards[-1]["sum"])
        env.reset(seed=5)
        while not env.terminated:
            env.step(zero_actions)
        assert float(env.episode_rewards[-1]["sum"]) == pytest.approx(unscaled_sum * 2.0, rel=1e-6)
    finally:
        env.close()


def test_dynamic_topology_early_join_on_long_horizon_keeps_unwritten_tail_cold():
    script = """
import json
import os
from pathlib import Path
import sys
import numpy as np
from citylearn.citylearn import CityLearnEnv
from citylearn.internal.histories import RowHistory

def rss_bytes():
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
                ("PrivateUsage", ctypes.c_size_t),
            ]

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        k32.K32GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(PROCESS_MEMORY_COUNTERS_EX),
            wintypes.DWORD,
        ]
        k32.K32GetProcessMemoryInfo.restype = wintypes.BOOL
        pmc = PROCESS_MEMORY_COUNTERS_EX()
        pmc.cb = ctypes.sizeof(pmc)
        assert k32.K32GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb)
        return int(pmc.WorkingSetSize), int(pmc.PeakWorkingSetSize)

    status = "/proc/self/status"
    if os.path.exists(status):
        vals = {}
        with open(status, encoding="utf-8") as fh:
            for line in fh:
                if line.startswith(("VmRSS:", "VmHWM:")):
                    k, v = line.split(":", 1)
                    vals[k] = int(v.strip().split()[0]) * 1024
        if "VmRSS" in vals and "VmHWM" in vals:
            return vals["VmRSS"], vals["VmHWM"]

    import resource
    peak = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    if sys.platform != "darwin":
        peak *= 1024
    return peak, peak

schema_path = Path(sys.argv[1])
schema = json.loads(schema_path.read_text(encoding="utf-8"))
schema["root_directory"] = str(schema_path.parent)
schema["interface"] = "entity"
schema["topology_mode"] = "dynamic"
schema["topology_events"] = [
    {"id": "join_early", "time_step": 2, "operation": "add_member", "target_member_id": "Building_18"}
]

env = CityLearnEnv(schema, interface="entity", topology_mode="dynamic", episode_time_steps=8760, random_seed=0)
try:
    env.reset(seed=0)
    # Reserve a full 15-second-year reward buffer to verify early member join never faults unwritten rows.
    env._rewards_history = RowHistory(2_102_400)
    env._rewards_history.append([])
    rss0, peak0 = rss_bytes()
    for _ in range(4):
        tables = env.action_space["tables"]
        actions = {
            "tables": {
                name: np.zeros(space.shape, dtype="float32")
                for name, space in tables.items()
                if name in {"building", "charger", "deferrable_appliance"}
            }
        }
        env.step(actions)
    rss1, peak1 = rss_bytes()
    widths = [len(row) for row in env._rewards_history.rows(1)]
    assert widths == [17, 17, 18, 18], widths
    print(json.dumps({"rss_delta": rss1 - rss0, "peak_delta": peak1 - peak0, "widths": widths}))
finally:
    env.close()
"""
    proc = subprocess.run(
        [sys.executable, "-c", script, str(DYNAMIC_SCHEMA)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=True,
    )
    stats = json.loads(proc.stdout.strip().splitlines()[-1])
    assert stats["widths"] == [17, 17, 18, 18]
    assert stats["rss_delta"] < 32 * 1024 * 1024
    assert stats["peak_delta"] < 32 * 1024 * 1024


def test_streaming_and_latest_readers_do_not_populate_public_list_cache():
    rows = RowHistory(501)
    rows.append([])
    net = ScalarHistory(500)
    cost = ScalarHistory(500)
    emission = ScalarHistory(500)

    for t in range(500):
        rows.append([float(t + j) for j in range(17)])
        val = np.float64(t * 0.5)
        net.put(t, val)
        cost.put(t, val)
        emission.put(t, val)

    gc.collect()
    tracemalloc.start()
    before_cur, _ = tracemalloc.get_traced_memory()
    assert len(rows.last()) == 17
    assert sum(len(r) for r in rows.rows(1)) == 500 * 17
    assert float(net.as_array().sum()) > 0.0
    assert float(cost.as_array().sum()) > 0.0
    assert float(emission.as_array().sum()) > 0.0
    gc.collect()
    after_cur, _ = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert rows._cache is None
    assert net._cache is None
    assert cost._cache is None
    assert emission._cache is None
    assert after_cur - before_cur < 16_384


def test_reset_clears_histories_in_every_episode():
    env = CityLearnEnv(str(SCHEMA), episode_time_steps=5, random_seed=0)

    try:
        for episode in range(3):
            env.reset(seed=1)
            assert env.rewards == [[]] and len(env.net_electricity_consumption) == 1
            step_rewards = _run(env, 4, np.random.default_rng(1))
            assert env.terminated and len(env.rewards) == 5
            assert env.rewards[1:] == [list(r) for r in step_rewards]

            for t in range(4):
                expected = sum((b.net_electricity_consumption[t] for b in env.buildings), np.float64(0))
                assert env.net_electricity_consumption[t].tobytes() == np.float64(expected).tobytes()

            assert len(env.episode_rewards) == episode + 1
    finally:
        env.close()


def test_history_grows_beyond_the_preallocated_episode_length():
    env = CityLearnEnv(str(SCHEMA), episode_time_steps=6, random_seed=0)

    try:
        env.reset(seed=0)
        _run(env, 4)
        reference = ([list(r) for r in env.rewards], list(env.net_electricity_consumption))
        # smaller preallocation than the steps taken forces doubling, with the same contents
        env._rewards_history = RowHistory(1)
        env._net_electricity_consumption_history = ScalarHistory(1)

        for row in reference[0]:
            env._rewards_history.append(row)

        for index, value in enumerate(reference[1]):
            env._net_electricity_consumption_history.put(index, value)

        assert env.rewards == reference[0] and env.net_electricity_consumption == reference[1]
    finally:
        env.close()


def test_cli_style_json_export_is_unchanged(stepped_env, tmp_path, monkeypatch):
    env, _ = stepped_env
    text = json.dumps({'episode_rewards': env.rewards})
    assert json.loads(text)['episode_rewards'][0] == []
    assert text == json.dumps({'episode_rewards': [[]] + [list(r) for r in env.rewards[1:]]})

    # Verify CLI Simulator evaluation streams episode_rewards without calling RowHistory.to_list().
    called_to_list = False
    orig_to_list = RowHistory.to_list

    def _spy_to_list(self):
        nonlocal called_to_list
        called_to_list = True
        return orig_to_list(self)

    monkeypatch.setattr(RowHistory, "to_list", _spy_to_list)
    Simulator.evaluate(
        schema=str(SCHEMA),
        agent_name="citylearn.agents.baseline.ZeroActionAgent",
        evaluation_episode_time_steps=(0, 4),
        env_kwargs={"offline": True},
        output_directory=str(tmp_path),
        simulation_id="stream_check",
        random_seed=0,
    )
    assert not called_to_list
    exported = json.loads((tmp_path / "stream_check-evaluation.json").read_text(encoding="utf-8"))
    assert len(exported["episode_rewards"]) == 5
    assert exported["episode_rewards"][0] == []


def test_kept_history_references_do_not_grow_until_property_is_reread():
    env = CityLearnEnv(str(PHASE_ALL_SCHEMA), episode_time_steps=12, random_seed=0)

    try:
        env.reset(seed=0)
        kept_rewards = env.rewards
        kept_net = env.net_electricity_consumption
        kept_cost = env.net_electricity_consumption_cost
        kept_emission = env.net_electricity_consumption_emission
        assert len(kept_rewards) == 1
        assert len(kept_net) == len(kept_cost) == len(kept_emission) == 1

        _run(env, 10)
        # Kept references stay at the length they had when read while step() advances.
        assert len(kept_rewards) == 1
        assert len(kept_net) == len(kept_cost) == len(kept_emission) == 1

        # Re-reading the properties returns the updated executed histories.
        assert len(env.rewards) == 11
        assert len(env.net_electricity_consumption) == 10
        assert len(env.net_electricity_consumption_cost) == 10
        assert len(env.net_electricity_consumption_emission) == 10
    finally:
        env.close()


@pytest.mark.parametrize("protocol", list(range(pickle.HIGHEST_PROTOCOL + 1)))
def test_returned_histories_pickle_as_plain_lists_across_protocols(stepped_env, protocol):
    env, _ = stepped_env

    unpickled_rewards = pickle.loads(pickle.dumps(env.rewards, protocol=protocol))
    assert type(unpickled_rewards) is list
    assert all(type(row) is list for row in unpickled_rewards)
    assert unpickled_rewards == env.rewards
    assert [[type(v) for v in row] for row in unpickled_rewards] == [
        [type(v) for v in row] for row in env.rewards
    ]

    for name in (
        "net_electricity_consumption",
        "net_electricity_consumption_cost",
        "net_electricity_consumption_emission",
    ):
        series = getattr(env, name)
        unpickled_series = pickle.loads(pickle.dumps(series, protocol=protocol))
        assert type(unpickled_series) is list
        assert all(type(v) is np.float64 for v in unpickled_series)
        assert [v.tobytes() for v in unpickled_series] == [v.tobytes() for v in series]

    # Uninitialized _TrackedList slot safety + fallback rows (including custom list subclass).
    bare = _TrackedList.__new__(_TrackedList)
    bare.extend([1.0, 2.0])
    assert list(bare) == [1.0, 2.0]

    fallback_rows = RowHistory(4)
    fallback_rows.append(_CustomRewardRow([1.5]))
    fallback_rows.append([1, 2.5])
    unpickled_fallback = pickle.loads(pickle.dumps(fallback_rows.to_list(), protocol=protocol))
    assert type(unpickled_fallback) is list
    assert type(unpickled_fallback[0]) is _CustomRewardRow and unpickled_fallback[0] == [1.5]
    assert type(unpickled_fallback[1]) is list and unpickled_fallback[1] == [1, 2.5]

    # Pickling a large-capacity history drops _cache and serializes only the executed prefix.
    large_rows = RowHistory(2_102_400)
    large_rows.append([1.0] * 17)
    large_rows.append([2.0] * 18)
    _ = large_rows.to_list()[-1]
    assert large_rows._cache is not None
    payload = pickle.dumps(large_rows, protocol=protocol)
    assert len(payload) < 16_384
    restored_rows = pickle.loads(payload)
    assert restored_rows._cache is None
    assert restored_rows._capacity == 2_102_400
    assert restored_rows.to_list() == [[1.0] * 17, [2.0] * 18]


@pytest.mark.parametrize("mode", ["pickle_default", "pickle_highest", "deepcopy"])
def test_stepped_env_pickles_and_continues_identically_after_history_reads(mode):
    env = CityLearnEnv(str(PHASE_ALL_SCHEMA), episode_time_steps=10, random_seed=0)
    env2 = None

    try:
        env.reset(seed=0)
        zero_actions = [np.zeros(s.shape, dtype="float32") for s in env.action_space]
        for _ in range(3):
            env.step(zero_actions)

        # Populate _cache on all four histories before serializing the environment.
        _ = env.rewards[-1]
        _ = env.net_electricity_consumption[-1]
        _ = env.net_electricity_consumption_cost[-1]
        _ = env.net_electricity_consumption_emission[-1]
        assert env._rewards_history._cache is not None
        assert env._net_electricity_consumption_history._cache is not None

        if mode == "deepcopy":
            env2 = copy.deepcopy(env)
        elif mode == "pickle_default":
            env2 = pickle.loads(pickle.dumps(env))
        else:
            env2 = pickle.loads(pickle.dumps(env, protocol=pickle.HIGHEST_PROTOCOL))

        assert env2._rewards_history._cache is None
        assert env2._net_electricity_consumption_history._cache is None
        assert env2._net_electricity_consumption_cost_history._cache is None
        assert env2._net_electricity_consumption_emission_history._cache is None

        while not env.terminated:
            env.step(zero_actions)
            env2.step([np.zeros(s.shape, dtype="float32") for s in env2.action_space])

        assert env2.terminated
        assert env2.rewards == env.rewards
        assert [[type(v) for v in row] for row in env2.rewards] == [
            [type(v) for v in row] for row in env.rewards
        ]
        for name in (
            "net_electricity_consumption",
            "net_electricity_consumption_cost",
            "net_electricity_consumption_emission",
        ):
            assert [v.tobytes() for v in getattr(env2, name)] == [v.tobytes() for v in getattr(env, name)]

        assert env2.episode_rewards == env.episode_rewards
        expected_kpi = env.evaluate_v2(include_business_as_usual=False)
        actual_kpi = env2.evaluate_v2(include_business_as_usual=False)
        merged = expected_kpi.merge(
            actual_kpi,
            on=["cost_function", "name"],
            suffixes=("_expected", "_actual"),
            how="outer",
        )
        assert len(merged) == len(expected_kpi) == len(actual_kpi)
        assert np.allclose(
            merged["value_expected"].astype(float),
            merged["value_actual"].astype(float),
            rtol=1e-9,
            atol=1e-9,
            equal_nan=True,
        )
    finally:
        env.close()
        if env2 is not None:
            env2.close()
