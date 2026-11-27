"""Property-based energy conservation (#289).

Hypothesis draws the step length, the physics and settlement versions, outages, phase limits, tariffs,
topology events and every action of the episode, and each run must keep the identities of the physics
invariant checker (``physics_invariant_checks=True`` raises ``PhysicsInvariantError``) and close the
independent flow balance of ``IndependentBalanceAudit``: energy, cash and carbon per member and for the
community. The cases are eight-step episodes on two small members, so each example takes about 0.1 s and
little memory. The search is derandomized, so CI and local runs try the same examples.
"""

import tempfile
from pathlib import Path

import numpy as np
import pytest

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import HealthCheck, given, settings, strategies as st  # noqa: E402

from citylearn.citylearn import CityLearnEnv  # noqa: E402
from citylearn.internal.balance_audit import IndependentBalanceAudit  # noqa: E402
from test_deferrable_appliance_integration import _zero_entity_payload  # noqa: E402
from test_independent_balances import scenario  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
MINUTE_EV_DEMO = ROOT / "tests" / "data" / "minute_ev_demo" / "schema.json"
STEPS = 7  # eight data rows, seven executed transitions
SETTINGS = settings(
    max_examples=40,
    deadline=None,
    derandomize=True,
    database=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)

unit = st.floats(min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False, width=32)
share = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False, width=32)
# Saturated commands are where clipping, efficiency curves and reserves meet, so they are drawn on purpose.
command = st.one_of(unit, st.sampled_from([-1.0, -0.5, 0.0, 0.5, 1.0]))


@st.composite
def community_cases(draw):
    events = None
    if draw(st.booleans()):
        kind = draw(st.sampled_from(["member", "asset"]))
        target = {"target_member_id": "Building_1"}
        if kind == "asset":
            target.update(target_asset_type="electrical_storage", target_asset_id="battery")
        leave = draw(st.integers(min_value=1, max_value=STEPS - 2))
        back = draw(st.integers(min_value=leave + 1, max_value=STEPS - 1))
        events = [
            dict(id="exit", time_step=leave, operation="remove_" + kind, **target),
            dict(id="return", time_step=back, operation="add_" + kind, **target),
        ]

    return dict(
        options=dict(
            seconds=draw(st.sampled_from([60, 300, 900, 1800, 3600])),
            version=draw(st.sampled_from([1, 2])),
            tariff=draw(st.booleans()),
            phase_limits=draw(st.booleans()),
            outage=draw(st.lists(st.sampled_from([0, 1]), min_size=8, max_size=8)),
            events=events,
        ),
        building=draw(st.lists(st.lists(command, min_size=2, max_size=2), min_size=STEPS, max_size=STEPS)),
        charger=draw(st.lists(share, min_size=STEPS, max_size=STEPS)),
        start=draw(st.lists(st.booleans(), min_size=STEPS, max_size=STEPS)),
    )


def _payload(env, case, t):
    payload = _zero_entity_payload(env)
    tables = payload["tables"]
    n = len(tables["building"])
    tables["building"][:, 0] = case["building"][t][:n]
    if len(tables["charger"]):
        tables["charger"][:, 0] = case["charger"][t]
    if len(tables["deferrable_appliance"]):
        tables["deferrable_appliance"][:, 0] = float(case["start"][t])
    return payload


@SETTINGS
@given(case=community_cases())
def test_random_community_episodes_conserve_energy_cash_and_carbon(case):
    with tempfile.TemporaryDirectory(prefix="citylearn-property-") as directory:
        env = scenario(Path(directory), **case["options"])
        try:
            env.reset()
            with IndependentBalanceAudit(env) as audit:
                t = 0
                while not env.terminated:
                    env.step(_payload(env, case, t))
                    t += 1
                result = audit.finish()
            assert t == STEPS
            assert result["status"] == "pass"
            assert result["completed_intervals"] == STEPS
            assert result["max_tolerance_fraction"] <= 1
        finally:
            env.close()


@SETTINGS
@given(
    seconds=st.sampled_from([60, 300, 900]),
    central_agent=st.booleans(),
    seed=st.integers(min_value=0, max_value=2**16),
)
def test_random_flat_actions_keep_the_physics_invariants(seconds, central_agent, seed):
    # The 15-minute EV demo on the flat interface, at its own and at shorter steps (compressed time).
    env = CityLearnEnv(
        str(MINUTE_EV_DEMO),
        central_agent=central_agent,
        seconds_per_time_step=seconds,
        time_step_ratio_mode="compress",
        physics_invariant_checks=True,
        random_seed=seed,
        offline=True,
    )
    try:
        env.reset(seed=seed)
        rng = np.random.default_rng(seed)
        while not env.terminated:
            actions = [
                rng.uniform(space.low, space.high).astype("float32") for space in env.action_space
            ]
            env.step(actions)
        assert env.time_step == env.time_steps - 1
    finally:
        env.close()
