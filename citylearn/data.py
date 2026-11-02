import ast
import logging
import os
from pathlib import Path
from platformdirs import user_cache_dir
import shutil
from typing import Any, Dict, Iterable, Mapping, List, Optional, Union
import numpy as np
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from citylearn.__init__ import __version__
from citylearn.utilities import FileHandler, NoiseUtils, parse_bool

LOGGER = logging.getLogger()
logging.basicConfig(level=logging.INFO)

TOLERANCE = 0.0001
ZERO_DIVISION_PLACEHOLDER = 0.000001
MISC_DIRECTORY = os.path.join(os.path.dirname(__file__), 'misc')
QUERIES_DIRECTORY = os.path.join(MISC_DIRECTORY, 'queries')
SETTINGS_FILEPATH = os.path.join(MISC_DIRECTORY, 'settings.yaml')
LOCAL_DATA_DIRECTORY = os.path.normpath(
    os.path.join(os.path.dirname(__file__), '..', 'data')
)
LOCAL_DATA_DATASETS_DIRECTORY = os.path.join(LOCAL_DATA_DIRECTORY, 'datasets')
LOCAL_DATA_MISC_DIRECTORY = os.path.normpath(
    os.path.join(LOCAL_DATA_DIRECTORY, 'misc')
)


class OfflineDataError(RuntimeError):
    """Raised when offline mode blocks network fallback or required local data is unavailable."""


def _parse_env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)

    if value is None:
        return default

    return bool(parse_bool(value, default=default, path=name))

def get_settings():
    directory = os.path.join(os.path.join(os.path.dirname(__file__), 'misc'))
    filepath = os.path.join(directory, 'settings.yaml')
    settings = FileHandler.read_yaml(filepath)

    return settings

class DataSet:
    """CityLearn input data set and schema class."""

    GITHUB_ACCOUNT = os.getenv('CITYLEARN_DATASET_GITHUB_ACCOUNT', 'citylearn-project')
    REPOSITORY_NAME = os.getenv('CITYLEARN_DATASET_REPOSITORY', 'CityLearn')
    REPOSITORY_TAG = os.getenv('CITYLEARN_DATASET_TAG', f'v{__version__}')
    OFFLINE = _parse_env_bool('CITYLEARN_OFFLINE', False)
    REPOSITORY_DATA_PATH = FileHandler.join_url('data')
    REPOSITORY_DATA_DATASETS_PATH = FileHandler.join_url(REPOSITORY_DATA_PATH, 'datasets')
    REPOSITORY_DATA_MISC_PATH = FileHandler.join_url(REPOSITORY_DATA_PATH, 'misc')
    GITHUB_API_CONTENT_URL = FileHandler.join_url('https://api.github.com/repos/', GITHUB_ACCOUNT, REPOSITORY_NAME, 'contents')
    DEFAULT_CACHE_DIRECTORY = os.path.join(user_cache_dir('citylearn'), REPOSITORY_TAG)
    BATTERY_CHOICES_FILENAME = 'battery_choices.yaml'
    PV_CHOICES_FILENAME = 'lbl-tracking_the_sun-res-pv.csv'

    def __init__(
        self, github_account: str = None, repository: str = None, tag: str = None, datasets_path: str = None,
        misc_path: str = None, logging_level: int = None, offline: bool = None
    ):
        self.github_account = github_account
        self.repository = repository
        self.tag = tag
        self.datasets_path = datasets_path
        self.misc_path = misc_path
        self.logging_level = logging_level
        self.offline = offline

    @property
    def github_account(self) -> str:
        return  self.__github_account
    
    @property
    def repository(self) -> str:
        return self.__repository
    
    @property
    def tag(self) -> str:
        return self.__tag
    
    @property
    def datasets_path(self) -> str:
        return self.__datasets_path
    
    @property
    def misc_path(self) -> str:
        return self.__misc_path
    
    @property
    def cache_directory(self) -> Union[Path, str]:
        directory = user_cache_dir(
            appname=self.repository.lower(),
            appauthor=self.github_account,
            version=self.tag,
        )
        os.makedirs(directory, exist_ok=True)
        
        return directory
    
    @property
    def logging_level(self) -> int:
        return self.__logging_level

    @property
    def offline(self) -> bool:
        return self.__offline

    @property
    def local_datasets_directories(self) -> List[str]:
        env_value = os.getenv('CITYLEARN_LOCAL_DATASETS_PATH')
        env_paths = [] if env_value is None else [p for p in env_value.split(os.pathsep) if p.strip() != '']
        default_paths = [
            LOCAL_DATA_DATASETS_DIRECTORY,
            os.path.join(os.getcwd(), 'data', 'datasets'),
        ]

        return self._existing_directories([*env_paths, *default_paths])

    @property
    def local_misc_directories(self) -> List[str]:
        env_value = os.getenv('CITYLEARN_LOCAL_MISC_PATH')
        env_paths = [] if env_value is None else [p for p in env_value.split(os.pathsep) if p.strip() != '']
        default_paths = [
            LOCAL_DATA_MISC_DIRECTORY,
            os.path.join(os.getcwd(), 'data', 'misc'),
        ]

        return self._existing_directories([*env_paths, *default_paths])
    
    @github_account.setter
    def github_account(self, value: str):
        self.__github_account = self.GITHUB_ACCOUNT if value is None else value

    @repository.setter
    def repository(self, value: str):
        self.__repository = self.REPOSITORY_NAME if value is None else value

    @tag.setter
    def tag(self, value: str):
        self.__tag = self.REPOSITORY_TAG if value is None else value

    @datasets_path.setter
    def datasets_path(self, value: str):
        self.__datasets_path = self.REPOSITORY_DATA_DATASETS_PATH if value is None else value

    @misc_path.setter
    def misc_path(self, value: str):
        self.__misc_path = self.REPOSITORY_DATA_MISC_PATH if value is None else value

    @logging_level.setter
    def logging_level(self, value: int):
        self.__logging_level = 20 if value is None else value
        LOGGER.setLevel(self.logging_level)

    @offline.setter
    def offline(self, value: bool):
        self.__offline = self.OFFLINE if value is None else bool(parse_bool(value, default=False, path='offline'))

    @staticmethod
    def _existing_directories(directories: Iterable[str]) -> List[str]:
        existing_directories: List[str] = []
        seen_directories = set()

        for directory in directories:
            if directory is None:
                continue

            normalized_directory = os.path.abspath(os.path.expanduser(str(directory)))

            if normalized_directory in seen_directories:
                continue

            if os.path.isdir(normalized_directory):
                seen_directories.add(normalized_directory)
                existing_directories.append(normalized_directory)

        return existing_directories

    def _find_local_dataset_root(self, name: str) -> Optional[str]:
        normalized_name = str(name).strip()
        name_path = Path(normalized_name).expanduser()

        if name_path.is_dir() and (name_path / 'schema.json').is_file():
            return str(name_path.resolve())

        for root in self.local_datasets_directories:
            candidate = Path(root) / normalized_name

            if candidate.is_dir() and (candidate / 'schema.json').is_file():
                return str(candidate.resolve())

        return None

    def _find_local_misc_filepath(self, filename: str) -> Optional[str]:
        for root in self.local_misc_directories:
            filepath = Path(root) / filename

            if filepath.is_file():
                return str(filepath.resolve())

        return None

    def _get_local_dataset_names(self) -> List[str]:
        dataset_names = set()

        for root in self.local_datasets_directories:
            for dataset_path in Path(root).iterdir():
                if dataset_path.is_dir() and (dataset_path / 'schema.json').is_file():
                    dataset_names.add(dataset_path.name)

        return sorted(dataset_names)

    def get_schema(self, name: str) -> dict:
        schema_filepath = self.get_dataset(name)
        schema = FileHandler.read_json(schema_filepath)
        schema['root_directory'] = os.path.split(Path(schema_filepath).absolute())[0]

        return schema

    def get_dataset(self, name: str, directory: Union[Path, str] = None) -> str:
        dataset_name = Path(str(name).rstrip('/')).name
        datasets_directory = os.path.join(self.cache_directory, 'datasets')
        root_directory = os.path.join(datasets_directory, dataset_name)
        schema_filepath = os.path.join(root_directory, 'schema.json')
        path = FileHandler.join_url(self.datasets_path, dataset_name)

        # check that dataset does not already exist using the schema as a proxy
        if not os.path.isfile(schema_filepath):
            local_root_directory = self._find_local_dataset_root(str(name))

            if local_root_directory is not None:
                if os.path.isdir(root_directory):
                    shutil.rmtree(root_directory)

                shutil.copytree(local_root_directory, root_directory)

            else:
                if self.offline:
                    local_directories = self.local_datasets_directories
                    local_directories_message = ', '.join(local_directories) if len(local_directories) > 0 else '(none)'
                    raise OfflineDataError(
                        f"Offline mode is enabled and dataset '{dataset_name}' was not found locally. "
                        f"Checked cache file '{schema_filepath}' and local dataset roots: {local_directories_message}. "
                        "Pass a local schema.json file path or place the dataset under one of the local roots."
                    )

                LOGGER.info(
                    f'The {dataset_name} dataset DNE in cache/local roots. Will download from '
                    f'{self.github_account}/{self.repository}/tree/{self.tag} GitHub repository and write to {datasets_directory}. '
                    f'Next time DataSet.get_dataset(\'{dataset_name}\') is called, it will read '
                    'from cache unless DataSet.clear_cache is run first.'
                )
                contents = self.get_github_contents(path)

                if os.path.isdir(root_directory):
                    shutil.rmtree(root_directory)

                for c in contents:
                    if c['type'] == 'file':
                        relative_directory_content = c['path'].split(f'{dataset_name}/')[-1].split('/')[:-1]
                        content_directory = os.path.join(root_directory, *relative_directory_content)
                        filepath = os.path.join(content_directory, c['name'])
                        os.makedirs(content_directory, exist_ok=True)
                        response = self.get_requests_session().get(c['download_url'])

                        with open(filepath, 'wb') as f:
                            f.write(response.content)

        if directory is not None:
            os.makedirs(directory, exist_ok=True)
            shutil.copytree(root_directory, directory, dirs_exist_ok=True)
            schema_filepath = os.path.join(directory, dataset_name, 'schema.json')
    
        return schema_filepath

    def get_dataset_names(self) -> List[str]:
        filepath = os.path.join(self.cache_directory, 'dataset_names.json')
        local_dataset_names = self._get_local_dataset_names()

        if len(local_dataset_names) > 0:
            cached_dataset_names = FileHandler.read_json(filepath) if os.path.isfile(filepath) else []
            contents = sorted(set(local_dataset_names).union(cached_dataset_names))

        elif os.path.isfile(filepath):
            contents = FileHandler.read_json(filepath)

        elif self.offline:
            local_directories = self.local_datasets_directories
            local_directories_message = ', '.join(local_directories) if len(local_directories) > 0 else '(none)'
            raise OfflineDataError(
                'Offline mode is enabled and dataset names are not cached and no local datasets were found. '
                f'Checked dataset roots: {local_directories_message}.'
            )

        else:
            LOGGER.info(f'The dataset names DNE in cache. Will download from '
                f'{self.github_account}/{self.repository}/tree/{self.tag} GitHub repository and write to {filepath}. '
                    'Next time DataSet.get_dataset_names is called, it will read '
                        'from cache unless DataSet.clear_cache is run first.')
            contents = self.get_github_contents(self.datasets_path)
            contents = [
                r['name'] for r in contents 
                    if r.get('type') == 'dir' 
                        and r.get('path').replace(r['name'], '').strip('/') == self.datasets_path
            ]
            FileHandler.write_json(filepath, contents)
            
        contents = sorted(contents)

        return contents
    
    def get_pv_sizing_data(self) -> pd.DataFrame:
        """Reads and returns LBNL''s Tracking The Sun dataset that has been prefilered for completeness.
        
        Returns
        -------
        data: pd.DataFrame
        """

        misc_directory = os.path.join(self.cache_directory, 'misc')
        os.makedirs(misc_directory, exist_ok=True)
        filepath = os.path.join(misc_directory, self.PV_CHOICES_FILENAME)
        path = FileHandler.join_url(self.misc_path)

        # Prefer local data to avoid unnecessary network usage.
        if not os.path.isfile(filepath):
            local_filepath = self._find_local_misc_filepath(self.PV_CHOICES_FILENAME)

            if local_filepath is not None:
                shutil.copy(local_filepath, filepath)

        # check that file DNE
        if not os.path.isfile(filepath):
            if self.offline:
                local_directories = self.local_misc_directories
                local_directories_message = ', '.join(local_directories) if len(local_directories) > 0 else '(none)'
                raise OfflineDataError(
                    f"Offline mode is enabled and '{self.PV_CHOICES_FILENAME}' was not found locally. "
                    f"Checked cache file '{filepath}' and local misc roots: {local_directories_message}."
                )

            LOGGER.info(f'The PV sizing data DNE in cache. Will download from '
                f'{self.github_account}/{self.repository}/tree/{self.tag} GitHub repository and write to {misc_directory}. '
                    'Next time DataSet.get_pv_sizing_data is called, it will read '
                        'from cache unless DataSet.clear_cache is run first.')
            contents = self.get_github_contents(path)
            url = [f['download_url'] for f in contents if f['name'] == self.PV_CHOICES_FILENAME][0]
            response = self.get_requests_session().get(url)

            with open(filepath, 'wb') as f:
                f.write(response.content)

        else:
            pass

        data = pd.read_csv(filepath, low_memory=False)
        
        return data
    
    def get_battery_sizing_data(self) -> Mapping[str, Union[float, str]]:
        """Reads and returns internally defined real world manufacturer models.
        
        Returns
        -------
        data: Mapping[str, Union[float, str]]
        """

        misc_directory = os.path.join(self.cache_directory, 'misc')
        os.makedirs(misc_directory, exist_ok=True)
        filepath = os.path.join(misc_directory, self.BATTERY_CHOICES_FILENAME)
        path = FileHandler.join_url(self.misc_path)

        # Prefer local data to avoid unnecessary network usage.
        if not os.path.isfile(filepath):
            local_filepath = self._find_local_misc_filepath(self.BATTERY_CHOICES_FILENAME)

            if local_filepath is not None:
                shutil.copy(local_filepath, filepath)

        # check that file DNE
        if not os.path.isfile(filepath):
            if self.offline:
                local_directories = self.local_misc_directories
                local_directories_message = ', '.join(local_directories) if len(local_directories) > 0 else '(none)'
                raise OfflineDataError(
                    f"Offline mode is enabled and '{self.BATTERY_CHOICES_FILENAME}' was not found locally. "
                    f"Checked cache file '{filepath}' and local misc roots: {local_directories_message}."
                )

            LOGGER.info(f'The battery sizing data DNE in cache. Will download from '
                f'{self.github_account}/{self.repository}/tree/{self.tag} GitHub repository and write to {misc_directory}. '
                    'Next time DataSet.get_battery_sizing_data is called, it will read '
                        'from cache unless DataSet.clear_cache is run first.')
            contents = self.get_github_contents(path)
            url = [f['download_url'] for f in contents if f['name'] == self.BATTERY_CHOICES_FILENAME][0]
            response = self.get_requests_session().get(url)

            with open(filepath, 'wb') as f:
                f.write(response.content)

        else:
            pass

        data = FileHandler.read_yaml(filepath)
        data = pd.DataFrame([{'model': k, **v['attributes']} for k, v in data.items()])
        data = data.set_index('model')

        return data
    
    def clear_cache(self):
        if os.path.isdir(self.cache_directory):
            shutil.rmtree(self.cache_directory)
        
        else:
            pass

    def get_github_contents(self, path: str = None) -> List[Mapping[str, Any]]:
        if self.offline:
            raise OfflineDataError(
                'Offline mode is enabled and GitHub access is disabled. '
                'Provide local data files or disable offline mode.'
            )

        url = self.GITHUB_API_CONTENT_URL if path is None else FileHandler.join_url(self.GITHUB_API_CONTENT_URL, path) 
        params = dict(ref=self.tag)
        contents = self.get_requests_session().get(url, params=params)

        if contents.status_code == 200:
            contents = contents.json()

        else:
            raise Exception(f'Unable to get response from GitHub API for endpoint: {url}.'\
                f'\rReturned status code: {contents.status_code};\rContent: {contents.content}')

        return contents
    
    @staticmethod
    def get_requests_session(**kwargs) -> requests.Session:
        session = requests.Session()
        kwargs = {
            'total': 5,
            'backoff_factor': 1,
            'status_forcelist': [400, 502, 503, 504],
            **kwargs
        }
        retries = Retry(**kwargs)
        session.mount('http://', HTTPAdapter(max_retries=retries))
        session.mount('https://', HTTPAdapter(max_retries=retries))
        
        return session
    
class TimeSeriesData:
    """Generic time series data class.
    
    
    Parameters
    ----------
    variable: np.array, optional
        A generic time series variable.
    start_time_step: int, optional
        Time step to start reading variables.
    end_time_step: int, optional
         Time step to end reading variables.
    """

    def __init__(self, variable: Iterable = None, start_time_step: int = None, end_time_step: int = None):
        self.variable = variable if variable is None else np.array(variable)
        self.start_time_step = start_time_step
        self.end_time_step = end_time_step

    @staticmethod
    def _slice_variable(variable: Any, start_time_step: int, end_time_step: int):
        if isinstance(variable, np.ndarray):
            start_index = 0 if start_time_step is None else start_time_step
            end_index = variable.shape[0] if end_time_step is None else end_time_step + 1
            return variable[start_index:end_index]

        if isinstance(variable, (list, tuple)):
            start_index = 0 if start_time_step is None else start_time_step
            end_index = len(variable) if end_time_step is None else end_time_step + 1
            return variable[start_index:end_index]

        return variable

    def __getattribute__(self, name: str):
        if name.startswith('__'):
            return object.__getattribute__(self, name)

        data = object.__getattribute__(self, '__dict__')
        variable_name = f'_{name}'

        if variable_name in data:
            start_time_step = data.get('_start_time_step')
            end_time_step = data.get('_end_time_step')
            variable = data[variable_name]
            return self._slice_variable(variable, start_time_step, end_time_step)

        return object.__getattribute__(self, name)

    def __getattr__(self, name: str, start_time_step: int = None, end_time_step: int = None):
        """Returns values of the named variable within the specified time steps and
        is useful for selecting episode-specific observation."""
        
        # not the most elegant solution tbh
        try:
            variable = self.__dict__[f'_{name}']
        except KeyError:
            raise AttributeError(f'_{name}')
        explicit_start = start_time_step is not None
        explicit_end = end_time_step is not None
        start_time_step = self.start_time_step if start_time_step is None else start_time_step
        end_time_step = self.end_time_step if end_time_step is None else end_time_step
        offset = int(self.__dict__.get('_time_step_offset', 0) or 0)

        if offset != 0 and explicit_start:
            start_time_step -= offset

        if offset != 0 and explicit_end:
            end_time_step -= offset

        return self._slice_variable(variable, start_time_step, end_time_step)
        
    def __setattr__(self, name: str, value: Any):
        """Sets named variable.
        
        Variables are named with a single underscore prefix.
        """

        self.__dict__[f'_{name}'] = value

class EnergySimulation(TimeSeriesData):
    """`Building` `energy_simulation` data class.

    Parameters
    ----------
    month : np.array
        Month time series value ranging from 1 - 12.
    hour : np.array
        Hour time series value ranging from 1 - 24.
    minutes : np.array
        Minutes time series value ranging from 0 - 60.
    seconds : np.array
        Seconds time series value ranging from 0 - 59. Optional, but needed to
        infer dataset cadence below one minute.
    day_type : np.array
        Numeric day of week time series ranging from 1 - 8 where 1 - 7 is Monday - Sunday and 8 is reserved for special days e.g. holiday.
    indoor_dry_bulb_temperature : np.array
        Average building dry bulb temperature time series in [C].
    non_shiftable_load : np.array
        Total building non-shiftable plug and equipment loads time series in [kWh].
    dhw_demand : np.array
        Total building domestic hot water demand time series in [kWh].
    cooling_demand : np.array
        Total building space cooling demand time series in [kWh].
    heating_demand : np.array
        Total building space heating demand time series in [kWh].
    solar_generation : np.array
        Inverter output per 1 kW of PV system time series in [W/kW].
    daylight_savings_status : np.array, optional
        Daylight saving status time series signal of 0 or 1 indicating inactive  or active daylight saving respectively.
    average_unmet_cooling_setpoint_difference : np.array, optional
        Average difference between `indoor_dry_bulb_temperature` and cooling temperature setpoints time series in [C].
    indoor_relative_humidity : np.array, optional
        Average building relative humidity time series in [%].
    occupant_count: np.array, optional
        Building occupant count time series in [people].
    indoor_dry_bulb_temperature_cooling_set_point: np.array
        Average building dry bulb temperature cooling set point time series in [C].
    indoor_dry_bulb_temperature_heating_set_point: np.array
        Average building dry bulb temperature heating set point time series in [C].
    hvac_mode: np.array, default: 1
        Cooling and heating device availability. If 0, both HVAC devices are unavailable (off), if 1,
        the cooling device is available for space cooling and if 2, the heating device is available
        for space heating only. Automatic (auto) mode is 3 and allows for either cooling or heating 
        depending on the control action. The default is to set the mode to cooling at all times. 
        The HVAC devices are always available for cooling and heating storage charging irrespective 
        of the hvac mode.
    power_outage np.array, default: 0
        Signal for power outage. If 0, there is no outage and building can draw energy from grid. 
        If 1, there is a power outage and building can only use its energy resources to meet loads.
    comfort_band np.array, default: 2
        Occupant comfort band above the `indoor_dry_bulb_temperature_cooling_set_point` and below the `indoor_dry_bulb_temperature_heating_set_point` [C]. The value is added
        to and subtracted from the set point to set the upper and lower bounds of comfort bound.
    start_time_step: int, optional
        Time step to start reading variables.
    end_time_step: int, optional
        Time step to end reading variables.
    """

    DEFUALT_COMFORT_BAND = 2.0

    def __init__(
        self, month: Iterable[int], hour: Iterable[int], day_type: Iterable[int],
         indoor_dry_bulb_temperature: Iterable[float], 
        non_shiftable_load: Iterable[float], dhw_demand: Iterable[float], cooling_demand: Iterable[float], heating_demand: Iterable[float], solar_generation: Iterable[float], 
        daylight_savings_status: Iterable[int] = None, average_unmet_cooling_setpoint_difference: Iterable[float] = None, indoor_relative_humidity: Iterable[float] = None, occupant_count: Iterable[int] = None, indoor_dry_bulb_temperature_cooling_set_point: Iterable[int] = None, indoor_dry_bulb_temperature_heating_set_point: Iterable[int] = None, hvac_mode: Iterable[int] = None, power_outage: Iterable[int] = None, comfort_band: Iterable[float] = None, start_time_step: int = None, end_time_step: int = None,  seconds_per_time_step: int = None, minutes: Iterable[int] = None, seconds: Iterable[int] = None, time_step_ratios: List[float] = None, noise_std = 0.0,
        noise_seed=None,
        noise_start_index=0,
        dataset_seconds_per_time_step=None,
    ):
        super().__init__(start_time_step=start_time_step, end_time_step=end_time_step)
        self.noise_std = noise_std
        from citylearn.utilities import IndexedNoise
        noise_random_state = None if noise_seed is None else IndexedNoise(noise_seed, noise_start_index)
        self.month = np.array(month, dtype='int32')
        self.hour = np.array(hour, dtype='int32')
        self.day_type = np.array(day_type, dtype='int32')
        self.indoor_dry_bulb_temperature = np.clip(
            np.array(indoor_dry_bulb_temperature, dtype='float32') + 
            NoiseUtils.generate_gaussian_noise(indoor_dry_bulb_temperature, self.noise_std, random_state=noise_random_state),
            -90, 57
        )
        self.non_shiftable_load = np.array(non_shiftable_load, dtype = 'float32')
        self.dhw_demand = np.array(dhw_demand, dtype = 'float32')
        
        # set space demands and check there is not cooling and heating demand at same time step
        self.cooling_demand = np.array(cooling_demand, dtype = 'float32')
        self.heating_demand = np.array(heating_demand, dtype = 'float32')
        assert (self.cooling_demand*self.heating_demand).sum() == 0, 'Cooling and heating in the same time step is not allowed.'

        self.solar_generation = np.array(solar_generation, dtype = 'float32') + NoiseUtils.generate_gaussian_noise(indoor_dry_bulb_temperature, self.noise_std, random_state=noise_random_state)

        # optional
        self.minutes = np.array(minutes, dtype='int32') if minutes is not None else None
        self.seconds = np.array(seconds, dtype='int32') if seconds is not None else None
        time_delta_seconds = None

        if len(self.hour) > 1:
            if self.minutes is not None and self.seconds is not None and len(self.minutes) > 1 and len(self.seconds) > 1:
                t0 = self.hour[0] * 3600 + self.minutes[0] * 60 + self.seconds[0]
                t1 = self.hour[1] * 3600 + self.minutes[1] * 60 + self.seconds[1]
                time_delta_seconds = t1 - t0

            elif self.minutes is not None and len(self.minutes) > 1:
                t0 = self.hour[0] * 60 + self.minutes[0]
                t1 = self.hour[1] * 60 + self.minutes[1]
                time_delta_minutes = t1 - t0

                if time_delta_minutes == 0 and seconds_per_time_step is not None and float(seconds_per_time_step) < 60.0:
                    time_delta_seconds = float(seconds_per_time_step)
                else:
                    time_delta_seconds = time_delta_minutes * 60

            else:
                time_delta_hours = self.hour[1] - self.hour[0]
                time_delta_seconds = time_delta_hours * 3600

        if time_delta_seconds is not None and time_delta_seconds < 0:
            time_delta_seconds += 24 * 3600

        if time_delta_seconds == 0 and seconds_per_time_step is not None:
            time_delta_seconds = float(seconds_per_time_step)

        base_step_seconds = None

        if time_delta_seconds is not None:
            # Convert dataset spacing to seconds (guard against zero/negative values)
            candidate = max(1, time_delta_seconds)
            base_step_seconds = candidate

        if dataset_seconds_per_time_step is not None:
            if not np.isfinite(dataset_seconds_per_time_step) or dataset_seconds_per_time_step <= 0:
                raise ValueError("Invalid declared dataset interval")
            base_step_seconds = float(dataset_seconds_per_time_step)

        time_step_ratio = (
            seconds_per_time_step / base_step_seconds
            if seconds_per_time_step and base_step_seconds
            else None
        )
        self.dataset_seconds_per_time_step = base_step_seconds
        ratios = [] if time_step_ratios is None else list(time_step_ratios)
        ratios.append(time_step_ratio)
        self.time_step_ratios = ratios

        self.noise_std = noise_std

        self.daylight_savings_status = np.zeros(len(solar_generation), dtype='int32') if daylight_savings_status is None else np.array(daylight_savings_status, dtype='int32')
        self.average_unmet_cooling_setpoint_difference = np.zeros(len(solar_generation), dtype='float32') if average_unmet_cooling_setpoint_difference is None else np.array(average_unmet_cooling_setpoint_difference, dtype='float32')
        self.indoor_relative_humidity = np.zeros(len(solar_generation), dtype='float32') if indoor_relative_humidity is None else np.clip(np.array(indoor_relative_humidity, dtype = 'float32') + NoiseUtils.generate_gaussian_noise(indoor_relative_humidity, self.noise_std, random_state=noise_random_state),0,100)
        self.occupant_count = np.zeros(len(solar_generation), dtype='float32') if occupant_count is None else np.array(occupant_count, dtype='float32')
        self.indoor_dry_bulb_temperature_cooling_set_point = np.zeros(len(solar_generation), dtype='float32') if indoor_dry_bulb_temperature_cooling_set_point is None else np.array(indoor_dry_bulb_temperature_cooling_set_point, dtype='float32')
        self.indoor_dry_bulb_temperature_heating_set_point = np.zeros(len(solar_generation), dtype='float32') if indoor_dry_bulb_temperature_heating_set_point is None else np.array(indoor_dry_bulb_temperature_heating_set_point, dtype='float32')
        self.power_outage = np.zeros(len(solar_generation), dtype='float32') if power_outage is None else np.array(power_outage, dtype='float32')
        self.comfort_band = np.zeros(len(solar_generation), dtype='float32') + self.DEFUALT_COMFORT_BAND if comfort_band is None else np.array(comfort_band, dtype='float32')

        # set controlled variable defaults
        self.indoor_dry_bulb_temperature_without_control = self.indoor_dry_bulb_temperature.copy() 
        self.cooling_demand_without_control = self.cooling_demand.copy()
        self.heating_demand_without_control = self.heating_demand.copy()
        self.dhw_demand_without_control = self.dhw_demand.copy()
        self.non_shiftable_load_without_control = self.non_shiftable_load.copy()
        self.indoor_relative_humidity_without_control = self.indoor_relative_humidity.copy()
        self.indoor_dry_bulb_temperature_cooling_set_point_without_control = self.indoor_dry_bulb_temperature_cooling_set_point.copy()
        self.indoor_dry_bulb_temperature_heating_set_point_without_control = self.indoor_dry_bulb_temperature_heating_set_point.copy()

        if hvac_mode is None:
            hvac_mode = np.zeros(len(solar_generation), dtype='int32') + 1 
        
        else:
            unique = list(set(hvac_mode))

            for i in range(4):
                try:
                    unique.remove(i)
                except ValueError:
                    pass

            assert len(unique) == 0, f'Invalid hvac_mode values were found: {unique}. '\
                'Valid values are 0, 1, 2, 3 to indicate off, cooling mode, heating mode, and automatic mode.'
            
        self.hvac_mode = np.array(hvac_mode, dtype='int32')

    @property
    def time_step_ratios(self):
        """Getter for the time_step_ratio variable."""
        return self.__time_step_ratios

    @time_step_ratios.setter
    def time_step_ratios(self, value):
        """Setter for the time_step_ratio variable."""
        self.__time_step_ratios = value    
    
class LogisticRegressionOccupantParameters(TimeSeriesData):
    def __init__(self, a_increase: Iterable[float], b_increase: Iterable[float], a_decrease: Iterable[float], b_decrease: Iterable[float], start_time_step: int = None, end_time_step: int = None):
        super().__init__(start_time_step=start_time_step, end_time_step=end_time_step)
        self.a_increase = np.array(a_increase, dtype='float32')
        self.b_increase = np.array(b_increase, dtype='float32')
        self.a_decrease = np.array(a_decrease, dtype='float32')
        self.b_decrease = np.array(b_decrease, dtype='float32')
        self.occupant_interaction_indoor_dry_bulb_temperature_set_point_delta = np.zeros(len(self.a_increase), dtype='float32')
        self.occupant_interaction_indoor_dry_bulb_temperature_set_point_delta_without_control = np.zeros(len(self.a_increase), dtype='float32')

class Weather(TimeSeriesData):
    """`Building` `weather` data class.

    Parameters
    ----------
    outdoor_dry_bulb_temperature : np.array
        Outdoor dry bulb temperature time series in [C].
    outdoor_relative_humidity : np.array
        Outdoor relative humidity time series in [%].
    diffuse_solar_irradiance : np.array
        Diffuse solar irradiance time series in [W/m^2].
    direct_solar_irradiance : np.array
        Direct solar irradiance time series in [W/m^2].
    outdoor_dry_bulb_temperature_predicted_1 : np.array
        Outdoor dry bulb temperature `n` hours ahead prediction time series in [C]. `n` can be any number of hours and is typically 6 hours in existing datasets.
    outdoor_dry_bulb_temperature_predicted_2 : np.array
        Outdoor dry bulb temperature `n` hours ahead prediction time series in [C]. `n` can be any number of hours and is typically 12 hours in existing datasets.
    outdoor_dry_bulb_temperature_predicted_3 : np.array
        Outdoor dry bulb temperature `n` hours ahead prediction time series in [C]. `n` can be any number of hours and is typically 24 hours in existing datasets.
    outdoor_relative_humidity_predicted_1 : np.array
        Outdoor relative humidity `n` hours ahead prediction time series in [%]. `n` can be any number of hours and is typically 6 hours in existing datasets.
    outdoor_relative_humidity_predicted_2 : np.array
        Outdoor relative humidity `n` hours ahead prediction time series in [%]. `n` can be any number of hours and is typically 12 hours in existing datasets.
    outdoor_relative_humidity_predicted_3 : np.array
        Outdoor relative humidity `n` hours ahead prediction time series in [%]. `n` can be any number of hours and is typically 24 hours in existing datasets.
    diffuse_solar_irradiance_predicted_1 : np.array
        Diffuse solar irradiance `n` hours ahead prediction time series in [W/m^2]. `n` can be any number of hours and is typically 6 hours in existing datasets.
    diffuse_solar_irradiance_predicted_2 : np.array
        Diffuse solar irradiance `n` hours ahead prediction time series in [W/m^2]. `n` can be any number of hours and is typically 12 hours in existing datasets.
    diffuse_solar_irradiance_predicted_3 : np.array
        Diffuse solar irradiance `n` hours ahead prediction time series in [W/m^2]. `n` can be any number of hours and is typically 24 hours in existing datasets.
    direct_solar_irradiance_predicted_1 : np.array
        Direct solar irradiance `n` hours ahead prediction time series in [W/m^2]. `n` can be any number of hours and is typically 6 hours in existing datasets.
    direct_solar_irradiance_predicted_2 : np.array
        Direct solar irradiance `n` hours ahead prediction time series in [W/m^2]. `n` can be any number of hours and is typically 12 hours in existing datasets.
    direct_solar_irradiance_predicted_3 : np.array
        Direct solar irradiance `n` hours ahead prediction time series in [W/m^2]. `n` can be any number of hours and is typically 24 hours in existing datasets.
    start_time_step: int, optional
        Time step to start reading variables.
    end_time_step: int, optional
         Time step to end reading variables.
    """

    def __init__(
        self, outdoor_dry_bulb_temperature: Iterable[float], outdoor_relative_humidity: Iterable[float], diffuse_solar_irradiance: Iterable[float], direct_solar_irradiance: Iterable[float], 
        outdoor_dry_bulb_temperature_predicted_1: Iterable[float], outdoor_dry_bulb_temperature_predicted_2: Iterable[float], outdoor_dry_bulb_temperature_predicted_3: Iterable[float],
        outdoor_relative_humidity_predicted_1: Iterable[float], outdoor_relative_humidity_predicted_2: Iterable[float], outdoor_relative_humidity_predicted_3: Iterable[float],
        diffuse_solar_irradiance_predicted_1: Iterable[float], diffuse_solar_irradiance_predicted_2: Iterable[float], diffuse_solar_irradiance_predicted_3: Iterable[float],
        direct_solar_irradiance_predicted_1: Iterable[float], direct_solar_irradiance_predicted_2: Iterable[float], direct_solar_irradiance_predicted_3: Iterable[float], start_time_step: int = None, end_time_step: int = None, noise_std: float = 0.0,
        noise_seed=None,
        noise_start_index=0,
    ):
        super().__init__(start_time_step=start_time_step, end_time_step=end_time_step)
        self.noise_std = noise_std
        from citylearn.utilities import IndexedNoise
        noise_random_state = None if noise_seed is None else IndexedNoise(noise_seed, noise_start_index)
        self.outdoor_dry_bulb_temperature = np.array(outdoor_dry_bulb_temperature, dtype='float32')
        self.outdoor_relative_humidity = np.array(outdoor_relative_humidity, dtype='float32')
        self.diffuse_solar_irradiance = np.array(diffuse_solar_irradiance, dtype='float32')
        self.direct_solar_irradiance = np.array(direct_solar_irradiance, dtype='float32')

        # Add stochastic behavior by adding Gaussian noise to the data
        self.outdoor_dry_bulb_temperature += NoiseUtils.generate_gaussian_noise(self.outdoor_dry_bulb_temperature, self.noise_std, random_state=noise_random_state)
        self.outdoor_relative_humidity += NoiseUtils.generate_gaussian_noise(self.outdoor_relative_humidity, self.noise_std, random_state=noise_random_state)
        self.diffuse_solar_irradiance += NoiseUtils.generate_gaussian_noise(self.diffuse_solar_irradiance, self.noise_std, random_state=noise_random_state)
        self.direct_solar_irradiance += NoiseUtils.generate_gaussian_noise(self.direct_solar_irradiance, self.noise_std, random_state=noise_random_state)
        
        # Predicted weather values (could also introduce noise here)
        self.outdoor_dry_bulb_temperature_predicted_1 = np.array(outdoor_dry_bulb_temperature_predicted_1, dtype='float32') + NoiseUtils.generate_gaussian_noise(outdoor_dry_bulb_temperature_predicted_1, self.noise_std, random_state=noise_random_state)
        self.outdoor_dry_bulb_temperature_predicted_2 = np.array(outdoor_dry_bulb_temperature_predicted_2, dtype='float32') + NoiseUtils.generate_gaussian_noise(outdoor_dry_bulb_temperature_predicted_2, self.noise_std, random_state=noise_random_state)
        self.outdoor_dry_bulb_temperature_predicted_3 = np.array(outdoor_dry_bulb_temperature_predicted_3, dtype='float32') + NoiseUtils.generate_gaussian_noise(outdoor_dry_bulb_temperature_predicted_3, self.noise_std, random_state=noise_random_state)
        
       

        self.outdoor_relative_humidity_predicted_1 = np.array(outdoor_relative_humidity_predicted_1, dtype='float32') + NoiseUtils.generate_gaussian_noise(outdoor_relative_humidity_predicted_1, self.noise_std, random_state=noise_random_state)
        self.outdoor_relative_humidity_predicted_2 = np.array(outdoor_relative_humidity_predicted_2, dtype='float32') + NoiseUtils.generate_gaussian_noise(outdoor_relative_humidity_predicted_2, self.noise_std, random_state=noise_random_state)
        self.outdoor_relative_humidity_predicted_3 = np.array(outdoor_relative_humidity_predicted_3, dtype='float32') + NoiseUtils.generate_gaussian_noise(outdoor_relative_humidity_predicted_3, self.noise_std, random_state=noise_random_state)

        self.diffuse_solar_irradiance_predicted_1 = np.array(diffuse_solar_irradiance_predicted_1, dtype='float32') + NoiseUtils.generate_gaussian_noise(diffuse_solar_irradiance_predicted_1, self.noise_std, random_state=noise_random_state)
        self.diffuse_solar_irradiance_predicted_2 = np.array(diffuse_solar_irradiance_predicted_2, dtype='float32') + NoiseUtils.generate_gaussian_noise(diffuse_solar_irradiance_predicted_2, self.noise_std, random_state=noise_random_state)
        self.diffuse_solar_irradiance_predicted_3 = np.array(diffuse_solar_irradiance_predicted_3, dtype='float32') + NoiseUtils.generate_gaussian_noise(diffuse_solar_irradiance_predicted_3, self.noise_std, random_state=noise_random_state)

        self.direct_solar_irradiance_predicted_1 = np.array(direct_solar_irradiance_predicted_1, dtype='float32') + NoiseUtils.generate_gaussian_noise(direct_solar_irradiance_predicted_1, self.noise_std, random_state=noise_random_state)
        self.direct_solar_irradiance_predicted_2 = np.array(direct_solar_irradiance_predicted_2, dtype='float32') + NoiseUtils.generate_gaussian_noise(direct_solar_irradiance_predicted_2, self.noise_std, random_state=noise_random_state)
        self.direct_solar_irradiance_predicted_3 = np.array(direct_solar_irradiance_predicted_3, dtype='float32') + NoiseUtils.generate_gaussian_noise(direct_solar_irradiance_predicted_3, self.noise_std, random_state=noise_random_state)



class Pricing(TimeSeriesData):
    """`Building` `pricing` data class.

    Parameters
    ----------
    electricity_pricing : np.array
        Electricity pricing time series in [$/kWh].
    electricity_pricing_predicted_1 : np.array
        Electricity pricing `n` hours ahead prediction time series in [$/kWh]. `n` can be any number of hours and is typically 1 or 6 hours in existing datasets.
    electricity_pricing_predicted_2 : np.array
        Electricity pricing `n` hours ahead prediction time series in [$/kWh]. `n` can be any number of hours and is typically 2 or 12 hours in existing datasets.
    electricity_pricing_predicted_3 : np.array
        Electricity pricing `n` hours ahead prediction time series in [$/kWh]. `n` can be any number of hours and is typically 3 or 24 hours in existing datasets.
    start_time_step: int, optional
        Time step to start reading variables.
    end_time_step: int, optional
         Time step to end reading variables.
    """

    def __init__(
        self, electricity_pricing: Iterable[float], electricity_pricing_predicted_1: Iterable[float], electricity_pricing_predicted_2: Iterable[float], 
        electricity_pricing_predicted_3: Iterable[float], start_time_step: int = None, end_time_step: int = None, noise_std: float = 0.0,
        noise_seed=None,
        noise_start_index=0,
    ):
        super().__init__(start_time_step=start_time_step, end_time_step=end_time_step)
        self.noise_std = noise_std
        from citylearn.utilities import IndexedNoise
        noise_random_state = None if noise_seed is None else IndexedNoise(noise_seed, noise_start_index)
        self.electricity_pricing = np.array(electricity_pricing, dtype='float32') + NoiseUtils.generate_gaussian_noise(electricity_pricing, self.noise_std, random_state=noise_random_state)
        self.electricity_pricing_predicted_1 = np.array(electricity_pricing_predicted_1, dtype='float32') + NoiseUtils.generate_gaussian_noise(electricity_pricing_predicted_1, self.noise_std, random_state=noise_random_state)
        self.electricity_pricing_predicted_2 = np.array(electricity_pricing_predicted_2, dtype='float32') + NoiseUtils.generate_gaussian_noise(electricity_pricing_predicted_2, self.noise_std, random_state=noise_random_state)
        self.electricity_pricing_predicted_3 = np.array(electricity_pricing_predicted_3, dtype='float32') + NoiseUtils.generate_gaussian_noise(electricity_pricing_predicted_3, self.noise_std, random_state=noise_random_state)

    def as_dict(self, time_step) -> dict:
        """Return a dictionary representation of the current pricing data.
        
        Returns
        -------
        dict
            Dictionary containing current electricity pricing and predictions,
            with keys matching the class attribute names.
        """
        return {
            'electricity_pricing-$/kWh': self.electricity_pricing[time_step],
            'electricity_pricing_predicted_1-$/kWh': self.electricity_pricing_predicted_1[time_step],
            'electricity_pricing_predicted_2-$/kWh': self.electricity_pricing_predicted_2[time_step],
            'electricity_pricing_predicted_3-$/kWh': self.electricity_pricing_predicted_3[time_step],
        } 

class CarbonIntensity(TimeSeriesData):
    """`Building` `carbon_intensity` data class.

    Parameters
    ----------
    carbon_intensity : np.array
        Grid carbon emission rate time series in [kg_co2/kWh].
    start_time_step: int, optional
        Time step to start reading variables.
    end_time_step: int, optional
         Time step to end reading variables.
    """

    def __init__(self, carbon_intensity: Iterable[float], start_time_step: int = None, end_time_step: int = None, noise_std: float = 0.0,
        noise_seed=None,
        noise_start_index=0,
    ):
        self.noise_std = noise_std
        from citylearn.utilities import IndexedNoise
        noise_random_state = None if noise_seed is None else IndexedNoise(noise_seed, noise_start_index)
        super().__init__(start_time_step=start_time_step, end_time_step=end_time_step)
        self.carbon_intensity = np.array(carbon_intensity, dtype='float32') + NoiseUtils.generate_gaussian_noise(carbon_intensity, self.noise_std, random_state=noise_random_state)

class ChargerSimulation(TimeSeriesData):
    """Charger-centric electric vehicle simulation data class.

    This class models the charging schedule of electric vehicles from the perspective
    of a specific charger, with one entry per timestep indicating the state of a connected or incoming EV.

    Attributes
    ----------
    electric_vehicle_charger_state : np.array
        State of the electric vehicle:
            1: 'Parked, plugged in, and ready to charge'
            2: 'Incoming to a charger'
            3: 'Commuting (vehicle is away)'
    electric_vehicle_id : np.array
        Identifier for the electric vehicle.
    electric_vehicle_session_id : np.array
        Identifier for the charging session. This remains distinct from the EV
        identifier because the same vehicle may begin a new session without an
        intervening disconnected charger row.
    electric_vehicle_departure_time : np.array
        Number of time steps expected until the EV departs from the charger (only for state 1).
        Defaults to -1 when not present.
    electric_vehicle_required_soc_departure : np.array
        Target SOC percentage required for the EV at departure time (only for state 1),
        normalized to the [0, 1] range and with added Gaussian noise if provided.
        Defaults to -0.1 when not present.
    electric_vehicle_estimated_arrival_time : np.array
        Number of time steps expected until the EV arrives at the charger (only for state 2).
        Defaults to -1 when not present.
    electric_vehicle_estimated_soc_arrival : np.array
        Estimated SOC percentage at the time of arrival to the charger (only for state 2),
        normalized to the [0, 1] range and with optional Gaussian noise.
        Defaults to -0.1 when not present.
    """

    def __init__(
        self,
        electric_vehicle_charger_state: Iterable[int],
        electric_vehicle_id: Iterable[str],
        electric_vehicle_departure_time: Iterable[float],
        electric_vehicle_required_soc_departure: Iterable[float],
        electric_vehicle_estimated_arrival_time: Iterable[float],
        electric_vehicle_estimated_soc_arrival: Iterable[float],
        electric_vehicle_session_id: Iterable[str] = None,
        start_time_step: int = None,
        end_time_step: int = None,
        noise_std: float = 1.0,
        noise_seed=None,
        noise_start_index=0,
    ):
        """Initialize ChargerSchedule from charger-centric EV CSV input."""
        super().__init__(start_time_step=start_time_step, end_time_step=end_time_step)

        self.noise_std = noise_std
        from citylearn.utilities import IndexedNoise
        noise_random_state = None if noise_seed is None else IndexedNoise(noise_seed, noise_start_index)

        default_time_value = -1
        default_soc_value = -0.1

        self.electric_vehicle_charger_state = np.array([
            int(str(s)) if str(s).isdigit() else np.nan
            for s in electric_vehicle_charger_state
        ], dtype='float32')

        self.electric_vehicle_id = np.array(electric_vehicle_id, dtype=object)
        self.electric_vehicle_session_id = np.array(
            [""] * len(self.electric_vehicle_id)
            if electric_vehicle_session_id is None
            else electric_vehicle_session_id,
            dtype=object,
        )


        departure_time_arr = np.array(electric_vehicle_departure_time, dtype='float32')
        self.electric_vehicle_departure_time = np.where(
            np.isnan(departure_time_arr), default_time_value, departure_time_arr
        ).astype('int32')

        arrival_time_arr = np.array(electric_vehicle_estimated_arrival_time, dtype='float32')
        self.electric_vehicle_estimated_arrival_time = np.where(
            np.isnan(arrival_time_arr), default_time_value, arrival_time_arr
        ).astype('int32')

        self.electric_vehicle_required_soc_departure = self.normalize_soc_series(
            electric_vehicle_required_soc_departure,
            default_soc_value=default_soc_value,
            noise_std=self.noise_std,
            random_state=noise_random_state,
        )

        self.electric_vehicle_estimated_soc_arrival = self.normalize_soc_series(
            electric_vehicle_estimated_soc_arrival,
            default_soc_value=default_soc_value,
            noise_std=self.noise_std,
            random_state=noise_random_state,
        )

    @staticmethod
    def normalize_soc_series(
        values: Iterable[float],
        default_soc_value: float = -0.1,
        noise_std: float = 0.0,
        random_state=None,
    ) -> np.ndarray:
        """Normalize SOC inputs that may be fractions or percentages."""

        raw = np.array(values, dtype='float32')
        raw = np.where(np.isnan(raw), default_soc_value, raw)
        normalized = np.full(raw.shape, float(default_soc_value), dtype='float32')

        valid = (raw != default_soc_value) & (raw >= 0.0)
        fraction = valid & (raw >= 0.0) & (raw <= 1.0)
        percent = valid & (raw > 1.0)

        normalized[fraction] = raw[fraction]
        normalized[percent] = raw[percent] / 100.0

        if noise_std:
            noise = NoiseUtils.generate_gaussian_noise(normalized, noise_std, random_state=random_state) / 100.0
            normalized[valid] = normalized[valid] + noise[valid]

        normalized[valid] = np.clip(normalized[valid], 0.0, 1.0)
        return normalized.astype('float32')

class EscalatorSimulation(TimeSeriesData):
    """Time series inputs for an escalator controlled at each simulation step.

    The model deliberately stays aggregate: passengers are a demand signal, not
    individual agents or queues.  This makes it suitable for energy-management
    experiments while preserving a traceable service KPI when an escalator is
    left in standby while passengers are expected.
    """

    REQUIRED_COLUMNS = {
        'time_step',
        'passengers_from_trains_15min',
        'background_pedestrians_15min',
        'passengers_expected_15min',
        'people_detected',
        'arriving_trains',
        'departing_trains',
        'minutes_to_next_train',
        'available',
    }

    @classmethod
    def from_dataframe(cls, dataframe: pd.DataFrame, source_label: str = None) -> 'EscalatorSimulation':
        """Validate and construct an escalator simulation from a CSV dataframe."""

        source_label = source_label or 'escalator'
        missing = cls.REQUIRED_COLUMNS.difference(dataframe.columns)
        if missing:
            raise ValueError(f'{source_label} is missing columns: {sorted(missing)}.')

        frame = dataframe.copy()
        numeric_columns = list(cls.REQUIRED_COLUMNS)
        for column in numeric_columns:
            frame[column] = pd.to_numeric(frame[column], errors='coerce')

        if frame[numeric_columns].isna().any().any() or not np.isfinite(frame[numeric_columns].to_numpy(dtype='float64')).all():
            raise ValueError(f'{source_label} contains non-finite values in required columns.')

        time_steps = frame['time_step'].to_numpy(dtype='int64')
        if not np.array_equal(time_steps, np.arange(len(frame), dtype='int64')):
            raise ValueError(f'{source_label}.time_step must be contiguous and start at 0.')

        non_negative = (
            'passengers_from_trains_15min', 'background_pedestrians_15min',
            'passengers_expected_15min', 'arriving_trains', 'departing_trains',
            'minutes_to_next_train',
        )
        if (frame[list(non_negative)] < 0.0).any().any():
            raise ValueError(f'{source_label} has a negative demand, train-count or time-to-train value.')

        for column in ('people_detected', 'available'):
            values = frame[column].to_numpy(dtype='float64')
            if not np.isin(values, (0.0, 1.0)).all():
                raise ValueError(f'{source_label}.{column} must contain only 0 or 1.')

        expected = frame['passengers_from_trains_15min'] + frame['background_pedestrians_15min']
        if not np.allclose(
            frame['passengers_expected_15min'].to_numpy(dtype='float64'),
            expected.to_numpy(dtype='float64'), rtol=1.0e-5, atol=1.0e-4,
        ):
            raise ValueError(
                f'{source_label}.passengers_expected_15min must equal '
                'passengers_from_trains_15min + background_pedestrians_15min.'
            )

        instance = cls()
        for column in dataframe.columns:
            values = frame[column].to_numpy(copy=False)
            if column in ('people_detected', 'available', 'arriving_trains', 'departing_trains', 'time_step'):
                values = values.astype('int32')
            elif np.issubdtype(values.dtype, np.number):
                values = values.astype('float32')
            setattr(instance, column, values)
        return instance


class DeferrableApplianceSimulation:
    """Sparse deferrable-appliance cycle catalogue and flexibility schedule.

    Cycle profile energy values are always interpreted as kWh per simulation step.
    Schedule time fields are global simulation time-step indices.
    """

    PROFILE_REQUIRED_COLUMNS = {
        'profile_id',
        'duration_steps',
        'total_energy_kwh',
        'load_profile',
    }
    SCHEDULE_REQUIRED_COLUMNS = {
        'cycle_id',
        'profile_id',
        'earliest_start_time_step',
        'latest_start_time_step',
        'deadline_time_step',
        'priority',
        'must_run',
    }

    def __init__(
        self,
        *,
        cycle_profiles: Mapping[str, Mapping[str, Any]],
        flexibility_schedule: Iterable[Mapping[str, Any]],
        source_label: str = None,
    ):
        self.source_label = source_label or 'deferrable_appliance'
        self.cycle_profiles = dict(cycle_profiles)
        self.flexibility_schedule = list(flexibility_schedule)
        self._validate_non_overlapping_schedule()

    @classmethod
    def from_dataframes(
        cls,
        *,
        cycle_profiles: pd.DataFrame,
        flexibility_schedule: pd.DataFrame,
        source_label: str = None,
    ) -> 'DeferrableApplianceSimulation':
        source_label = source_label or 'deferrable_appliance'
        missing_profiles = cls.PROFILE_REQUIRED_COLUMNS.difference(set(cycle_profiles.columns))
        if missing_profiles:
            raise ValueError(f'{source_label}.cycle_profiles is missing columns: {sorted(missing_profiles)}.')

        missing_schedule = cls.SCHEDULE_REQUIRED_COLUMNS.difference(set(flexibility_schedule.columns))
        if missing_schedule:
            raise ValueError(f'{source_label}.flexibility_schedule is missing columns: {sorted(missing_schedule)}.')

        profiles: Dict[str, Mapping[str, Any]] = {}
        for row_index, row in cycle_profiles.iterrows():
            profile_id = str(row['profile_id']).strip()
            if profile_id == '' or profile_id.lower() == 'nan':
                raise ValueError(f'{source_label}.cycle_profiles[{row_index}].profile_id is required.')
            if profile_id in profiles:
                raise ValueError(f"{source_label}.cycle_profiles contains duplicate profile_id '{profile_id}'.")

            load_profile = cls.parse_load_profile(row['load_profile'])
            if load_profile.size == 0:
                raise ValueError(f"{source_label}.cycle_profiles profile '{profile_id}' has an empty load_profile.")

            try:
                duration_steps = int(row['duration_steps'])
            except Exception as exc:
                raise ValueError(f"{source_label}.cycle_profiles profile '{profile_id}' duration_steps must be an integer.") from exc

            if duration_steps <= 0:
                raise ValueError(f"{source_label}.cycle_profiles profile '{profile_id}' duration_steps must be > 0.")
            if duration_steps != int(load_profile.size):
                raise ValueError(
                    f"{source_label}.cycle_profiles profile '{profile_id}' duration_steps={duration_steps} "
                    f"does not match load_profile length={load_profile.size}."
                )

            try:
                total_energy = float(row['total_energy_kwh'])
            except Exception as exc:
                raise ValueError(f"{source_label}.cycle_profiles profile '{profile_id}' total_energy_kwh must be numeric.") from exc

            if not np.isfinite(total_energy) or total_energy < 0.0:
                raise ValueError(f"{source_label}.cycle_profiles profile '{profile_id}' total_energy_kwh must be finite and >= 0.")

            profile_sum = float(np.sum(load_profile))
            if abs(profile_sum - total_energy) > max(1.0e-6, 1.0e-5 * max(abs(total_energy), 1.0)):
                raise ValueError(
                    f"{source_label}.cycle_profiles profile '{profile_id}' total_energy_kwh={total_energy} "
                    f"does not match load_profile sum={profile_sum}."
                )

            profiles[profile_id] = {
                'profile_id': profile_id,
                'duration_steps': duration_steps,
                'total_energy_kwh': total_energy,
                'load_profile': load_profile.astype('float32'),
            }

        schedule = []
        seen_cycle_ids = set()
        for row_index, row in flexibility_schedule.iterrows():
            cycle_id = str(row['cycle_id']).strip()
            if cycle_id == '' or cycle_id.lower() == 'nan':
                raise ValueError(f'{source_label}.flexibility_schedule[{row_index}].cycle_id is required.')
            if cycle_id in seen_cycle_ids:
                raise ValueError(f"{source_label}.flexibility_schedule contains duplicate cycle_id '{cycle_id}'.")
            seen_cycle_ids.add(cycle_id)

            profile_id = str(row['profile_id']).strip()
            if profile_id not in profiles:
                raise ValueError(
                    f"{source_label}.flexibility_schedule cycle '{cycle_id}' references unknown profile_id '{profile_id}'."
                )
            profile = profiles[profile_id]

            try:
                earliest = int(row['earliest_start_time_step'])
                latest = int(row['latest_start_time_step'])
                deadline = int(row['deadline_time_step'])
            except Exception as exc:
                raise ValueError(
                    f"{source_label}.flexibility_schedule cycle '{cycle_id}' time-step fields must be integers."
                ) from exc

            if earliest < 0 or latest < 0 or deadline < 0:
                raise ValueError(f"{source_label}.flexibility_schedule cycle '{cycle_id}' time-step fields must be >= 0.")
            if earliest > latest:
                raise ValueError(
                    f"{source_label}.flexibility_schedule cycle '{cycle_id}' earliest_start_time_step "
                    f"cannot be greater than latest_start_time_step."
                )
            if latest + int(profile['duration_steps']) - 1 > deadline:
                raise ValueError(
                    f"{source_label}.flexibility_schedule cycle '{cycle_id}' cannot finish by deadline when "
                    f"started at latest_start_time_step."
                )

            try:
                priority = float(row['priority'])
            except Exception as exc:
                raise ValueError(f"{source_label}.flexibility_schedule cycle '{cycle_id}' priority must be numeric.") from exc
            if not np.isfinite(priority):
                raise ValueError(f"{source_label}.flexibility_schedule cycle '{cycle_id}' priority must be finite.")

            schedule.append({
                'cycle_id': cycle_id,
                'profile_id': profile_id,
                'earliest_start_time_step': earliest,
                'latest_start_time_step': latest,
                'deadline_time_step': deadline,
                'priority': float(np.clip(priority, 0.0, 1.0)),
                'must_run': parse_bool(row['must_run'], default=True, path=f'{source_label}.flexibility_schedule.{cycle_id}.must_run'),
                'duration_steps': int(profile['duration_steps']),
                'total_energy_kwh': float(profile['total_energy_kwh']),
                'load_profile': profile['load_profile'],
            })

        schedule.sort(key=lambda item: (item['earliest_start_time_step'], item['latest_start_time_step'], item['cycle_id']))
        return cls(cycle_profiles=profiles, flexibility_schedule=schedule, source_label=source_label)

    @staticmethod
    def parse_load_profile(profile) -> np.ndarray:
        if profile is None:
            return np.array([], dtype='float32')

        if isinstance(profile, (list, tuple, np.ndarray)):
            try:
                values = np.array(profile, dtype='float32').flatten()
            except (TypeError, ValueError):
                return np.array([], dtype='float32')
        else:
            text = str(profile).strip()
            if text == '' or text.lower() in {'nan', 'none'} or text == '-1':
                return np.array([], dtype='float32')
            try:
                parsed = ast.literal_eval(text)
            except (SyntaxError, ValueError):
                return np.array([], dtype='float32')
            if np.isscalar(parsed):
                parsed = [parsed]
            try:
                values = np.array(parsed, dtype='float32').flatten()
            except (TypeError, ValueError):
                return np.array([], dtype='float32')

        if values.size == 0:
            return np.array([], dtype='float32')

        values = values[np.isfinite(values)]
        if values.size == 0 or np.any(values < 0.0):
            return np.array([], dtype='float32')

        return values.astype('float32')

    def _validate_non_overlapping_schedule(self):
        previous = None
        for cycle in self.flexibility_schedule:
            if previous is not None and int(cycle['earliest_start_time_step']) <= int(previous['deadline_time_step']):
                raise ValueError(
                    f"{self.source_label}.flexibility_schedule has overlapping cycles for one appliance: "
                    f"'{previous['cycle_id']}' and '{cycle['cycle_id']}'."
                )
            previous = cycle

class WashingMachineSimulation(TimeSeriesData):
    """Washing Machine Simulation data class.

    Attributes
    ----------
    day_type : np.array
        Type of the day (e.g., weekday/weekend).
    hour : np.array
        Hour of the day when the washing machine is scheduled.
    start_time_step : np.array
        Start time step of the washing machine usage.
    end_time_step : np.array
        End time step of the washing machine usage.
    load_profile : np.array
        List of power consumption values during the washing machine's cycle.
    """

    def __init__(
            self,
            day_type: Iterable[int],
            hour: Iterable[int],
            wm_start_time_step: Iterable[int],
            wm_end_time_step: Iterable[int],
            load_profile: Iterable[str],
            start: int = None,
            end: int = None
    ):
        """Initialize WashingMachineSimulation."""
        super().__init__(start_time_step=start, end_time_step=end)

        default_time_value = -1

        self.day_type = np.array(day_type, dtype='int32')
        self.hour = np.array(hour, dtype='int32')

        start_time_step_arr = np.array(wm_start_time_step, dtype=float)
        end_time_step_arr = np.array(wm_end_time_step, dtype=float)
        

        self.wm_start_time_step = np.where(np.isnan(start_time_step_arr), default_time_value, start_time_step_arr).astype('int32')
        self.wm_end_time_step = np.where(np.isnan(end_time_step_arr), default_time_value, end_time_step_arr).astype('int32')

        # Parse load_profile strings like '[10,20,30]' into lists of floats.
        empty_profile = np.array([], dtype=float)
        profile_cache = {}

        def parse_profile(profile_str):
            if profile_str is None:
                return empty_profile

            if isinstance(profile_str, (list, tuple, np.ndarray)):
                try:
                    return np.array(profile_str, dtype=float).flatten()
                except (TypeError, ValueError):
                    return empty_profile

            text = str(profile_str).strip()
            if text == '' or text.lower() in {'nan', 'none'} or text == '-1':
                return empty_profile

            cached = profile_cache.get(text)
            if cached is not None:
                return cached

            try:
                parsed = ast.literal_eval(text)
            except (SyntaxError, ValueError):
                return empty_profile

            if np.isscalar(parsed):
                try:
                    value = float(parsed)
                except (TypeError, ValueError):
                    return empty_profile

                if not np.isfinite(value) or value < 0.0:
                    return empty_profile

                values = np.array([value], dtype=float)
                profile_cache[text] = values
                return values

            try:
                values = np.array(parsed, dtype=float).flatten()
            except (TypeError, ValueError):
                return empty_profile

            values = values[np.isfinite(values)]
            values = values[values >= 0.0]
            profile_cache[text] = values
            return values

        self.load_profile = np.array([parse_profile(lp) for lp in load_profile], dtype=object)
