"""The end-use load profile pipeline runs CityLearn on the datasets it builds (#471).

These tests need the ``end_use_load_profiles`` extra and skip without it. The weekly workflow
``.github/workflows/end_use_load_profiles.yml`` installs the extra and fails when they skip.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

neighborhood = pytest.importorskip("citylearn.end_use_load_profiles.neighborhood")

# The pipeline writes LSTM dynamics buildings; this bundled dataset has the same building type.
DATASET = Path(__file__).resolve().parents[1] / "data" / "datasets" / "citylearn_challenge_2023_phase_1"


def test_neighborhood_runs_its_citylearn_simulation_on_a_small_lstm_dataset(monkeypatch):
    # Simulating a schema needs neither the ResStock metadata reader nor EnergyPlus.
    monkeypatch.setattr(neighborhood, "EndUseLoadProfiles", lambda **kwargs: None)
    schema = json.loads((DATASET / "schema.json").read_text(encoding="utf-8"))
    schema["root_directory"] = str(DATASET)
    schema["simulation_end_time_step"] = 47
    for index, building in enumerate(schema["buildings"].values()):
        building["include"] = index == 0

    evaluation, predictions, errors = neighborhood.Neighborhood(random_seed=0).test_citylearn_simulation(
        schema, env_kwargs={"central_agent": True}
    )

    assert isinstance(evaluation, pd.DataFrame) and not evaluation.empty
    assert len(predictions) == 1 and len(errors) == 1
    # 48 dataset rows give 47 simulated steps; the last row is only the terminal observation.
    assert len(predictions[0]) == 47
    assert not predictions[0].isna().any().any()
    assert np.isfinite(errors[0]["rmse"]).all()
