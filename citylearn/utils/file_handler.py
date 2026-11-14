import json
import math
import pickle
from pathlib import Path
from typing import Any
import numpy as np
import yaml


def _sanitize_json_value(value: Any, *, ignore_nan: bool) -> Any:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        scalar = float(value)
        if not math.isfinite(scalar):
            return None if ignore_nan else scalar
        return scalar
    if isinstance(value, np.ndarray):
        return _sanitize_json_value(value.tolist(), ignore_nan=ignore_nan)
    if isinstance(value, dict):
        return {k: _sanitize_json_value(v, ignore_nan=ignore_nan) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize_json_value(v, ignore_nan=ignore_nan) for v in value]
    return value


class FileHandler:
    @staticmethod
    def resolve_schema_root(schema: dict, schema_filepath: str) -> Path:
        """Resolve local data roots independently of the process directory.

        Prefer schema-relative roots. Older repository schemas include their
        full repository-relative directory; resolve those against an existing
        ancestor without changing the stored schema or consulting the cwd.
        """
        schema_dir = Path(schema_filepath).expanduser().resolve().parent
        configured = schema.get('root_directory')
        if configured is None:
            return schema_dir
        root = Path(configured).expanduser()
        if root.is_absolute():
            return root.resolve()
        candidate = (schema_dir / root).resolve()
        if candidate.is_dir():
            return candidate
        for ancestor in schema_dir.parents:
            legacy_candidate = (ancestor / root).resolve()
            if legacy_candidate.is_dir():
                return legacy_candidate
        return candidate

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
            Other infrequently used keyword arguments to be parsed to `json.load`.

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
            Other infrequently used keyword arguments to be parsed to `json.dump`.
        """

        kwargs = {'ignore_nan': True, 'sort_keys': False, 'default': str, 'indent': 2, **kwargs}
        ignore_nan = bool(kwargs.pop('ignore_nan', True))
        if ignore_nan:
            kwargs.setdefault('allow_nan', False)
        payload = _sanitize_json_value(dictionary, ignore_nan=ignore_nan)

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(payload, f, **kwargs)

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

        with open(filepath, 'r', encoding='utf-8') as f:
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

        with open(filepath, 'w', encoding='utf-8') as f:
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

