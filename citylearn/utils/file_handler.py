import pickle
from pathlib import Path
from typing import Any
import numpy as np
import simplejson as json
import yaml


def json_default(value: Any) -> Any:
    """Return a JSON-serializable stand-in for `value`; the `default` of `FileHandler.write_json`.

    simplejson calls it only for objects it cannot write itself. NumPy booleans,
    integers and floats become the equal Python value, so they are written as JSON
    booleans and numbers (``np.float32(0.1)`` is written as ``0.10000000149011612``,
    its exact value). NumPy arrays of booleans and numbers become nested lists. With
    ``ignore_nan=True``, NaN and infinite values in them are written as ``null``.
    Anything else, including NumPy scalars without an equal Python value such as
    ``np.longdouble`` on some platforms, is written as ``str(value)``.
    """

    if isinstance(value, (np.bool_, np.integer, np.floating)):
        item = value.item()
        if not isinstance(item, np.generic):
            return item
    elif isinstance(value, np.ndarray) and value.dtype.kind in 'biuf':
        return value.tolist()

    return str(value)


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
            dictionary to convert to JSON. NumPy booleans, numbers and numeric arrays are
            written as JSON values (see `json_default`); with the default ``ignore_nan=True``,
            NaN and infinity are written as ``null``. namedtuples are written as objects and
            `Decimal` values as numbers.

        Other Parameters
        ----------------
        **kwargs : dict
            Other infrequently used keyword arguments to be parsed to `simplejson.dump`.
        """

        kwargs = {'ignore_nan': True, 'sort_keys': False, 'default': json_default, 'indent': 2, **kwargs}

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

