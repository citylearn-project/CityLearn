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
from gymnasium import ActionWrapper
import pandas as pd
import simplejson as json

try:
    from stable_baselines3.common.base_class import BaseAlgorithm as StableBaselines3Agent

except (ImportError, ModuleNotFoundError):
    # stable-baselines3 is optional; guard runtime isinstance/load calls when absent.
    StableBaselines3Agent = None

def run_work_order(work_order_filepath, max_workers=None, start_index=None, end_index=None, virtual_environment_path=None, windows_system=None):
    work_order_filepath = Path(work_order_filepath)
    windows_system = (os.name == 'nt') if windows_system is None else bool(windows_system)
    
    if virtual_environment_path is not None:    
        if windows_system:
            virtual_environment_command = f'call "{os.path.join(virtual_environment_path, "Scripts", "activate.bat")}"'
        
        else:
            virtual_environment_command = f'source "{os.path.join(virtual_environment_path, "bin", "activate")}"'
    
    else:
        virtual_environment_command = 'echo "No virtual environment"'

    with open(work_order_filepath, mode='r', encoding='utf-8-sig') as f:
        args = [line.strip() for line in f.read().splitlines() if line.strip()]
    
    if len(args) == 0:
        return

    start_index = 0 if start_index is None else start_index
    end_index = len(args) - 1 if end_index is None else end_index
    assert start_index <= end_index, 'start_index must be <= end_index'
    assert start_index < len(args), 'start_index must be < number of jobs'
    args = args[start_index:end_index + 1]
    args = [a for a in args if not a.lstrip().startswith('#')]
    args = [f'{virtual_environment_command} && {a}' for a in args]
    max_workers = cpu_count() if max_workers is None else max_workers
    
    with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
        logging.debug(f'Will use {max_workers} workers for job.')
        logging.debug(f'Pooling {len(args)} jobs to run in parallel...')
        results = [executor.submit(subprocess.run,**{'args':a, 'shell':True}) for a in args]
            
        for future in concurrent.futures.as_completed(results):
            try:
                logging.debug(future.result())
            
            except Exception as e:
                logging.debug(e)

class Simulator:
    def __init__(self, schema: str, agent_name: str = None, env_kwargs: Mapping[str, Any] = None, agent_kwargs: Mapping[str, Any] = None, wrappers: List[str] = None,
     time_series_variables: List[str] = None, simulation_id: str = None, output_directory: Union[Path, str] = None, agent_filepath: Union[Path, str] = None,
     random_seed: int = None, offline: bool = None, overwrite: bool = None
    ) -> None:
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
            data = {}
            n_steps = len(b.net_electricity_consumption)

            for variable in self.time_series_variables:
                key = b
                values = variable.split('.')
                value = None

                for i in range(len(values)):
                    if hasattr(key, values[i]):
                        value = getattr(key, values[i])
                        key = value
                    
                    else:
                        value = None
                        break
                
                if isinstance(value, (list, tuple, pd.Series)) or hasattr(value, '__len__') and not isinstance(value, (str, bytes, Mapping)):
                    if len(value) > n_steps:
                        value = value[:n_steps]
                data[variable.replace('.', '_')] = value
            
            data = pd.DataFrame(data, index=range(n_steps))
            data.insert(0, 'time_step', data.index)
            data.insert(1, 'building_name', b.name)
            data_list.append(data)

        return pd.concat(data_list, ignore_index=True)

    def __unwrap_actions(self, actions: Any) -> Any:
        unwrapped_actions = actions
        cur = self.env
        base = self.env.unwrapped
        while cur is not base and hasattr(cur, 'env'):
            if isinstance(cur, ActionWrapper):
                unwrapped_actions = cur.action(unwrapped_actions)
            cur = cur.env
        return unwrapped_actions

    @staticmethod
    def _normalize_episode_time_steps(evaluation_episode_time_steps):
        if evaluation_episode_time_steps is None:
            return None
        if (
            isinstance(evaluation_episode_time_steps, (list, tuple))
            and len(evaluation_episode_time_steps) == 2
            and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in evaluation_episode_time_steps)
        ):
            return [[int(evaluation_episode_time_steps[0]), int(evaluation_episode_time_steps[1])]]
        return [[int(pair[0]), int(pair[1])] for pair in evaluation_episode_time_steps]

    def __get_training_summary(self):
        return {
            'hostname': socket.gethostname(),
            'username': getpass.getuser(),
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
        reset_out = self.env.reset()
        observations = reset_out[0] if isinstance(reset_out, tuple) else reset_out
        terminated = bool(self.env.unwrapped.terminated)
        truncated = bool(self.env.unwrapped.truncated)
        actions_list = []
        self.__evaluation_start_timestamp = datetime.datetime.now(datetime.timezone.utc)
        
        while not (terminated or truncated):
            if isinstance(self.agent, CityLearnAgent):
                actions = self.agent.predict(observations, deterministic=True)
                actions_list.append(self.env.unwrapped._parse_actions(self.__unwrap_actions(actions)))
            
            elif StableBaselines3Agent is not None and isinstance(self.agent, StableBaselines3Agent):
                actions, _ = self.agent.predict(observations, deterministic=True)
                unwrapped_actions = self.__unwrap_actions(actions)
                if not isinstance(unwrapped_actions, list) or (len(unwrapped_actions) > 0 and not isinstance(unwrapped_actions[0], (list, tuple, pd.Series)) and getattr(unwrapped_actions, 'ndim', 1) == 1):
                    unwrapped_actions = [unwrapped_actions]
                actions_list.append(self.env.unwrapped._parse_actions(unwrapped_actions))

            else:
                raise TypeError(f'Unknown agent type: {type(self.agent)}')

            step_out = self.env.step(actions)
            observations = step_out[0]
            terminated = bool(step_out[2])
            truncated = bool(step_out[3]) if len(step_out) >= 5 else bool(self.env.unwrapped.truncated)

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

    def __set_agent(self) -> Any:
        if self.agent_filepath is None:
            agent = self.env.unwrapped.load_agent(
                agent=self.agent_name, 
                env=self.env,
                **self.agent_kwargs,
            )

        else:
            if str(self.agent_filepath).endswith('.pkl'):
                agent = FileHandler.read_pickle(self.agent_filepath)
                agent.env = self.env

            else:
                if StableBaselines3Agent is None:
                    raise ImportError(
                        'Loading a Stable-Baselines3 agent requires `stable-baselines3`. '
                        'Install it via `pip install stable-baselines3`.'
                    )
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
    def evaluate(cls, evaluation_episode_time_steps: Tuple[int, int] = None, **kwargs):
        kwargs = dict(kwargs)
        kwargs['env_kwargs'] = {} if kwargs.get('env_kwargs') is None else dict(kwargs['env_kwargs'])

        if evaluation_episode_time_steps is not None:
            kwargs['env_kwargs']['episode_time_steps'] = cls._normalize_episode_time_steps(evaluation_episode_time_steps)

        simulator = cls(**kwargs)
        simulator.__evaluate()
        filepath = os.path.join(simulator.output_directory, f'{simulator.simulation_id}-evaluation.json')
        FileHandler.write_json(filepath, simulator.__get_evaluation_summary())

    @classmethod
    def train(cls, episodes: int = None, evaluate: bool = None, evaluation_episode_time_steps: Tuple[int, int] = None, save_agent: bool = None, **kwargs):
        kwargs = dict(kwargs)
        kwargs['env_kwargs'] = {} if kwargs.get('env_kwargs') is None else dict(kwargs['env_kwargs'])
        simulator = cls(**kwargs)
        episodes = 1 if episodes is None else episodes
        simulator.__train(episodes)
        filepath = os.path.join(simulator.output_directory, f'{simulator.simulation_id}-train.json')
        FileHandler.write_json(filepath, simulator.__get_training_summary())

        if save_agent:
            simulator.__save_agent()

        if evaluate:
            normalized_steps = (
                [[
                    simulator.env.unwrapped.episode_tracker.simulation_start_time_step,
                    simulator.env.unwrapped.episode_tracker.simulation_end_time_step,
                ]]
                if evaluation_episode_time_steps is None
                else cls._normalize_episode_time_steps(evaluation_episode_time_steps)
            )
            simulator.env.unwrapped.episode_time_steps = normalized_steps
            simulator.__evaluate()
            eval_filepath = os.path.join(simulator.output_directory, f'{simulator.simulation_id}-evaluation.json')
            FileHandler.write_json(eval_filepath, simulator.__get_evaluation_summary())

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
    subparser_datasets.set_defaults(func=DataSet().get_dataset_names)

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
        action='append', help=('Start and end time steps in data set to evaluate on otherwise, the agent is evaluated on entire dataset.'))
    subparser_simulate.add_argument('-p', '--append', dest='overwrite', action='store_false', help=(
        'Add to output for existing simulation with `simulation_id` i.e. do not overwrite.'))
    subparser_simulate.add_argument('-rs', '--random_seed', dest='random_seed', type=int, help=(
        'Random seed used during environment and agent initialization.'))
    subparser_simulate.add_argument('--offline', dest='offline', action='store_true', help=(
        'Disable network access and require datasets/misc files to be available locally.'))
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
        'Whether to run deterministic evaluation for one episode at the end of training.'))
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
        arg_spec = inspect.getfullargspec(args.func)
        kwargs = {key:value for (key, value) in args._get_kwargs() 
            if (key in arg_spec.args or (arg_spec.varkw is not None and key not in ['func','subcommands']))
        }

        return args.func(**kwargs)
    
    else:
        return parser

if __name__ == '__main__':
    sys.exit(main())
