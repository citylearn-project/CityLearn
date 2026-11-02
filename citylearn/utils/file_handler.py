import pickle
from typing import Any
import simplejson as json
import yaml

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

        with open(filepath, encoding='utf-8-sig') as f:
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
    