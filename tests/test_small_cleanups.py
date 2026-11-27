"""Signed peak ratios (#430), portfolio settings (#431) and the release tag check (#470)."""

from pathlib import Path

import numpy as np
import pytest

from citylearn.citylearn import CityLearnEnv
from citylearn.internal.kpi import CityLearnKPIService
from citylearn.multi_community import MultiCommunityEnv

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "tests/data/minute_ev_demo/schema.json"


def test_signed_ratio_of_a_negative_peak_reads_a_higher_peak_as_worse():
    # BAU daily-peak average -4 kW, control -2 kW: the control peak is higher, so the ratio is above 1.
    assert CityLearnKPIService._signed_ratio(-2.0, -4.0) == pytest.approx(1.5)
    assert CityLearnKPIService._signed_ratio(2.0, 4.0) == pytest.approx(0.5)


def test_v2_peak_ratios_to_the_bau_follow_the_signed_rule():
    env = CityLearnEnv(str(SCHEMA), central_agent=True, episode_time_steps=4, random_seed=0)
    try:
        env.reset(seed=0)
        done = False
        while not done:
            _, _, terminated, truncated, _ = env.step([np.zeros(env.action_space[0].shape[0], dtype="float32")])
            done = terminated or truncated
        table = env.evaluate_v2().set_index("cost_function")["value"]
    finally:
        env.close()

    for metric in ("peak_daily_average", "peak_all_time_average"):
        stem = f"district_energy_grid_shape_quality_{metric}"
        ratio = table[f"{stem}_to_business_as_usual_ratio"]
        expected = CityLearnKPIService._signed_ratio(table[f"{stem}_control_kw"], table[f"{stem}_business_as_usual_kw"])
        assert ratio == pytest.approx(expected)


def _community(community_id, **env_kwargs):
    kwargs = {"central_agent": True, "episode_time_steps": 4, "render_mode": "none", "random_seed": 0, **env_kwargs}
    return {"community_id": community_id, "schema": str(SCHEMA), "env_kwargs": kwargs}


@pytest.mark.parametrize("setting, value", [
    ("ev_departure_service_tolerance", 0.2),
    ("ev_departure_within_tolerance", 0.2),
    ("energy_provenance", False),
])
def test_portfolio_communities_must_share_the_ev_tolerances_and_provenance(setting, value):
    with pytest.raises(ValueError, match=setting):
        MultiCommunityEnv(communities=[_community("a"), _community("b", **{setting: value})])


def test_pypi_workflow_checks_the_release_tag_against_the_version():
    workflow = (ROOT / ".github/workflows/pypi_deploy.yml").read_text(encoding="utf-8")
    assert "Check that the tag matches the package version" in workflow
    assert 'if [ "$tag" != "v$version" ]' in workflow
