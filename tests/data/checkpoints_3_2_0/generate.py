"""Write the CityLearn 3.2.0 SAC and MARLISA checkpoints that tests/test_sac_marlisa_regressions.py resumes.

Run it against CityLearn 3.2.0, not the working tree, e.g. from the repository root:

    git archive v3.2.0 citylearn | tar -x -C /tmp/citylearn-3.2.0
    PYTHONPATH=/tmp/citylearn-3.2.0 python tests/data/checkpoints_3_2_0/generate.py

The agents are trained past exploration and saved as `citylearn simulate ... train --save_agent` saves them
(FileHandler.write_pickle), on the CPU so that they load without a GPU. Their `env` is detached before saving: the CLI
replaces it right after loading (`agent.env = env`), and it would add about 2 MB to each file. The pickles are
gzip-compressed.
"""

import os

os.environ['CUDA_VISIBLE_DEVICES'] = '-1'  # before torch is imported; an empty value would unset it on Windows

import gzip
import json
from pathlib import Path

import citylearn
from citylearn.agents.marlisa import MARLISA
from citylearn.agents.sac import SAC
from citylearn.citylearn import CityLearnEnv
from citylearn.utilities import FileHandler

assert citylearn.__version__ == '3.2.0', f'Run with CityLearn 3.2.0, not {citylearn.__version__} ({citylearn.__file__}).'
OUTPUT = Path(__file__).resolve().parent
DATASET = OUTPUT.parents[2] / 'data' / 'datasets' / 'citylearn_challenge_2022_phase_all'


def env(buildings):
    schema = json.loads((DATASET / 'schema.json').read_text(encoding='utf-8'))
    schema['root_directory'] = str(DATASET)
    return CityLearnEnv(schema, central_agent=False, episode_time_steps=24, buildings=list(buildings), random_seed=0)


sac = SAC(env((0,)), hidden_dimension=[8, 8], batch_size=8, standardize_start_time_step=10, end_exploration_time_step=15)
sac.learn(episodes=1)
marlisa = MARLISA(
    env((0, 1)), hidden_dimension=[8, 8], batch_size=8, start_regression_time_step=2, standardize_start_time_step=42,
    end_exploration_time_step=45,
)
marlisa.learn(episodes=2)

for name, agent in [('sac', sac), ('marlisa', marlisa)]:
    assert agent.device.type == 'cpu' and all(agent.normalized) and agent.time_step > agent.end_exploration_time_step
    agent.env = None
    path = OUTPUT / f'{name}.pkl'
    FileHandler.write_pickle(path, agent)
    path.with_suffix('.pkl.gz').write_bytes(gzip.compress(path.read_bytes(), mtime=0))
    path.unlink()
