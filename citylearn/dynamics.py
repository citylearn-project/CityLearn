from __future__ import annotations

from pathlib import Path
from typing import List, Union
try:
    import torch
    import torch.nn
except ImportError:  # pragma: no cover - optional dependency for LSTM dynamics only
    torch = None


class _TorchNNPlaceholder:
    class Module:
        pass

class Dynamics:
    """Base building dynamics model."""

    def __init__(self):
        pass

    def reset(self):
        pass

class LSTMDynamics(Dynamics, (torch.nn if torch is not None else _TorchNNPlaceholder).Module):
    """LSTM building dynamics model that predicts indoor temperature based on partial cooling/heating load and other weather variables.
    
    Parameters
    ----------
    filepath: Union[Path, str]
        Path to model state dictionary.
    input_observation_names: List[str]
        List of maximum values used for input observation min-max normalization.
    input_normalization_minimum: List[float]
        List of minumum values used for input observation min-max normalization.
    input_normalization_maximum: List[float]
        List of maximum values used for input observation min-max normalization.
    hidden_size: int
        The number of neurons in hidden layer.
    num_layers: int
        Number of hidden layers.
    lookback: int
        Number of samples used for prediction.
    input_size: int, optional
        Number of variables used for prediction. This may not equal `input_observation_names`
        e.g. cooling and heating demand may be included in `input_observation_names` but only
        one of two may be used for the actual prediction depending on building needs.
        The default is to set set `input_size` to the length of `input_observation_names`.
    dropout: float, default: 0.0
        Probability of excluding input and recurrent connections to LSTM units from activation 
        and weight updates while training a network. This has the effect of reducing overfitting 
        and improving model performance.
    """

    def __init__(
            self, filepath: Union[Path, str], input_observation_names: List[str], input_normalization_minimum: List[float], 
            input_normalization_maximum: List[float], hidden_size: int, num_layers: int, lookback: int, input_size: int = None,
            dropout: float = None
    ):
        if torch is None:
            raise ImportError('torch is required to use LSTMDynamics.')

        Dynamics.__init__(self)
        torch.nn.Module.__init__(self)
        assert len(input_observation_names) == len(input_normalization_minimum) == len(input_normalization_maximum),\
            'input_observation_names, input_normalization_minimum and input_normalization_maximum must have the same length.'
        self.input_observation_names = input_observation_names
        self.input_normalization_minimum = input_normalization_minimum
        self.input_normalization_maximum = input_normalization_maximum
        self.input_size = input_size
        self.hidden_size = hidden_size
        self.num_layers = num_layers
        self.lookback = lookback
        self.filepath = filepath
        self.l_lstm = self.set_lstm()
        self.l_linear = self.set_linear()
        self._hidden_state = None
        self._model_input = None
        self.dropout = torch.nn.Dropout(dropout if dropout is not None else 0.0)

    @property
    def input_size(self) -> int:
        return self.__input_size
    
    @input_size.setter
    def input_size(self, value: int):
        self.__input_size = len(self.input_observation_names) if value is None else value
    
    def set_lstm(self) -> torch.nn.LSTM:
        """Initialize LSTM model."""

        return torch.nn.LSTM(
            input_size=self.input_size,
            hidden_size=self.hidden_size,
            num_layers=self.num_layers,
            batch_first=True,
        )

    def set_linear(self) -> torch.nn.Linear:
        """Initialize linear transformer."""

        return torch.nn.Linear(
            in_features=self.hidden_size,
            out_features=1
        )
    
    def forward(self, x, h):
        """Predict indoor dry bulb temperature."""

        lstm_out, h = self.l_lstm(x, h)
        lstm_out = self.dropout(lstm_out)
        out = lstm_out[:, -1, :]
        out_linear_transf = self.l_linear(out)
        return out_linear_transf, h

    def init_hidden(self, batch_size: int):
        """Initialize hidden states."""

        hidden_state = torch.zeros(self.num_layers, batch_size, self.hidden_size)
        cell_state = torch.zeros(self.num_layers, batch_size, self.hidden_size)
        hidden = (hidden_state, cell_state)
        
        return hidden

    def reset(self):
        """Loads dynamic model state dict, and initializes hidden states and model input."""

        super().reset()

        cached_path = getattr(self, '_cached_state_dict_filepath', None)
        state_dict = getattr(self, '_cached_state_dict', None)
        if state_dict is None or cached_path != self.filepath:
            checkpoint = torch.load(self.filepath, map_location=torch.device('cpu'))
            state_dict = (
                checkpoint['model_state_dict']
                if isinstance(checkpoint, dict) and 'model_state_dict' in checkpoint
                else checkpoint
            )
            self._cached_state_dict = state_dict
            self._cached_state_dict_filepath = self.filepath

        self.load_state_dict(state_dict)

        # Simulation is inference: without eval() the dropout layer stays active and every prediction
        # drops random units (unseeded), making the temperature dynamics noisy and non-reproducible.
        self.eval()
        self._hidden_state = self.init_hidden(1)
        self._model_input = [[None]*(self.lookback + 1) for _ in self.input_observation_names]

    def terminate(self):
        return
