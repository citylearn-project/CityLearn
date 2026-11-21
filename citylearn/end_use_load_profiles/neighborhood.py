import concurrent.futures
from copy import deepcopy
import os
from enum import Enum, unique
from pathlib import Path
import random
import shutil
from typing import Any, Callable, List, Mapping, Tuple, Union
from doe_xstock.data import VersionDatasetType
from doe_xstock.end_use_load_profiles import EndUseLoadProfiles
from doe_xstock.simulate import EndUseLoadProfilesEnergyPlusSimulator, OpenStudioModelEditor
import numpy as np
import pandas as pd
from sklearn.metrics import mean_squared_error, mean_absolute_percentage_error
import torch
from citylearn import random_streams
from citylearn.agents.base import Agent, NoControlAgent
from citylearn.base import Environment
from citylearn.building import Building
from citylearn.citylearn import CityLearnEnv
from citylearn.data import get_settings
from citylearn.dynamics import LSTMDynamics
from citylearn.end_use_load_profiles.clustering import MetadataClustering
from citylearn.end_use_load_profiles.lstm_model.model_generation_wrapper import run_one_model
from citylearn.end_use_load_profiles.simulate import EndUseLoadProfilesEnergyPlusPartialLoadSimulator
from citylearn.preprocessing import PeriodicNormalization, Normalize
from citylearn.utilities import FileHandler

BuildingSimulators = Mapping[
    str, 
    Union[EndUseLoadProfilesEnergyPlusSimulator, EndUseLoadProfilesEnergyPlusSimulator, List[EndUseLoadProfilesEnergyPlusPartialLoadSimulator]]
]
BuildingsSimulators = List[BuildingSimulators]

@unique
class SampleMethod(Enum):
    RANDOM = 0
    METADATA_CLUSTER_FREQUENCY = 1

class NeighborhoodBuild:
    def __init__(
        self, schema_filepath: Path, citylearn_simulation_test_evaluation: pd.DataFrame, citylearn_simulation_lstm_prediction_data: Mapping[int, pd.DataFrame], 
        citylearn_simulation_lstm_error_data: Mapping[int, pd.DataFrame], lstm_test_data: Mapping[int, pd.DataFrame], bldg_ids: List[int], sample_cluster_labels: List[int], 
        sample_metadata: Mapping[str, Any], simulators: BuildingsSimulators
    ):
        self.__schema_filepath = schema_filepath
        self.__citylearn_simulation_test_evaluation = citylearn_simulation_test_evaluation
        self.__citylearn_simulation_lstm_prediction_data = citylearn_simulation_lstm_prediction_data
        self.__citylearn_simulation_lstm_error_data = citylearn_simulation_lstm_error_data
        self.__lstm_test_data = lstm_test_data
        self.__bldg_ids = bldg_ids
        self.__sample_cluster_labels = sample_cluster_labels
        self.__sample_metadata = sample_metadata
        self.__simulators = simulators

    @property
    def schema_filepath(self) -> Path:
        return self.__schema_filepath

    @property
    def citylearn_simulation_test_evaluation(self) -> pd.DataFrame:
        return self.__citylearn_simulation_test_evaluation
    
    @property
    def citylearn_simulation_lstm_prediction_data(self) -> List[pd.DataFrame]:
        return self.__citylearn_simulation_lstm_prediction_data
    
    @property
    def citylearn_simulation_lstm_error_data(self) -> List[pd.DataFrame]:
        return self.__citylearn_simulation_lstm_error_data
    
    @property
    def lstm_test_data(self) -> List[pd.DataFrame]:
        return self.__lstm_test_data
    
    @property
    def bldg_ids(self) -> List[int]:
        return self.__bldg_ids
    
    @property
    def sample_cluster_labels(self) -> List[int]:
        return self.__sample_cluster_labels
    
    @property
    def sample_metadata(self) -> Mapping[str, Any]:
        return self.__sample_metadata
    
    @property
    def simulators(self) -> BuildingsSimulators:
        return self.__simulators

class Neighborhood:
    __BUILDING_TYPE_COLUMN = 'in.geometry_building_type_recs'
    __SINGLE_FAMILY_BUILDING_TYPE_NAME = 'Single-Family Detached'
    __COUNTY_COLUMN = 'in.resstock_county_id'

    def __init__(
        self, weather_data: str = None, year_of_publication: int = None, release: int = None, cache: bool = None,
        energyplus_output_directory: Union[Path, str] = None, dataset_directory: Union[Path, str] = None,
        max_workers: int = None, random_seed: int = None, random_stream_version: Union[str, int] = None
    ) -> None:
        self.__end_use_load_profiles = EndUseLoadProfiles(
            dataset_type=VersionDatasetType.RESSTOCK,
            weather_data=weather_data,
            year_of_publication=year_of_publication,
            release=release,
            cache=cache,
        )
        self.energyplus_output_directory = energyplus_output_directory
        self.dataset_directory = dataset_directory
        self.max_workers = max_workers
        self.random_seed = random_seed
        self.random_stream_version = random_stream_version

    @property
    def end_use_load_profiles(self) -> EndUseLoadProfiles:
        return self.__end_use_load_profiles
    
    @property
    def energyplus_output_directory(self) -> Union[Path, str]:
        return self.__energyplus_output_directory
    
    @property
    def dataset_directory(self) -> Union[Path, str]:
        return self.__dataset_directory
    
    @property
    def max_workers(self) -> int:
        return self.__max_workers
    
    @property
    def random_seed(self) -> int:
        return self.__random_seed

    @energyplus_output_directory.setter
    def energyplus_output_directory(self, value: Union[Path, str]):
        self.__energyplus_output_directory = 'neighborhood_energyplus_output' if value is None else value

    @dataset_directory.setter
    def dataset_directory(self, value: Union[Path, str]):
        self.__dataset_directory = 'neighborhood_datasets' if value is None else value

    @max_workers.setter
    def max_workers(self, value: int):
        self.__max_workers = value

    @property
    def random_stream_version(self) -> str:
        """Derivation of the partial-load simulation seeds; see :py:func:`citylearn.random_streams.partial_load_simulation_seed`."""

        return self.__random_stream_version

    @random_seed.setter
    def random_seed(self, value: int):
        self.__random_seed = random.randint(*Environment.DEFAULT_RANDOM_SEED_RANGE) if value is None else value

    @random_stream_version.setter
    def random_stream_version(self, value: Union[str, int]):
        self.__random_stream_version = random_streams.parse_random_stream_version(value)

    def build(
        self, idd_filepath: Union[Path, str], bldg_ids: List[int] = None, include_lstm_models: bool = None, test_lstm_models: bool = None, 
        test_citylearn_simulation: bool = None, delete_energyplus_simulation_output: bool = None, sample_buildings_kwargs: Mapping[str, Any] = None, 
        energyplus_simulation_kwargs: Mapping[str, Any] = None, train_lstm_kwargs: Mapping[str, Any] = None, schema_kwargs: Mapping[str, Any] = None, 
        test_citylearn_simulation_kwargs: Mapping[str, Any] = None
    ) -> NeighborhoodBuild:
        sample_buildings_kwargs = {} if sample_buildings_kwargs is None else sample_buildings_kwargs
        energyplus_simulation_kwargs = {} if energyplus_simulation_kwargs is None else energyplus_simulation_kwargs
        train_lstm_kwargs = {} if train_lstm_kwargs is None else train_lstm_kwargs
        schema_kwargs = {} if schema_kwargs is None else schema_kwargs
        test_citylearn_simulation_kwargs = {} if test_citylearn_simulation_kwargs is None else test_citylearn_simulation_kwargs
        include_lstm_models = True if include_lstm_models is None else include_lstm_models
        test_citylearn_simulation = True if test_citylearn_simulation is None else test_citylearn_simulation
        test_lstm_models = True if test_lstm_models is None else test_lstm_models
        delete_energyplus_simulation_output = False if delete_energyplus_simulation_output is None else delete_energyplus_simulation_output

        labels = None
        sample_metadata = None
        simulators = None
        lstm_training_data = None
        lstm_models = None
        schema_filepath = None
        citylearn_simulation_evaluation = None 
        citylearn_simulation_lstm_prediction_data = None
        citylearn_simulation_lstm_error_data = None
        lstm_test_data = None

        # sample buildings
        if bldg_ids is None:
            bldg_ids, labels, sample_metadata = self.sample_buildings(**sample_buildings_kwargs)
        
        else:
            pass
        
        # run energyplus simulations
        simulators = self.simulate_energy_plus(bldg_ids, idd_filepath, **energyplus_simulation_kwargs)

        # train LSTM models
        if include_lstm_models:
            lstm_training_data = self.get_lstm_training_data(simulators)
            lstm_models = self.train_lstm(lstm_training_data, **train_lstm_kwargs)
        
        else:
            pass
        
        # generate schema
        schema_filepath = self.set_schema(simulators, bldg_ids, lstm_models=lstm_models, **schema_kwargs)

        # confirm schema initializes correctly in CityLearn and simulation completes without errors
        if test_citylearn_simulation:
            citylearn_simulation_evaluation, citylearn_simulation_lstm_prediction_data, citylearn_simulation_lstm_error_data \
            = self.test_citylearn_simulation(schema_filepath, **test_citylearn_simulation_kwargs)
        
        else:
            pass
        
        # run test on generated LSTM training data for all partial load simulation references
        if include_lstm_models and test_lstm_models:
            lstm_test_data = self.multiprocess_test_lstm(lstm_training_data, schema_filepath)
        
        else:
            pass
        
        # delete energyplus output files to save space
        if delete_energyplus_simulation_output:
            self.delete_energyplus_simulation_output(simulators)
        
        else:
            pass

        return NeighborhoodBuild(
            schema_filepath=schema_filepath,
            citylearn_simulation_test_evaluation=citylearn_simulation_evaluation,
            citylearn_simulation_lstm_prediction_data=citylearn_simulation_lstm_prediction_data,
            citylearn_simulation_lstm_error_data=citylearn_simulation_lstm_error_data,
            lstm_test_data=lstm_test_data,
            bldg_ids=bldg_ids,
            sample_cluster_labels=labels,
            sample_metadata=sample_metadata,
            simulators=simulators
        )
    
    def delete_energyplus_simulation_output(self, simulators: BuildingsSimulators):
        directories = [Path(s['ideal'].output_directory).parents[0] for s in simulators]

        for d in directories:
            if os.path.isdir(d):
                shutil.rmtree(d)
            
            else:
                pass

    def multiprocess_test_lstm(self, training_data: List[pd.DataFrame], schema_filepath: Path) -> List[pd.DataFrame]:
        test_data = [None]*len(training_data)

        with concurrent.futures.ProcessPoolExecutor(max_workers=self.max_workers) as executor:
            results = [executor.submit(
                self.test_lstm, 
                *(i, td.copy(), schema_filepath)
            ) for i, td in enumerate(training_data)]
            
            for future in concurrent.futures.as_completed(results):
                result = future.result()
                test_data[result[0]] = result[1]

        return test_data
    
    def test_lstm(self, bldg_ix: int, training_data: pd.DataFrame, schema_filepath: Path) -> Tuple[int, pd.DataFrame]:
        # set data
        schema = FileHandler.read_json(schema_filepath)
        schema_directory = Path(schema_filepath).parents[0]
        bldg_key = list(schema['buildings'].keys())[bldg_ix]
        dynamics_model = schema['buildings'][bldg_key]['dynamics']
        normalization_minimum = dynamics_model['attributes']['input_normalization_minimum']
        normalization_maximum = dynamics_model['attributes']['input_normalization_maximum']
        observation_names = dynamics_model['attributes']['input_observation_names']
        periodic_observations = Building.get_periodic_observation_metadata()
        training_data = training_data.sort_values(['reference', 'timestep'])

        # type cast
        columns = [c for c in observation_names + list(periodic_observations.keys()) if not c.endswith('_sin') and not c.endswith('_cos')]
        training_data[columns] = training_data[columns].astype('float32')

        ## cyclic normalization
        for c, m in periodic_observations.items():
            result = training_data[c]*PeriodicNormalization(x_max=m[-1])
            result = pd.DataFrame(result.tolist(), index=result.index)
            training_data[f'{c}_sin'] = result[0].tolist()
            training_data[f'{c}_cos'] = result[1].tolist()

        input_columns = []
        
        # then normalize all columns between 0 and 1 including the cyclic columns
        for i, c in enumerate(observation_names):
            input_columns.append(f'{c}_norm')
            training_data[input_columns[-1]] = training_data[c]*Normalize(normalization_minimum[i], normalization_maximum[i])

        training_data[input_columns] = training_data[input_columns].astype('float32')
        independent_columns = input_columns[:-1]
        dependent_column = input_columns[-1]

        # initialize trained model
        model = LSTMDynamics(
            os.path.join(schema_directory, dynamics_model['attributes']['filename']),
            observation_names,
            normalization_minimum,
            normalization_maximum,
            hidden_size=dynamics_model['attributes']['hidden_size'],
            num_layers=dynamics_model['attributes']['num_layers'],
            lookback=dynamics_model['attributes']['lookback']
        )

        # make predictions
        data_list = []

        for _, reference_data in training_data.groupby('reference'):
            reference_data = reference_data.reset_index(drop=True)
            model.reset()

            for i in range(model.lookback, reference_data.shape[0]):
                x_independent = reference_data[independent_columns].iloc[i - model.lookback + 1:i + 1].values
                x_dependent = reference_data[[dependent_column]].iloc[i - model.lookback:i].values
                x = np.append(x_independent, x_dependent, axis=1)
                x = torch.tensor(x.copy())
                x = x[np.newaxis, :, :]
                hidden_state = tuple([h.data for h in model._hidden_state])
                y, model._hidden_state = model(x.float(), hidden_state)
                y = y.item()
                reference_data.loc[i, dependent_column] = y

            predicted_column = dependent_column.replace('norm', 'predicted')
            actual_column = dependent_column.replace('_norm', '')
            norm_min = normalization_minimum[-1]
            norm_max = normalization_maximum[-1]
            reference_data[predicted_column] = reference_data[dependent_column]*(norm_max - norm_min) + norm_min
            reference_data = reference_data[['timestep', 'reference', 'reference_name', actual_column, predicted_column]].copy()
            data_list.append(reference_data)

        return bldg_ix, pd.concat(data_list, ignore_index=True)

    def test_citylearn_simulation(
        self, schema: Path, model: Agent = None, env_kwargs: Mapping[str, Any] = None, model_kwargs: Mapping[str, Any] = None,
          report_lstm_performance: bool = None
    ) -> Tuple[pd.DataFrame, List[pd.DataFrame], List[pd.DataFrame]]:
        report_lstm_performance = True if report_lstm_performance is None else report_lstm_performance
        env_kwargs = {} if env_kwargs is None else env_kwargs
        model_kwargs = {} if model_kwargs is None else model_kwargs
        
        # test initialization
        env = CityLearnEnv(schema, **env_kwargs)
        model = NoControlAgent if model is None else model
        model = model(env=env, **model_kwargs)
        observations, _ = env.reset()
        
        # test stepping
        while not env.terminated:
            actions = model.predict(observations)
            observations, _, _, _, _ = env.step(actions)

        evaluation = env.evaluate()

        if report_lstm_performance:
            lstm_prediction_data: List[pd.DataFrame] = []
            lstm_error_data: List[pd.DataFrame] = []

            for b in env.buildings:
                lstm_prediction_data.append(pd.DataFrame({
                    'hour': b.energy_simulation.hour,
                    'month': b.energy_simulation.month,
                    'indoor_dry_bulb_temperature': b.energy_simulation.indoor_dry_bulb_temperature_without_control,
                    'indoor_dry_bulb_temperature_predicted': b.indoor_dry_bulb_temperature,
                }))
                
                rmse_data = lstm_prediction_data[-1].groupby(['month'])[['indoor_dry_bulb_temperature','indoor_dry_bulb_temperature_predicted']].apply(
                    lambda x: mean_squared_error(x['indoor_dry_bulb_temperature'], x['indoor_dry_bulb_temperature_predicted']
                )).reset_index(name='rmse')
                rmse_data['rmse'] = rmse_data['rmse']**0.5
                mape_data = lstm_prediction_data[-1].groupby(['month'])[['indoor_dry_bulb_temperature','indoor_dry_bulb_temperature_predicted']].apply(
                    lambda x: mean_absolute_percentage_error(x['indoor_dry_bulb_temperature'], x['indoor_dry_bulb_temperature_predicted']
                )).reset_index(name='mape')
                mape_data['mape'] = mape_data['mape']*100.0
                error_data = rmse_data.merge(mape_data, on=['month'])
                error_data.insert(0, 'bldg_name', b.name)
                lstm_error_data.append(error_data)
        
        else:
            lstm_prediction_data = None
            lstm_error_data = None


        return evaluation, lstm_prediction_data, lstm_error_data

    def set_schema(
        self, simulators: BuildingsSimulators, bldg_ids: List[int], lstm_models: List[Mapping[str, Any]] = None, 
        pricing: Union[List[Union[Path, pd.DataFrame, str]], Path, pd.DataFrame, str] = None, carbon_intensity: List[Union[Path, pd.DataFrame, str]] = None,
        template: Mapping[str, Union[dict, float, int, str]] = None, 
        metadata: pd.DataFrame = None, dataset_name: str = None, schema_directory: Union[Path, str] = None, weather_kwargs: dict = None,
        user_customization_function: Callable[[dict], dict] = None
    ) -> Path:
        assert pricing is None or not isinstance(pricing, list) or len(pricing) == len(bldg_ids), \
            'There must be as many pricing as bldg_ids.'
        assert carbon_intensity is None or not isinstance(carbon_intensity, list) or len(carbon_intensity) == len(bldg_ids), \
            'There must be as many carbon_intensity as bldg_ids.'
        template = get_settings()['schema']['template'] if template is None else template
        lstm_models = [None]*len(simulators) if lstm_models is None else lstm_models
        metadata = self.end_use_load_profiles.metadata.metadata.get().to_dict('index') if metadata is None else metadata
        schema_directory = self.dataset_directory if schema_directory is None else schema_directory
        county = metadata[list(metadata.keys())[0]][self.__COUNTY_COLUMN]
        county = county.lower().replace(',', '').replace(' ', '_')
        dataset_name = f'{self.end_use_load_profiles.version}-{county}' if dataset_name is None else dataset_name
        weather_kwargs = {} if weather_kwargs is None else weather_kwargs

        building_template = template.pop('buildings')['Building_1']
        template['buildings'] = {}
        schema_directory = os.path.join(schema_directory, dataset_name)
        os.makedirs(schema_directory, exist_ok=True)
        
        # write weather (csv and epw)
        reference_simulator = simulators[0]['partial'][0]
        weather_data = self.get_weather_data(reference_simulator, **weather_kwargs)
        weather_filename = building_template['weather'] if building_template['weather'] is not None else 'weather.csv'
        weather_data.to_csv(os.path.join(schema_directory, weather_filename), index=False)
        _ = shutil.copy(reference_simulator.epw_filepath, os.path.join(schema_directory, weather_filename.replace('.csv', '.epw')))

        for i, (bldg_id, building_simulators, lstm_model) in enumerate(zip(bldg_ids, simulators, lstm_models)):
            bldg_key = '-'.join(building_simulators['ideal'].simulation_id.split('-')[:-1])
            simulator: EndUseLoadProfilesEnergyPlusPartialLoadSimulator = building_simulators['partial'][0]
            ideal_simulator: EndUseLoadProfilesEnergyPlusSimulator = building_simulators['ideal']
            building = deepcopy(building_template)
            no_lstm_model = True if lstm_model is None else False

            # set building data
            building_data_query_filepath = os.path.join(simulator.QUERIES_DIRECTORY, 'select_citylearn_energy_simulation.sql')
            building_data = simulator.get_output_database().query_table_from_file(building_data_query_filepath)
            building_data_ideal = ideal_simulator.get_output_database().query_table_from_file(building_data_query_filepath)
            building_data['indoor_dry_bulb_temperature_cooling_set_point'] = building_data_ideal['indoor_dry_bulb_temperature_cooling_set_point'].tolist()
            building_data['indoor_dry_bulb_temperature_heating_set_point'] = building_data_ideal['indoor_dry_bulb_temperature_heating_set_point'].tolist()

            # set building-specific filepaths
            building['energy_simulation'] = f'{bldg_key}.csv'
            building['pricing'], building['carbon_intensity'] = self.__get_building_pricing_and_carbon_intensity(
                bldg_key,
                i,
                building_template,
                schema_directory,
                pricing,
                carbon_intensity)
            
            # as-modeled DER survey
            no_space_cooling = building_data['cooling_demand'].sum() == 0
            no_space_heating = building_data['heating_demand'].sum() == 0
            no_dhw_heating = building_data['dhw_demand'].sum() == 0
            no_electric_dhw_heating = metadata[bldg_id]['in.water_heater_fuel'] != 'Electricity'
            no_dhw_heating_storage = True if no_electric_dhw_heating else False

            if no_space_cooling:
                building['cooling_device'] = None
                building['inactive_observations'] += [o for o in template['observations'] if 'cooling' in o]

            else:
                pass

            if no_space_heating:
                building['heating_device'] = None
                building['inactive_observations'] += [o for o in template['observations'] if 'heating' in o]

            else:
                pass

            if no_dhw_heating:
                building['dhw_device'] = None
                building['dhw_storage'] = None
                building['inactive_observations'] += [o for o in template['observations'] if 'dhw' in o]
                building['inactive_actions'] += ['dhw_storage']

            elif no_dhw_heating_storage:
                building['dhw_storage'] = None
                building['inactive_observations'] += [o for o in template['observations'] if 'dhw_storage' in o]
                building['inactive_actions'] += ['dhw_storage']

            else:
                pass

            # PV autosize attributes
            osm = OpenStudioModelEditor(self.end_use_load_profiles.get_building(bldg_id).open_studio_model.get())
            building['pv']['autosize_attributes'] = {
                **building['pv']['autosize_attributes'],
                'roof_area': round(osm.get_roof_area(), 2),
            }

            # dynamics model
            if no_lstm_model:
                building['dynamics'] = None
                building['type'] = 'citylearn.building.Building'
            
            else:
                building['dynamics']['attributes']['filename'] = f'{bldg_key}.pth'
                building['dynamics']['attributes']['hidden_size'] = lstm_model['attributes']['hidden_size']
                building['dynamics']['attributes']['num_layers'] = lstm_model['attributes']['num_layers']
                building['dynamics']['attributes']['lookback'] = lstm_model['attributes']['lookback']
                building['dynamics']['attributes']['input_observation_names'] = lstm_model['attributes']['input_observation_names']
                building['dynamics']['attributes']['input_normalization_minimum'] = lstm_model['attributes']['input_normalization_minimum']
                building['dynamics']['attributes']['input_normalization_maximum'] = lstm_model['attributes']['input_normalization_maximum']
                torch.save(
                    lstm_model['model'].state_dict(), 
                    os.path.join(schema_directory, building['dynamics']['attributes']['filename'])
                )

            # set building schema
            template['buildings'][bldg_key] = building

            # write back data file
            building_data = building_data.astype('float32')

            for c in ['hour', 'month', 'daylight_savings_status', 'hvac_mode', 'day_type']:
                if c in building_data.columns:
                    building_data[c] = building_data[c].astype('int32')
                
                else:
                    pass

            building_data.to_csv(os.path.join(schema_directory, building['energy_simulation']), index=False)

        schema_filepath = os.path.join(schema_directory, f'schema.json')
        template = user_customization_function(template) if user_customization_function is not None else template
        FileHandler.write_json(schema_filepath, template)
        
        return schema_filepath
    
    def __get_building_pricing_and_carbon_intensity(
        self, bldg_key: str, bldg_ix: int, 
        building_template: Mapping[str, Union[dict, float, int, str]], schema_directory: Union[str, Path],
        pricing: Union[List[Union[Path, pd.DataFrame, str]], Path, pd.DataFrame, str] = None,
        carbon_intensity: Union[List[Union[Path, pd.DataFrame, str]], Path, pd.DataFrame, str] = None
    ) -> Tuple[str, str]:
        data = dict(
            pricing=dict(
                default_filename=building_template['pricing'] if building_template['pricing'] is not None else 'pricing.csv',
                data=pricing,
                schema_filename=None
            ),
            carbon_intensity=dict(
                default_filename=building_template['carbon_intensity'] if building_template['carbon_intensity'] is not None else 'carbon_intensity.csv',
                data=carbon_intensity,
                schema_filename=None
            )
        )

        for k, v in data.items():
            if v['data'] is None:
                if os.path.isfile(os.path.join(schema_directory, v['default_filename'])):
                    data[k]['schema_filename'] = v['default_filename']

                else:
                    pass

            elif isinstance(v['data'], (Path, str)):
                destination_filepath = os.path.join(schema_directory, v['default_filename'])
                shutil.copy(v['data'], destination_filepath)
                data[k]['schema_filename'] = v['default_filename']

            elif isinstance(v['data'], pd.DataFrame):
                destination_filepath = os.path.join(schema_directory, v['default_filename'])
                v['data'].to_csv(destination_filepath, index=False)
                data[k]['schema_filename'] = v['default_filename']

            elif isinstance(v['data'], list):
                destination_filename = f'{bldg_key}-pricing.csv'
                data[k]['schema_filename'] = destination_filename
                destination_filepath = os.path.join(schema_directory, destination_filename)
                
                if isinstance(v['data'][bldg_ix], (Path, str)):
                    shutil.copy(v['data'][bldg_ix], destination_filepath)

                elif isinstance(v['data'][bldg_ix], pd.DataFrame):
                    v['data'][bldg_ix].to_csv(destination_filepath, index=False)

            else:
                raise ValueError(f'Invalid {k} value type: {type(v["data"])}')

        return data['pricing']['schema_filename'], data['carbon_intensity']['schema_filename']

    def get_weather_data(self, simulator: EndUseLoadProfilesEnergyPlusPartialLoadSimulator, shifts: Tuple[int, int, int] = None, accuracy: Mapping[str, Tuple[float, float, float]] = None) -> pd.DataFrame:
        database = simulator.get_output_database()
        query_filepath = os.path.join(simulator.QUERIES_DIRECTORY, 'select_citylearn_weather.sql')
        data = database.query_table_from_file(query_filepath)
        columns = data.columns
        shifts = (6, 12, 24) if shifts is None else shifts
        accuracy = {c: (0.3, 0.65, 1.35) if c == 'outdoor_dry_bulb_temperature' else (0.025, 0.05, 0.1) for c in columns} \
            if accuracy is None else accuracy

        for c in columns:
            for i, (s, a) in enumerate(zip(shifts, accuracy[c])):
                arr = np.roll(data[c], shift=-s)
                nprs = np.random.RandomState(self.random_seed)
                shift_column = f'{c}_predicted_{int(i + 1)}'

                if c in ['outdoor_dry_bulb_temperature']:
                    data[shift_column] = arr + nprs.uniform(-a, a, len(arr))

                elif c in ['outdoor_relative_humidity', 'diffuse_solar_irradiance', 'direct_solar_irradiance']:
                    data[shift_column] = arr + arr*nprs.uniform(-a, a, len(arr))

                else:
                    raise Exception(f'Unknown field: {c}')
                
                if c != 'outdoor_dry_bulb_temperature':
                    data[shift_column] = data[shift_column].clip(lower=0.0)

                    if c == 'outdoor_relative_humidity':
                        data[shift_column] = data[shift_column].clip(upper=100.0)
                    
                    else:
                        pass

                else:
                    pass

        data = data.astype('float32')

        return data
    
    def train_lstm(self, data: List[pd.DataFrame], config: Mapping[str, Any] = None, seed: int = None) -> List[Mapping[str, Any]]:
        seed = self.random_seed if seed is None else seed
        config = get_settings()['lstm']['train']['config'] if config is None else config
        data = [run_one_model(config, d.copy(), seed) for d in data]

        return data
    
    def get_lstm_training_data(self, simulators: BuildingsSimulators) -> List[pd.DataFrame]:
        data = []

        for building_simulators in simulators:
            data_list = []

            for partial_simulator in building_simulators['partial']:
                partial_simulator: EndUseLoadProfilesEnergyPlusPartialLoadSimulator
                query_filepath = os.path.join(EndUseLoadProfilesEnergyPlusPartialLoadSimulator.QUERIES_DIRECTORY, 'select_lstm_training_data.sql')
                pdata = partial_simulator.get_output_database().query_table_from_file(query_filepath)
                pdata.insert(0, 'reference_name', partial_simulator.simulation_id.split('-')[-2])
                pdata.insert(0, 'reference', int(partial_simulator.simulation_id.split('-')[-1]))
                data_list.append(pdata)
            
            data.append(pd.concat(data_list, ignore_index=True))

        return data
    
    def simulate_energy_plus(
        self, bldg_ids: List[int], idd_filepath: Union[Path, str], simulation_ids: List[str] = None, models: List[Union[Path, str]] = None, 
        schedules: List[Union[Path, pd.DataFrame]] = None, thermostat_setpoints: List[Union[Path, pd.DataFrame]] = None, 
        fixed_ideal_loads_idf: List[Union[Path, str]] = None, osm: bool = None, partial_loads_simulations: int = None, simulate_mechanical: bool = None, 
        delete_existing_simulation: bool = None, partial_loads_kwargs: Mapping[str, Any] = None, **kwargs
    ) -> BuildingsSimulators:
        assert models is None or len(models) == len(bldg_ids), 'There must be as many models as bldg_ids.'
        assert schedules is None or len(schedules) == len(bldg_ids), 'There must be as many schedules as bldg_ids.'
        assert thermostat_setpoints is None or len(thermostat_setpoints) == len(bldg_ids), 'There must be as many thermostat_setpoints as bldg_ids.'
        assert fixed_ideal_loads_idf is None or len(fixed_ideal_loads_idf) == len(bldg_ids), 'There must be as many fixed_ideal_loads_idf as bldg_ids.'
        assert simulation_ids is None or len(simulation_ids) == len(bldg_ids), 'There must be as many simulation_ids as bldg_ids.'
        os.makedirs(self.energyplus_output_directory, exist_ok=True)
        partial_loads_simulations = 4 if partial_loads_simulations is None else partial_loads_simulations
        simulate_mechanical = True if simulate_mechanical is None else simulate_mechanical
        delete_existing_simulation = True if delete_existing_simulation is None else delete_existing_simulation
        partial_loads_kwargs = {} if partial_loads_kwargs is None else partial_loads_kwargs
        simulators = []

        kwargs = dict(
            idd_filepath=idd_filepath,
            osm=osm,
            **kwargs,
            number_of_time_steps_per_hour=1 if kwargs.get('number_of_time_steps_per_hour', None) is None else kwargs['number_of_time_steps_per_hour']
        )

        if (
            kwargs.get('default_output_variables', None) is None or not kwargs['default_output_variables']
        ) and kwargs.get('output_variables', None) is None:
            kwargs['default_output_variables'] = True

        else:
            pass

        if (
            kwargs.get('default_output_meters', None) is None or not kwargs['default_output_meters']
        ) and kwargs.get('output_meters', None) is None:
            kwargs['default_output_meters'] = True

        else:
            pass

        for i, bldg_id in enumerate(bldg_ids):
            bldg_id_ix = bldg_ids[:i].count(bldg_id)
            simulation_id = f'{self.end_use_load_profiles.version}-{bldg_id}-{bldg_id_ix}' if simulation_ids is None else simulation_ids[i]
            output_directory = os.path.join(self.energyplus_output_directory, simulation_id)

            if os.path.isdir(output_directory) and delete_existing_simulation:
                shutil.rmtree(output_directory)
            
            else:
                pass
            
            os.makedirs(output_directory)

            _kwargs = dict(
                **kwargs,
                bldg_id=bldg_id,
                model=models[i] if models is not None else models,
                schedules=schedules[i] if schedules is not None else schedules,
                thermostat_setpoint=thermostat_setpoints[i] if thermostat_setpoints is not None else thermostat_setpoints,
            )

            # mechanical loads
            if simulate_mechanical:
                _simulation_id = f'{simulation_id}-mechanical'
                _output_directory = os.path.join(output_directory, _simulation_id)
                mechanical_simulator = self.end_use_load_profiles.simulate_building(
                    ideal_loads=False,
                    simulation_id=_simulation_id,
                    output_directory=_output_directory,
                    **_kwargs
                ).simulator
            
            else:
                mechanical_simulator = None

            # ideal loads
            _ideal_kwargs = deepcopy(_kwargs)

            if fixed_ideal_loads_idf is not None:
                _ideal_kwargs['model'] = fixed_ideal_loads_idf[i]
                _ideal_kwargs['osm'] = False
            
            else:
                pass
            
            _simulation_id = f'{simulation_id}-ideal'
            _output_directory = os.path.join(output_directory, _simulation_id)
            ideal_simulator = self.end_use_load_profiles.simulate_building(
                ideal_loads=True,
                simulation_id=_simulation_id,
                output_directory=_output_directory,
                **_ideal_kwargs
            ).simulator

            # partial loads
            partial_loads_simulators: List[EndUseLoadProfilesEnergyPlusPartialLoadSimulator] = []
            kwargs_multiplier_minimum = partial_loads_kwargs.pop('multiplier_minimum', None)
            kwargs_multiplier_maximum = partial_loads_kwargs.pop('multiplier_maximum', None)
            kwargs_multiplier_probability = partial_loads_kwargs.pop('multiplier_probability', None)

            for i in range(partial_loads_simulations + 2):
                multiplier_minimum = kwargs_multiplier_minimum
                multiplier_maximum = kwargs_multiplier_maximum
                multiplier_probability = kwargs_multiplier_probability

                if i == 0:
                    reference_name = 'ideal'
                    multiplier_probability = 0
                
                elif i == 1:
                    reference_name = 'free_float'
                    multiplier_minimum = 0
                    multiplier_maximum = 0

                else:
                    reference_name = 'undercool_overcool_underheat_overheat'

                _simulation_id = f'{simulation_id}-partial-{reference_name}-{i}'
                _output_directory = os.path.join(output_directory, _simulation_id)
                _ = partial_loads_kwargs.pop('simulation_id', None)
                _ = partial_loads_kwargs.pop('output_directory', None)
                _ = partial_loads_kwargs.pop('random_seed', None)
                partial_loads_simulators.append(EndUseLoadProfilesEnergyPlusPartialLoadSimulator(
                    ideal_loads_simulator=deepcopy(ideal_simulator),
                    multiplier_minimum=multiplier_minimum,
                    multiplier_maximum=multiplier_maximum,
                    multiplier_probability=multiplier_probability,
                    simulation_id=_simulation_id,
                    output_directory=_output_directory,
                    random_seed=random_streams.partial_load_simulation_seed(
                        self.random_seed, bldg_id, i, self.random_stream_version
                    ),
                    **partial_loads_kwargs
                ))
            
            EndUseLoadProfilesEnergyPlusPartialLoadSimulator.multi_simulate(partial_loads_simulators, max_workers=self.max_workers)

            simulators.append({
                'mechanical': mechanical_simulator,
                'ideal': ideal_simulator,
                'partial': partial_loads_simulators
            })
        
        return simulators

    def sample_buildings(
        self, filters: Mapping[str, List[Any]] = None, sample_method: SampleMethod = None, sample_count: int = None, duplicate_to_count: bool = None, 
        single_county: bool = None, single_family_detached: bool = None, **kwargs
    ) -> Tuple[List[int], List[int], Mapping[str, Any]]:
        sample_method = SampleMethod.RANDOM if sample_method is None else sample_method
        valid_sample_method = [v for v in SampleMethod]
        assert sample_method in valid_sample_method, f'Valid sample methods are {valid_sample_method}.'
        sample_count = 100 if sample_count is None else sample_count
        duplicate_to_count = True if duplicate_to_count is None else duplicate_to_count
        single_county = True if single_county is None else single_county
        single_family_detached = True if single_family_detached is None else single_family_detached
        
        nprs = np.random.RandomState(self.random_seed)
        sample_metadata = None

        if single_family_detached:
            filters = {} if filters is None else filters
            filters[self.__BUILDING_TYPE_COLUMN] =  [self.__SINGLE_FAMILY_BUILDING_TYPE_NAME]
        
        else:
            pass
        
        metadata = self.end_use_load_profiles.metadata.metadata.get(filters)

        if single_county:
            county = nprs.choice(metadata[self.__COUNTY_COLUMN].unique(), 1)[0]
            metadata = metadata[metadata[self.__COUNTY_COLUMN]==county].copy()

        else:
            pass

        if sample_method == SampleMethod.RANDOM:
            metadata['label'] = 0

        elif sample_method == SampleMethod.METADATA_CLUSTER_FREQUENCY:
            mc = MetadataClustering(self.end_use_load_profiles, metadata.index.tolist(), random_seed=self.random_seed, **kwargs)
            optimal_clusters, scores, labels = mc.cluster()
            sample_metadata = {
                'optimal_clusters': optimal_clusters,
                'scores': scores,
                'labels': labels
            }

            metadata = metadata.merge(labels[labels['clusters']==optimal_clusters].set_index('bldg_id'), left_index=True, right_index=True)

        metadata['label_count'] = metadata.groupby('label')['label'].transform('count')
        metadata = metadata.sample(sample_count, weights='label_count', replace=duplicate_to_count, random_state=self.random_seed)
        bldg_ids = metadata.index.tolist()
        labels = metadata['label'].tolist()

        return bldg_ids, labels, sample_metadata