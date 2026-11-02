import pickle
from typing import Any, Iterable, Union
import numpy as np
import simplejson as json
import yaml


def parse_bool(value: Any, default: Any = None, path: str = 'value'):
    """Parse boolean-like values from schema/config sources.

    Accepted inputs:
    - bool
    - int/np.integer: 0 or 1
    - float/np.floating: 0.0 or 1.0
    - str (case-insensitive): true/false, 1/0, yes/no, on/off

    Parameters
    ----------
    value: Any
        Value to parse.
    default: Any, optional
        Fallback value if `value` is None.
    path: str, default: 'value'
        Config path used in validation error messages.
    """

    if value is None:
        if default is None:
            return None
        return parse_bool(default, default=None, path=path)

    if isinstance(value, (bool, np.bool_)):
        return bool(value)

    if isinstance(value, (int, np.integer)) and not isinstance(value, bool):
        if int(value) in (0, 1):
            return bool(int(value))
        raise ValueError(f"{path} must be one of: true/false, 1/0, yes/no, on/off.")

    if isinstance(value, (float, np.floating)):
        if float(value) in (0.0, 1.0):
            return bool(int(float(value)))
        raise ValueError(f"{path} must be one of: true/false, 1/0, yes/no, on/off.")

    if isinstance(value, str):
        token = value.strip().lower()
        if token in {'true', '1', 'yes', 'on'}:
            return True
        if token in {'false', '0', 'no', 'off'}:
            return False
        raise ValueError(f"{path} must be one of: true/false, 1/0, yes/no, on/off.")

    raise ValueError(f"{path} must be one of: true/false, 1/0, yes/no, on/off.")


class FileHandler:
    @staticmethod
    def read_json(filepath: str, **kwargs) -> dict:
        """Return JSON document as dictionary.
        
        Parameters
        ----------
        filepath : str
        pathname of JSON document.

        Other Parameters
        ----------------
        **kwargs : dict
            Other infrequently used keyword arguments to be parsed to `simplejson.load`.
        
        Returns
        -------
        dict
            JSON document converted to dictionary.
        """

        with open(filepath) as f:
            json_file = json.load(f, **kwargs)

        return json_file

    @staticmethod
    def write_json(filepath: str, dictionary: dict, **kwargs):
        """Write dictionary to JSON file.
        
        Parameters
        ----------
        filepath : str
            pathname of JSON document.
        dictionary: dict
            dictionary to convert to JSON.

        Other Parameters
        ----------------
        **kwargs : dict
            Other infrequently used keyword arguments to be parsed to `simplejson.dump`.
        """

        kwargs = {'ignore_nan': True, 'sort_keys': False, 'default': str, 'indent': 2, **kwargs}
        
        with open(filepath,'w') as f:
            json.dump(dictionary, f, **kwargs)

    @staticmethod
    def read_yaml(filepath: str) -> dict:
        """Return YAML document as dictionary.
        
        Parameters
        ----------
        filepath : str
        pathname of YAML document.
        
        Returns
        -------
        dict
            YAML document converted to dictionary.
        """

        with open(filepath, 'r') as f:
            data = yaml.safe_load(f)

        return data

    @staticmethod
    def write_yaml(filepath: str, dictionary: dict, **kwargs):
        """Write dictionary to YAML file. 
        
        Parameters
        ----------
        filepath : str
            pathname of YAML document.
        dictionary: dict
            dictionary to convert to YAML.

        Other Parameters
        ----------------
        **kwargs : dict
            Other infrequently used keyword arguments to be parsed to `yaml.safe_dump`.
        """

        kwargs = {'sort_keys': False, 'indent': 2, **kwargs}
        
        with open(filepath, 'w') as f:
            yaml.safe_dump(dictionary, f, **kwargs)

    @staticmethod
    def read_pickle(filepath: str, **kwargs) -> Any:
        """Return pickle file as some Python class object.
        
        Parameters
        ----------
        filepath : str
        pathname of pickle file.

        Other Parameters
        ----------------
        **kwargs : dict
            Other infrequently used keyword arguments to be parsed to `pickle.load`.
        
        Returns
        -------
        Any
            Pickle file as a Python object.
        """

        with (open(filepath, 'rb')) as f:
            data = pickle.load(f, **kwargs)

        return data

    @staticmethod
    def write_pickle(filepath: str, data: Any, **kwargs):
        """Write Python object to pickle file. 
        
        Parameters
        ----------
        filepath : str
            pathname of pickle document.
        data: dict
            object to convert to pickle.

        Other Parameters
        ----------------
        **kwargs : dict
            Other infrequently used keyword arguments to be parsed to `pickle.dump`.
        """

        with open(filepath, 'wb') as f:
            pickle.dump(data, f, **kwargs)

    @staticmethod
    def join_url(*args: str) -> str:
        url = '/'.join([a.strip('/') for a in args])

        return url
    
class IndexedNoise:
    """Owned per-channel streams indexed by the absolute source-row offset."""
    def __init__(self, seed, offset):
        self.seed, self.offset, self.channel = int(seed), int(offset), 0

    def normal(self, loc, scale, size):
        import hashlib
        key = f'{self.seed}:{self.channel}'.encode()
        self.channel += 1
        seed = int.from_bytes(hashlib.sha256(key).digest()[:4], 'big')
        count = int(np.prod(size))
        return np.random.RandomState(seed).normal(loc, scale, self.offset+count)[self.offset:].reshape(size)

class NoiseUtils:
    @staticmethod
    def generate_gaussian_noise(input_data: Union[np.ndarray, Iterable[float]], noise_std: float, random_state=None) -> np.ndarray:
        """Generates Gaussian noise matching input shape.
        
        Parameters
        ----------
        input_data : Union[np.ndarray, Iterable[float]]
            Time series to add noise to.
        noise_std : float
            Noise standard deviation (ignored if <= 0)
            
        Returns
        -------
            noise: np.ndarray
                Zero-mean noise array with same shape as input
        """

        arr = np.asarray(input_data)  # Handles both ndarray and Iterable
        if noise_std <= 0:
            return np.zeros(arr.shape, dtype=np.float32)
        return (np.random if random_state is None else random_state).normal(loc=0, scale=noise_std, size=arr.shape).astype(np.float32, copy=False)

    @staticmethod
    def generate_scaled_noise(input_data: Union[np.ndarray, Iterable[float]], noise_std: float, scale: float = 1.0) -> np.ndarray:
        """Generates pre-scaled noise (e.g., for percentage values)."""
        
        return NoiseUtils.generate_gaussian_noise(input_data, noise_std) * scale
