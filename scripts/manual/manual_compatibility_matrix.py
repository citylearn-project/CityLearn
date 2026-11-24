import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from citylearn.agents.base import Agent
from citylearn.agents.marlisa import MARLISA, MARLISARBC
from citylearn.agents.rbc import RBC, HourRBC, BasicRBC, OptimizedRBC, BasicBatteryRBC
from citylearn.agents.sac import SAC, SACRBC
from citylearn.citylearn import CityLearnEnv
from citylearn.data import DataSet

agents = [
    Agent,
    RBC,
    HourRBC,
    BasicRBC,
    OptimizedRBC,
    BasicBatteryRBC,
    SAC,
    SACRBC,
    MARLISA,
    MARLISARBC,
]
schemas = [
    'baeda_3dem',
    'citylearn_challenge_2020_climate_zone_1',
    'citylearn_challenge_2021',
    'citylearn_challenge_2022_phase_all'
]
central_agent_setting = [
    True,
    False
]

# load all datasets
for schema in DataSet().get_dataset_names():
    try:
        env = CityLearnEnv(schema)
        print(f'Successfully loaded schema: "{schema}"')
    except Exception as e:
        print(f'Unsuccessfully loaded schema: "{schema}"')
        raise e

# load all internally defined agents
for schema in schemas:
    for agent in agents:
        env = CityLearnEnv(schema)

        try:
            model = agent(env)
            print(f'Successfully loaded agent: "{model.__class__.__name__}" with schema: "{schema}"')
        except Exception as e:
            print(f'Unccessfully loaded agent: "{model.__class__.__name__}" with schema: "{schema}"')
            raise e

# # train all internally defined agents with central and non-central agent
# for schema in schemas:
#     for agent in agents:
#         for central_agent in central_agent_setting:
#             if agent == MARLISA and central_agent:
#                 continue
#             else:
#                 pass
#
#             env = CityLearnEnv(schema, central_agent=central_agent, simulation_start_time_step=0, simulation_end_time_step=1000)
#
#             try:
#                 model: Agent = agent(
#                     env,
#                     standardize_start_time_step=env.time_steps - 1,
#                     end_exploration_time_step=env.time_steps
#                 )
#                 model.learn(episodes=3, deterministic_finish=True, logging_level=1)
#                 print(f'Successfully trained agent: "{model.__class__.__name__}" with schema: "{schema}" and central_agent: "{central_agent}"')
#             except Exception as e:
#                 print(f'Unccessfully trained agent: "{model.__class__.__name__}" with schema: "{schema}" and central_agent: "{central_agent}"')
#                 raise e
#
# stable-baselines


# TO-DO
# [X] Lose deterministic_start_time_step as rlc attribute and in schemas as the predict function has a deterministic variable.
# [X] Rename start_training_time_step to standardize_start_time_step for internally defined agents as the timestep infact defines when the observations and rewards replay buffer is normalized
# [] Rename prediction values; instead of xh, make it prediction 1-3 so that up to three predictions of any interval are allowed. This is a big change that will affect backward compatibility for datasets
