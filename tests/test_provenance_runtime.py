
import numpy as np
import pytest

from citylearn.citylearn import CityLearnEnv
from citylearn.internal.experiment import experiment_manifest
from test_market_phase_invariants import _write_residual_market_schema


def test_market_and_bau_emissions_share_the_same_boundary(tmp_path):
    schema = _write_residual_market_schema(tmp_path)
    env = CityLearnEnv(str(schema), central_agent=True, random_seed=0)
    env.reset()
    while not env.terminated:
        env.step([np.zeros(env.action_space[0].shape)])
    frame = env.evaluate_v2()
    metrics = frame[frame.name == 'District'].set_index('cost_function').value
    key = 'district_energy_provenance_external_purchase_emissions_kgco2'
    assert metrics[key] == pytest.approx(.2)
    assert metrics[key.replace('_kgco2', '_business_as_usual_kgco2')] == pytest.approx(.2)
    assert metrics[key.replace('_kgco2', '_delta_to_business_as_usual_kgco2')] == pytest.approx(0.)
    assert frame.attrs['energy_accounting']['kpi_definition_version'] == '1.9.0'
    manifest = experiment_manifest(env)
    assert manifest['community_market']['grid_export_price'] == 0.
    assert manifest['community_market']['local_price_ratio_to_grid_import'] == .8
    assert manifest['random_seed'] == 0
    assert manifest['git_commit']
    assert manifest['data_files_sha256']
    assert not manifest['unresolved_file_references']
    # Read-only queries preserve all counters and source identities.
    assert manifest['source_destinations'] == experiment_manifest(env)['source_destinations']
    env.close()


def test_passive_ledger_preserves_real_trajectories_and_no_feedback_path(tmp_path):
    from test_storage_reserve_conservation import _arrival_env, _actions
    environments = []
    for index in range(3):
        directory = tmp_path/str(index)
        directory.mkdir()
        environments.append(_arrival_env(directory, True, 'flat', 900))
    passive, muted, sidecar = environments
    # Disable accounting alone, keeping the same seeded equipment and actions.
    for method in ('begin_step', 'settle', 'synchronize'):
        setattr(muted._provenance_service, method, lambda: None)
    for action in (.5, -.5, 1., 0., -.2):
        for env in environments:
            if env.terminated:
                continue
            values = _actions(env, action)
            if env is sidecar:
                env._runtime_service.step_without_feedback(values)
            else:
                env.step(values)
    for env in (muted, sidecar):
        np.testing.assert_array_equal(passive.net_electricity_consumption, env.net_electricity_consumption)
        np.testing.assert_array_equal(passive.net_electricity_consumption_cost, env.net_electricity_consumption_cost)
        for a, b in zip(passive.electric_vehicles, env.electric_vehicles):
            np.testing.assert_array_equal(a.battery.soc, b.battery.soc)
    assert passive._provenance_service.summary() == sidecar._provenance_service.summary()
    for env in environments:
        env.close()

