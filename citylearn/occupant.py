from pathlib import Path
from typing import List, Mapping, Tuple, Union
import numpy as np
from citylearn.base import Environment
from citylearn.data import LogisticRegressionOccupantParameters
from citylearn.internal.occupant_models import TreeClassifierModel, load_occupant_model
from citylearn.internal.scalars import numpy1_scalar

class Occupant(Environment):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)

    def predict(self) -> float:
        delta = 0.0

        return delta

class LogisticRegressionOccupant(Occupant):
    def __init__(
            self, setpoint_increase_model_filepath: Union[Path, str], setpoint_decrease_model_filepath: Union[Path, str], 
            delta_output_map: Mapping[int, float], parameters: LogisticRegressionOccupantParameters, **kwargs
        ):
        super().__init__(**kwargs)
        self.__setpoint_increase_model: TreeClassifierModel = None
        self.__setpoint_decrease_model: TreeClassifierModel = None
        self.__probabilities = None
        self.setpoint_increase_model_filepath = setpoint_increase_model_filepath
        self.setpoint_decrease_model_filepath = setpoint_decrease_model_filepath
        self.delta_output_map = delta_output_map
        self.parameters = parameters

    @property
    def probabilities(self) -> Mapping[str, float]:
        return self.__probabilities

    @property
    def setpoint_increase_model_filepath(self) -> Union[Path, str]:
        return self.__setpoint_increase_model_filepath
    
    @property
    def setpoint_decrease_model_filepath(self) -> Union[Path, str]:
        return self.__setpoint_decrease_model_filepath
    
    @property
    def delta_output_map(self) -> Mapping[int, float]:
        return self.__delta_output_map
    
    @setpoint_increase_model_filepath.setter
    def setpoint_increase_model_filepath(self, value: Union[Path, str]):
        self.__setpoint_increase_model_filepath = value
        self.__setpoint_increase_model = load_occupant_model(self.setpoint_increase_model_filepath)

    @setpoint_decrease_model_filepath.setter
    def setpoint_decrease_model_filepath(self, value: Union[Path, str]):
        self.__setpoint_decrease_model_filepath = value
        self.__setpoint_decrease_model = load_occupant_model(self.setpoint_decrease_model_filepath)

    @delta_output_map.setter
    def delta_output_map(self, value: Mapping[Union[str, int], float]):
        self.__delta_output_map = {int(k): v for k, v in value.items()}

    def predict(self, x: Tuple[float, List[List[float]]]) -> float:
        delta = super().predict()
        response = None
        interaction_input, delta_input = x
        # Python 1s as float64: with float32 parameters NumPy 1 evaluated this in float64.
        one = numpy1_scalar(1.0)
        interaction_probability = lambda  a, b, x_ : one/(one + np.exp(-(a + b*x_)))
        interaction_input = numpy1_scalar(interaction_input)  # float32 parameters x Python input: float64, as in NumPy 1
        increase_setpoint_probability = interaction_probability(numpy1_scalar(self.parameters.a_increase[self.time_step]), numpy1_scalar(self.parameters.b_increase[self.time_step]), interaction_input)
        decrease_setpoint_probability = interaction_probability(numpy1_scalar(self.parameters.a_decrease[self.time_step]), numpy1_scalar(self.parameters.b_decrease[self.time_step]), interaction_input)
        random_seed = max(self.random_seed, 1) + self.time_step
        nprs = np.random.RandomState(random_seed)
        random_probability = nprs.uniform()
        self.__probabilities['increase_setpoint'][self.time_step] = increase_setpoint_probability
        self.__probabilities['decrease_setpoint'][self.time_step] = decrease_setpoint_probability
        self.__probabilities['random'][self.time_step] = random_probability
        
        if increase_setpoint_probability < random_probability and decrease_setpoint_probability < random_probability:
            pass

        elif increase_setpoint_probability >= random_probability and decrease_setpoint_probability >= random_probability:
            total_prob = increase_setpoint_probability + decrease_setpoint_probability
            if total_prob <= 0.0 or nprs.uniform() < (increase_setpoint_probability / total_prob):
                response = self.__setpoint_increase_model.predict(delta_input)
                delta = self.delta_output_map[response[0]]
            else:
                response = self.__setpoint_decrease_model.predict(delta_input)
                delta = -self.delta_output_map[response[0]]

        elif increase_setpoint_probability >= random_probability:
            response = self.__setpoint_increase_model.predict(delta_input)
            delta = self.delta_output_map[response[0]]

        elif decrease_setpoint_probability >= random_probability:
            response = self.__setpoint_decrease_model.predict(delta_input)
            delta = -self.delta_output_map[response[0]]

        else:
            pass

        return delta
    
    def reset(self):
        super().reset()
        self.__probabilities = {
            'increase_setpoint': np.zeros(self.episode_tracker.episode_time_steps, dtype='float32'),
            'decrease_setpoint': np.zeros(self.episode_tracker.episode_time_steps, dtype='float32'),
            'random': np.zeros(self.episode_tracker.episode_time_steps, dtype='float32'),
        }