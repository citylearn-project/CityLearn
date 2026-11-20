import argparse
import concurrent.futures
import datetime
import getpass
import importlib
import inspect
import logging
from multiprocessing import cpu_count
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
from typing import Any, List, Mapping, Tuple, Union
import uuid
from citylearn.agents.base import Agent as CityLearnAgent
from citylearn.citylearn import CityLearnEnv
from citylearn.data import DataSet, get_settings
from citylearn.__init__ import __version__
from citylearn.utilities import FileHandler
import numpy as np
import pandas as pd
import simplejson as json

LOGGER = logging.getLogger(__name__)

try:
    from stable_baselines3.common.base_class import BaseAlgorithm as StableBaselines3Agent

except (ImportError, ModuleNotFoundError):
    # stable-baselines3 is optional; the name is still used in annotations evaluated at import time.
    StableBaselines3Agent = Any

def run_work_order(work_order_filepath, max_workers=None, start_index=None, end_index=None, virtual_environment_path=None, windows_system=None):
    work_order_filepath = Path(work_order_filepath)
    windows_system = os.name == 'nt' if windows_system is None else windows_system
    
    if virtual_environment_path is not None:    
        if windows_system:
            # subprocess.run(..., shell=True) runs the commands in cmd.exe, which cannot run Activate.ps1.
            virtual_environment_command = f'call "{os.path.join(virtual_environment_path, "Scripts", "activate.bat")}"'
        
        else:
            virtual_environment_command = f'source "{os.path.join(virtual_environment_path, "bin", "activate")}"'
    
    else:
        virtual_environment_command = 'echo "No virtual environment"'

    with open(work_order_filepath,mode='r') as f:
        args = f.read()
    
    args = args.strip('\n').split('\n')
    start_index = 0 if start_index is None else start_index
    end_index = len(args) - 1 if end_index is None else end_index
    assert start_index <= end_index, 'start_index must be <= end_index'
    assert start_index < len(args), 'start_index must be < number of jobs'
    args = args[start_index:end_index + 1]
    args = [a for a in args if not a.startswith('#')]
    args = [f'{virtual_environment_command} && {a}' for a in args]
    max_workers = cpu_count() if max_workers is None else max_workers
    
    failures = []

    with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
        LOGGER.debug(f'Will use {max_workers} workers for job.')
        LOGGER.debug(f'Pooling {len(args)} jobs to run in parallel...')
        futures = {executor.submit(subprocess.run, **{'args': a, 'shell': True}): a for a in args}

        for future in concurrent.futures.as_completed(futures):
            command = futures[future]

            try:
                result = future.result()

            except Exception as e:
                LOGGER.error(f'Job failed to run: {command!r}: {e}')
                failures.append(command)
                continue

            LOGGER.debug(result)
            returncode = getattr(result, 'returncode', 0)

            if returncode != 0:
                LOGGER.error(f'Job exited with code {returncode}: {command!r}')
                failures.append(command)

    if failures:
        LOGGER.error(f'{len(failures)} of {len(args)} jobs failed.')

    # A failed job makes the whole work order fail, so batch runs and CI notice it.
    return 1 if failures else 0

def _list_dataset_names() -> List[str]:
    # Resolved when the command runs, not while the parser is built, so other commands
    # (and --help) neither read the dataset cache nor call the GitHub API.
    return DataSet().get_dataset_names()


def _exit_code(result: Any) -> int:
    """Print list results to stdout, one item per line, and return the process exit code.

    ``sys.exit(main())`` used to receive the list itself, which Python prints to stderr with exit status 1.
    """

    if isinstance(result, (list, tuple)):
        for item in result:
            print(item)

        return 0

    if isinstance(result, (bool, np.bool_)):
        return 0

    if isinstance(result, (int, np.integer)):
        return int(result)

    return 0


class Simulator:
    def __init__(self, schema: str, agent_name: str = None, env_kwargs: Mapping[str, Any] = None, agent_kwargs: Mapping[str, Any] = None, wrappers: List[str] = None,
     time_series_variables: List[str] = None, simulation_id: str = None, output_directory: Union[Path, str] = None, agent_filepath: Union[Path, str] = None,
     random_seed: int = None, offline: bool = None, overwrite: bool = None, record_host: bool = None
    ) -> None:
        # The machine and user names are personal data in shared results, so they are recorded only on request.
        self.record_host = False if record_host is None else bool(record_host)
        self.schema = schema
        self.agent_name = agent_name
        self.env_kwargs = env_kwargs
        self.agent_kwargs = agent_kwargs
        self.random_seed = random_seed
        self.offline = offline
        self.wrappers = wrappers
        self.time_series_variables = time_series_variables
        self.simulation_id = simulation_id
        self.overwrite = overwrite
        self.output_directory = output_directory
        self.agent_filepath = agent_filepath
        self.__reset()

    @property
    def schema(self) -> str:
        return self.__schema
    
    @property
    def agent_name(self) -> str:
        return self.__agent_name
    
    @property
    def env_kwargs(self) -> Mapping[str, Any]:
        return self.__env_kwargs
    
    @property
    def agent_kwargs(self) -> Mapping[str, Any]:
        return self.__agent_kwargs
    
    @property
    def wrappers(self) -> List[str]:
        return self.__wrappers
    
    @property
    def time_series_variables(self) -> List[str]:
        return self.__time_series_variables
    
    @property
    def simulation_id(self) -> str:
        return self.__simulation_id
    
    @property
    def output_directory(self) -> Path:
        return self.__output_directory
    
    @property
    def agent_filepath(self) -> Path:
        return self.__agent_filepath
    
    @property
    def random_seed(self) -> int:
        return self.__random_seed

    @property
    def offline(self) -> bool:
        return self.__offline
    
    @property
    def overwrite(self) -> bool:
        return self.__overwrite
    
    @schema.setter
    def schema(self, value: str):
        self.__schema = value

    @agent_name.setter
    def agent_name(self, value: str):
        self.__agent_name = value

    @env_kwargs.setter
    def env_kwargs(self, value: Mapping[str, Any]):
        self.__env_kwargs = {} if value is None else value

    @agent_kwargs.setter
    def agent_kwargs(self, value: Mapping[str, Any]):
        self.__agent_kwargs = {} if value is None else value

    @wrappers.setter
    def wrappers(self, value:List[str]):
        self.__wrappers = [] if value is None else value

    @time_series_variables.setter
    def time_series_variables(self, value: List[str]):
        self.__time_series_variables = self.get_default_time_series_variables() if value is None else value

    @simulation_id.setter
    def simulation_id(self, value: str):
        self.__simulation_id = f'citylearn-simulation-{uuid.uuid4().hex}' if value is None else value

    @output_directory.setter
    def output_directory(self, value: Path):
        self.__output_directory = Path(os.path.join('citylearn_simulations', self.simulation_id))\
            if value is None else value
        
        if os.path.isdir(self.__output_directory) and self.overwrite:
            shutil.rmtree(self.__output_directory)
        
        else:
            pass

        os.makedirs(self.__output_directory, exist_ok=True)

    @agent_filepath.setter
    def agent_filepath(self, value: Path):
        self.__agent_filepath =  value if value is None else Path(value)

    @random_seed.setter
    def random_seed(self, value: int):
        self.__random_seed = value

        if self.random_seed is not None:
            self.env_kwargs['random_seed'] = self.random_seed

            if self.agent_name is not None:
                random_seed_name = 'seed' if 'stable_baselines3' in self.agent_name else 'random_seed'
                self.agent_kwargs[random_seed_name] = self.random_seed
            
            else:
                pass

        else:
            pass

    @offline.setter
    def offline(self, value: bool):
        self.__offline = False if value is None else bool(value)

        if self.offline:
            self.env_kwargs['offline'] = True

    @overwrite.setter
    def overwrite(self, value: bool):
        self.__overwrite = True if value is None else value

    def __get_evaluation_summary(self):        
        return {
            'evaluation_episode_time_steps': [
                self.env.unwrapped.episode_tracker.episode_start_time_step, 
                self.env.unwrapped.episode_tracker.episode_end_time_step
            ],
            'evaluation_start_timestamp': self.__evaluation_start_timestamp,
            'evaluation_end_timestamp': self.__evaluation_end_timestamp,
            'evaluation': self.env.unwrapped.evaluate().pivot(index='name', columns='cost_function', values='value').to_dict('index'),
            'episode_reward_summary': self.env.unwrapped.episode_rewards[-1],
            'episode_rewards': self.env.unwrapped.rewards,
            'time_series': self.__get_time_series().to_dict('list'),
            'actions': self.__actions_list,
        }

    def __get_time_series(self) -> pd.DataFrame:
        data_list = []

        for b in self.env.unwrapped.buildings:
            # Building results hold one value per executed time step. Data and storage SOC series also
            # hold the terminal time step, which is observed but not executed.
            time_steps = len(b.net_electricity_consumption)
            data = {}

            for variable in self.time_series_variables:
                value = b

                for name in variable.split('.'):
                    value = getattr(value, name, None)

                    if value is None:
                        break

                data[variable.replace('.', '_')] = value[:time_steps] if np.ndim(value) > 0 else value

            data = pd.DataFrame(data, index=range(time_steps))
            data.insert(0, 'time_step', data.index)
            data.insert(1, 'building_name', b.name)
            data_list.append(data)

        return pd.concat(data_list, ignore_index=True)

    def __get_training_summary(self):
        host = {'hostname': socket.gethostname(), 'username': getpass.getuser()} if self.record_host else {}

        return {
            **host,
            'simulation_id': self.simulation_id,
            'agent': self.agent.__class__.__name__,
            'agent_kwargs': self.agent_kwargs,
            'wrappers': self.wrappers,
            'train_episodes': self.env.unwrapped.episode_tracker.episode,
            'train_episode_time_steps': self.env.unwrapped.episode_time_steps,
            'train_start_timestamp': self.__train_start_timestamp,
            'train_end_timestamp': self.__train_end_timestamp,
            'train_episode_reward_summary': self.env.unwrapped.episode_rewards,
            'env_metadata': self.env.unwrapped.get_metadata(),
        }

    def __evaluate(self):
        observations, _ = self.env.reset()
        actions_list = []
        self.__evaluation_start_timestamp = datetime.datetime.now(datetime.timezone.utc)
        
        # Gymnasium 1.x wrappers no longer forward attributes, so read the episode state from the base environment.
        while not self.env.unwrapped.terminated:
            if isinstance(self.agent, CityLearnAgent):
                actions = self.agent.predict(observations, deterministic=True)
                actions_list.append(self.env.unwrapped._parse_actions(actions))
            
            elif isinstance(self.agent, StableBaselines3Agent):
                actions, _ = self.agent.predict(observations, deterministic=True)
                actions_list.append(self.env.unwrapped._parse_actions([actions]))

            else:
                raise Exception(f'Unknown agent type: {type(self.agent)}')

            observations, _, _, _, _ = self.env.step(actions)

        self.__evaluation_end_timestamp = datetime.datetime.now(datetime.timezone.utc)
        self.__actions_list = actions_list

    def __train(self, episodes: int):
        kwargs = {}
        self.__train_start_timestamp = datetime.datetime.now(datetime.timezone.utc)
        env = self.env.unwrapped
        previous_final_export_episode_index = (
            env.plan_final_episode_exports(episodes)
            if hasattr(env, 'plan_final_episode_exports') else None
        )

        try:
            if isinstance(self.agent, CityLearnAgent):
                kwargs = {**kwargs, 'episodes': episodes}
                self.agent.learn(**kwargs)

            else:
                kwargs = {**kwargs, 'total_timesteps': episodes*self.env.unwrapped.time_steps}
                self.agent = self.agent.learn(**kwargs)
        finally:
            if hasattr(env, 'plan_final_episode_exports'):
                env._final_export_episode_index = previous_final_export_episode_index

        self.__train_end_timestamp = datetime.datetime.now(datetime.timezone.utc)

    def __save_agent(self):
        if isinstance(self.agent, CityLearnAgent):
            filepath = os.path.join(self.output_directory, f'{self.simulation_id}-agent.pkl')
            FileHandler.write_pickle(filepath, self.agent)
        
        else:
            filepath = os.path.join(self.output_directory, f'{self.simulation_id}-agent')
            self.agent.save(filepath)
            filepath = f'{filepath}.zip'

        return filepath

    def __set_agent(self) -> Union[CityLearnAgent, StableBaselines3Agent]:
        if self.agent_filepath is None:
            try:
                agent = self.env.unwrapped.load_agent(
                    agent=self.agent_name,
                    env=self.env,
                    **self.agent_kwargs,
                )

            except TypeError as error:
                if 'stable_baselines3' in str(self.agent_name) and "'policy'" in str(error):
                    raise TypeError(
                        f'{self.agent_name} needs a policy. Pass it with the agent arguments, for example '
                        '-ka \'{"policy": "MlpPolicy"}\', and wrap the environment with '
                        '-w citylearn.wrappers.NormalizedObservationWrapper citylearn.wrappers.StableBaselines3Wrapper.'
                    ) from error

                raise

        else:
            if str(self.agent_filepath).endswith('.pkl'):
                agent = FileHandler.read_pickle(self.agent_filepath)
                agent.env = self.env

            else:
                agent = StableBaselines3Agent.load(self.agent_filepath, self.env)

        return agent
    
    def __set_env(self) -> CityLearnEnv:
        env = CityLearnEnv(self.schema, **self.env_kwargs)

        for wrapper in self.wrappers:
            wrapper_module = '.'.join(wrapper.split('.')[0:-1])
            wrapper_name = wrapper.split('.')[-1]
            wrapper_constructor = getattr(importlib.import_module(wrapper_module), wrapper_name)
            env = wrapper_constructor(env)

        return env
    
    def __reset(self):
        self.env = self.__set_env()
        self.agent = self.__set_agent()
        self.__train_start_timestamp = None
        self.__train_end_timestamp = None
        self.__evaluation_start_timestamp = None
        self.__evaluation_end_timestamp = None
        self.__actions_list = None
    
    @classmethod
    def evaluate(cls, evaluation_episode_time_steps: Union[Tuple[int, int], List[Tuple[int, int]]] = None, **kwargs):
        kwargs['env_kwargs'] = {} if kwargs.get('env_kwargs') is None else kwargs['env_kwargs']

        if evaluation_episode_time_steps is not None:
            kwargs['env_kwargs']['episode_time_steps'] = cls.__episode_time_steps(evaluation_episode_time_steps)
        
        else:
            pass
            

        simulator = cls(**kwargs)
        simulator.__evaluate()
        filepath = os.path.join(simulator.output_directory, f'{simulator.simulation_id}-evaluation.json')
        FileHandler.write_json(filepath, simulator.__get_evaluation_summary())
        print(f'Wrote the evaluation to {filepath}')

    @classmethod
    def train(cls, episodes: int = None, evaluate: bool = None, evaluation_episode_time_steps: Union[Tuple[int, int], List[Tuple[int, int]]] = None, save_agent: bool = None, **kwargs):
        simulator = cls(**kwargs)
        episodes = 1 if episodes is None else episodes
        simulator.__train(episodes)
        filepath = os.path.join(simulator.output_directory, f'{simulator.simulation_id}-train.json')
        FileHandler.write_json(filepath, simulator.__get_training_summary())
        print(f'Wrote the training summary to {filepath}')

        if save_agent:
            print(f'Wrote the agent to {simulator.__save_agent()}')

        else:
            pass

        if evaluate:
            # Evaluate the agent trained above, not a new agent built from the same arguments, on the first
            # training episode window unless -te gives other windows.
            simulator.env.unwrapped.episode_time_steps = (
                [simulator.__training_window()] if evaluation_episode_time_steps is None
                else cls.__episode_time_steps(evaluation_episode_time_steps)
            )
            simulator.__evaluate()
            filepath = os.path.join(simulator.output_directory, f'{simulator.simulation_id}-evaluation.json')
            FileHandler.write_json(filepath, simulator.__get_evaluation_summary())
            print(f'Wrote the evaluation to {filepath}')

        else:
            pass

    def __training_window(self) -> List[int]:
        """First episode window of the training configuration: the whole simulation window without episode splits."""

        tracker = self.env.unwrapped.episode_tracker
        start, end = int(tracker.simulation_start_time_step), int(tracker.simulation_end_time_step)
        episode_time_steps = self.env.unwrapped.episode_time_steps

        if episode_time_steps is None:
            return [start, end]

        if np.ndim(episode_time_steps) == 0:
            return [start, min(start + int(episode_time_steps) - 1, end)]

        first_start, first_end = episode_time_steps[0]

        return [int(first_start), int(first_end)]

    @staticmethod
    def __episode_time_steps(evaluation_episode_time_steps) -> List[List[int]]:
        # The CLI collects each `-te start end` pair in a list; the Python API also accepts one (start, end) pair.
        if np.ndim(evaluation_episode_time_steps) == 1:
            evaluation_episode_time_steps = [evaluation_episode_time_steps]

        return [[int(start), int(end)] for start, end in evaluation_episode_time_steps]

    @staticmethod
    def get_default_time_series_variables():
        return get_settings()['default_time_series_variables']

def main():
    parser = argparse.ArgumentParser(
        prog='citylearn', 
        formatter_class=argparse.ArgumentDefaultsHelpFormatter, description=(
            'An open source Farama Foundation Gymnasium environment for benchmarking distributed energy resource '
            'control algorithms to provide energy flexibility in a district of buildings. '
            'Compatible with training and evaluating internally defined CityLearn agents in `citylearn.agents`, '
            'user-defined agents that inherit from `citylearn.agents.base.Agent` and use the same interface as it, and agents '
            'provided by stable-baselines3.'))
    parser.add_argument('--version', action='version', version='%(prog)s' + f' {__version__}')
    subparsers = parser.add_subparsers(title='subcommands', required=True, dest='subcommands')

    # run many simulations in parallel
    subparser_run_work_order = subparsers.add_parser(
        'run_work_order', 
        formatter_class=argparse.ArgumentDefaultsHelpFormatter, 
        help='Run commands in parallel. Useful for running many `citylearn simulate` commands in parallel.'
    )
    subparser_run_work_order.add_argument('work_order_filepath', type=Path, help=(
        'Filepath to script containing list of commands to be run in parallel with each command defined on a new line.'))
    subparser_run_work_order.add_argument('-w', '--max_workers', dest='max_workers', type=int, help=(
        'Maximum number of commands to run at a time. Default is the number of CPUs.'))
    subparser_run_work_order.add_argument('-is', '--start_index', default=0, dest='start_index', type=int, help=(
        'Line index of first command to execute. Commands above this index are not executed. '
        'The default is to execute from the first line.'))
    subparser_run_work_order.add_argument('-ie', '--end_index', dest='end_index', type=int, help=(
        'Line index of last command to execute. Commands below this index are not exectued. '
        'The default is to execute till the last line.'))
    subparser_run_work_order.set_defaults(func=run_work_order)

    # get names of datasets
    subparser_datasets = subparsers.add_parser(
        'list_datasets', 
        formatter_class=argparse.ArgumentDefaultsHelpFormatter, 
        help='Lists available dataset names that can be parsed as `schema` in `citylearn simulate schema`.'
    )
    subparser_datasets.set_defaults(func=_list_dataset_names)

     # get default time series variables
    subparser_time_series_variables = subparsers.add_parser(
        'list_default_time_series_variables', 
        formatter_class=argparse.ArgumentDefaultsHelpFormatter, 
        help='Lists the default time series variables that will be reported and saved in a `JSON` file post-evaluation.'
    )
    subparser_time_series_variables.set_defaults(func=Simulator.get_default_time_series_variables)

    # run one simulation
    subparser_simulate = subparsers.add_parser(
        'simulate', 
        formatter_class=argparse.ArgumentDefaultsHelpFormatter, 
        help='Train or evaluate a trained agent against an environment.'
    )
    subparser_simulate.add_argument('schema', type=str, help=(
        'Name of CityLearn dataset or filepath to a schema. Call `citylearn list_datasets` to get list of valid dataset names.'))
    subparser_simulate.add_argument('-a', '--agent_name', dest='agent_name', default='citylearn.agents.baseline.BusinessAsUsualAgent', type=str, help=(
        'Name path to agent. Currently only compatible with internally defined CityLearn agents in `citylearn.agents`, '
        'user-defined agents that inherit from `citylearn.agents.base.Agent` and use the same interface as it, and agents '
        'provided by stable-baselines3. To use stable-baselines3 agents, make sure to run `pip install stable-baselines3` '
        'before using the `simulate command.`'))
    subparser_simulate.add_argument('-ke', '--env_kwargs', dest='env_kwargs', type=json.loads, help=(
        'Initialization parameters for`citylearn.citylearn.CityLearnEnv`.'))
    subparser_simulate.add_argument('-ka', '--agent_kwargs', dest='agent_kwargs', type=json.loads, help=(
        'Initialization parameters for agent class.'))
    subparser_simulate.add_argument('-w', '--wrappers', dest='wrappers', type=str, nargs='+', help=(
        'Name path to environment wrappers e.g., \'citylearn.wrappers.ClippedObservationWrapper\'.'))
    subparser_simulate.add_argument('-tv', '--time_series_variables', dest='time_series_variables', type=str, nargs='+', help=(
        'Names of building-level time series properties to be stored in the evaluation `JSON` post-evaluation. '
        'Call `citylearn list_default_time_series_variables` to see the default variable in use.'))
    subparser_simulate.add_argument('-sid', '--simulation_id', dest='simulation_id', type=str, help=(
        'SImulation reference ID used in directory and file names.' ))
    subparser_simulate.add_argument('-fa', '--agent_filepath', dest='agent_filepath', type=str, help=(
        'Filepath to previously saved agent to use for training or evaluation.'))
    subparser_simulate.add_argument('-d', '--output_directory', dest='output_directory', type=str, help=(
        'Directory to save all simulation output to.'))
    subparser_simulate.add_argument('-te', '--evaluation_episode_time_steps', dest='evaluation_episode_time_steps', type=int, nargs=2,
        action='append', help=('Start and end time steps in data set to evaluate on. Without it, `evaluate` uses the '
        'environment episode windows and `train --evaluate` the first training episode window.'))
    subparser_simulate.add_argument('-p', '--append', dest='overwrite', action='store_false', help=(
        'Add to output for existing simulation with `simulation_id` i.e. do not overwrite.'))
    subparser_simulate.add_argument('-rs', '--random_seed', dest='random_seed', type=int, help=(
        'Random seed used during environment and agent initialization.'))
    subparser_simulate.add_argument('--offline', dest='offline', action='store_true', help=(
        'Disable network access and require datasets/misc files to be available locally.'))
    subparser_simulate.add_argument('--record_host', dest='record_host', action='store_true', help=(
        'Record the machine host name and the user name in the training summary JSON.'))
    simulation_subparsers = subparser_simulate.add_subparsers(title='simulate subcommands', required=True, dest='subcommands')

    # -> train an agent
    subparser_train = simulation_subparsers.add_parser(
        'train', 
        formatter_class=argparse.ArgumentDefaultsHelpFormatter, 
        help='Train an agent.'
    )
    subparser_train.add_argument('-e', '--episodes', dest='episodes', type=int, help='Number of training episodes/epochs.')
    subparser_train.add_argument('--save_agent', dest='save_agent', action='store_true', help='Whether to save agent to disk at the end of training.')
    subparser_train.add_argument('--evaluate', dest='evaluate', action='store_true', help=(
        'Whether to run deterministic evaluation for one episode at the end of training, on the first training '
        'episode window unless `-te` gives evaluation windows.'))
    subparser_train.set_defaults(func=Simulator.train)

    # -> evaluate a trained agent
    subparser_evaluate = simulation_subparsers.add_parser(
        'evaluate', 
        formatter_class=argparse.ArgumentDefaultsHelpFormatter, 
        help='Deterministically evaluate an agent.'
    )
    subparser_evaluate.set_defaults(func=Simulator.evaluate)

    argv = sys.argv
    argv = ['sphinx-build' in a for a in argv]
    sphinx = any(argv)

    if not sphinx:
        args = parser.parse_args()
        # The CLI is an application, so it configures logging; the library itself only adds a NullHandler.
        logging.basicConfig(level=logging.INFO)
        arg_spec = inspect.getfullargspec(args.func)
        kwargs = {key:value for (key, value) in args._get_kwargs() 
            if (key in arg_spec.args or (arg_spec.varkw is not None and key not in ['func','subcommands']))
        }

        return _exit_code(args.func(**kwargs))
    
    else:
        return parser

if __name__ == '__main__':
    sys.exit(main())
