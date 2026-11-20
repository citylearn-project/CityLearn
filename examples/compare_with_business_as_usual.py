from citylearn.agents.baseline import RBCBasicPolicy
from citylearn.citylearn import CityLearnEnv

env = CityLearnEnv(
    "citylearn_challenge_2022_phase_all_plus_evs",
    episode_time_steps=24,
    interface="flat",
    render_mode="none",
)
agent = RBCBasicPolicy(env)
observations, info = env.reset(seed=0)
terminated = truncated = False

while not (terminated or truncated):
    actions = agent.predict(observations)
    observations, rewards, terminated, truncated, info = env.step(actions)

scorecard = env.scorecard(level="district")
selected = [
    "district_cost_total_control_eur",
    "district_cost_total_business_as_usual_eur",
    "district_cost_total_delta_to_business_as_usual_eur",
    "district_energy_grid_total_import_control_kwh",
    "district_energy_grid_total_import_business_as_usual_kwh",
    "district_ev_departure_audit_min_acceptable_service_feasible_ratio",
    "district_battery_total_throughput_delta_to_business_as_usual_kwh",
]
print(scorecard.loc[
    scorecard["cost_function"].isin(selected),
    ["cost_function", "value"],
].to_string(index=False))
env.close()
