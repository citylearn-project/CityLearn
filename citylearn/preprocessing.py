from typing import Any, List, Union
import numpy as np

class Encoder:
    r"""Base class to transform observations.
    """
    
    def __init__(self):
        pass

    def __mul__(self, x: Any):
        raise NotImplementedError

    def __rmul__(self, x: Any):
        raise NotImplementedError

class NoNormalization(Encoder):
    r"""Use to return observation value as-is i.e. without any transformation.

    Examples
    --------
    >>> x_max = 24
    >>> encoder = NoNormalization()
    >>> observation = 2
    >>> encoder*observation
    2
    """
    
    def __init__(self):
        super().__init__()

    def __mul__(self, x: Union[float, int]):
        return x
        
    def __rmul__(self, x: Union[float, int]):
        return x
        
class PeriodicNormalization(Encoder):
    r"""Use to transform observations that are cyclical/periodic e.g. hour-of-day, day-of-week, e.t.c.

    Parameters
    ----------
    x_max : Union[float, int]
        Maximum observation value.

    Notes
    -----
    The transformation returns two values :math:`x_{sin}` and :math:`x_{sin}` defined as:
    
    .. math:: 
        x_{sin} = sin(\frac{2 \cdot \pi \cdot x}{x_{max}})
        
        x_{cos} = cos(\frac{2 \cdot \pi \cdot x}{x_{max}})

    Examples
    --------
    >>> x_max = 24
    >>> encoder = PeriodicNormalization(x_max)
    >>> observation = 2
    >>> encoder*observation
    array([0.75, 0.9330127])
    """
    
    def __init__(self, x_max: Union[float, int]):
        super().__init__()
        self.x_max = x_max

    def __mul__(self, x: Union[float, int]):
        x = 2 * np.pi * x / self.x_max
        x_sin = np.sin(x)
        x_cos = np.cos(x)
        return np.array([x_sin, x_cos])

    def __rmul__(self, x: Union[float, int]):
        x = 2 * np.pi * x / self.x_max
        x_sin = np.sin(x)
        x_cos = np.cos(x)
        return np.array([x_sin, x_cos])

class OnehotEncoding(Encoder):
    r"""Use to transform unordered categorical observations e.g. boolean daylight savings e.t.c.

    Parameters
    ----------
    classes : Union[List[float], List[int], List[str]]
        Observation categories.

    Examples
    --------
    >>> classes = [1, 2, 3, 4]
    >>> encoder = OnehotEncoding(classes)
    # identity_matrix = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
    >>> observation = 2
    >>> encoder*observation
    [0, 1, 0, 0]
    """

    def __init__(self, classes: Union[List[float], List[int], List[str]]):
        super().__init__()
        self.classes = classes

    def _encode(self, x: Union[float, int, str]):
        identity_mat = np.eye(len(self.classes))
        matches = identity_mat[np.array(self.classes) == x]
        if len(matches) == 0:
            return np.zeros(len(self.classes), dtype=identity_mat.dtype)
        return matches[0]

    def __mul__(self, x: Union[float, int, str]):
        return self._encode(x)

    def __rmul__(self, x: Union[float, int, str]):
        return self._encode(x)
    
class Normalize(Encoder):
    r"""Use to transform observations to a value between `x_min` and `x_max` using min-max normalization.

    Parameters
    ----------
    x_min : Union[float, int]
        Minimum observation value.
    x_max : Union[float, int]
        Maximum observation value.

    Notes
    -----
    The transformation returns two values :math:`x_{sin}` and :math:`x_{sin}` defined as:
    
    .. math:: 
        x = \frac{x - x_{min}}{x_{max} - x_{min}}

    Examples
    --------
    >>> x_min = 0
    >>> x_max = 24
    >>> encoder = Normalize(x_min, x_max)
    >>> observation = 2
    >>> encoder*observation
    0.08333333333333333
    """
    
    def __init__(self, x_min: Union[float, int], x_max: Union[float, int]):
        super().__init__()
        self.x_min = x_min
        self.x_max = x_max

    def __mul__(self, x: Union[float, int]):
        if self.x_min == self.x_max:
            return 0
        else:
            return (x - self.x_min)/(self.x_max - self.x_min)

    def __rmul__(self, x: Union[float, int]):
        if self.x_min == self.x_max:
            return 0
        else:
            return (x - self.x_min)/(self.x_max - self.x_min)
        
class RemoveFeature(Encoder):
    r"""Use to exlude an observation by returning `None` type.

    Examples
    --------
    >>> encoder = RemoveFeature()
    >>> observation = 2
    >>> encoder*observation
    None
    """
    
    def __init__(self):
        super().__init__()
        pass

    def __mul__(self, x: Any):
        return None

    def __rmul__(self, x: Any):
        return None