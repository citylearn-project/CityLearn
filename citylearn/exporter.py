from __future__ import annotations

from collections import defaultdict
import csv
import datetime
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, TYPE_CHECKING, Union

import numpy as np

if TYPE_CHECKING:
    from citylearn.agents.base import Agent
    from citylearn.citylearn import CityLearnEnv
    from citylearn.electric_vehicle import ElectricVehicle

LOGGER = logging.getLogger(__name__)


class EpisodeExporter:
    """Internal helper that owns rendering/export behaviour for ``CityLearnEnv``."""

    DEFAULT_RENDER_START_DATE = datetime.date(2024, 1, 1)

    def __init__(self, env: "CityLearnEnv"):
        self.env = env
        self._chunk_counters = defaultdict(int)

    def _render_file_format(self) -> str:
        value = str(getattr(self.env, 'render_file_format', 'csv') or 'csv').strip().lower()
        return value if value in {'csv', 'parquet'} else 'csv'

    def _render_chunk_size(self) -> int:
        try:
            return max(int(getattr(self.env, 'render_chunk_size', 100_000)), 1)
        except (TypeError, ValueError):
            return 100_000

    def _export_filename(self, filename: str) -> str:
        if self._render_file_format() != 'parquet':
            return filename

        path = Path(filename)
        if path.suffix.lower() == '.parquet':
            return str(path)

        return str(path.with_suffix('.parquet'))

    def _buildings_for_time_step(self, time_step: int, env: "CityLearnEnv" = None):
        env = self.env if env is None else env
        if getattr(env, 'topology_mode', 'static') != 'dynamic':
            return list(env.buildings)

        topology_service = getattr(env, '_topology_service', None)
        if topology_service is None:
            return list(env.buildings)

        active_ids = topology_service.active_member_ids_at(time_step)
        return [
            topology_service.member_pool[member_id]
            for member_id in active_ids
            if member_id in topology_service.member_pool
        ]

    def _electric_vehicles_for_time_step(self, time_step: int, env: "CityLearnEnv" = None):
        env = self.env if env is None else env
        if getattr(env, 'topology_mode', 'static') != 'dynamic':
            return list(env.electric_vehicles)

        topology_service = getattr(env, '_topology_service', None)
        if topology_service is None:
            return list(env.electric_vehicles)

        active_ids = topology_service.active_ev_ids_at(time_step)
        return [
            topology_service.ev_pool[ev_id]
            for ev_id in active_ids
            if ev_id in topology_service.ev_pool
        ]

    def _chargers_for_time_step(self, building, time_step: int, env: "CityLearnEnv" = None):
        env = self.env if env is None else env
        if getattr(env, 'topology_mode', 'static') != 'dynamic':
            return list(building.electric_vehicle_chargers or [])

        topology_service = getattr(env, '_topology_service', None)
        if topology_service is None:
            return list(building.electric_vehicle_chargers or [])

        charger_map = topology_service.active_chargers_at(time_step, building.name)
        return list(charger_map.values())

    def _electrical_storage_for_time_step(self, building, time_step: int, env: "CityLearnEnv" = None):
        env = self.env if env is None else env
        if getattr(env, 'topology_mode', 'static') != 'dynamic':
            return building.electrical_storage

        topology_service = getattr(env, '_topology_service', None)
        if topology_service is None:
            return building.electrical_storage

        return topology_service.active_storage_at(time_step, building.name)

    def _deferrable_appliances_for_time_step(self, building, time_step: int, env: "CityLearnEnv" = None):
        env = self.env if env is None else env
        if getattr(env, 'topology_mode', 'static') != 'dynamic':
            return list(building.deferrable_appliances or [])

        topology_service = getattr(env, '_topology_service', None)
        if topology_service is None or not hasattr(topology_service, 'active_deferrable_appliances_at'):
            return list(building.deferrable_appliances or [])

        appliance_map = topology_service.active_deferrable_appliances_at(time_step, building.name)
        return list(appliance_map.values())

    @staticmethod
    def parse_render_start_date(start_date: Union[str, datetime.date, datetime.datetime]) -> datetime.date:
        """Return a valid start date for rendering timestamps."""

        if start_date is None:
            return EpisodeExporter.DEFAULT_RENDER_START_DATE

        if isinstance(start_date, datetime.datetime):
            return start_date.date()

        if isinstance(start_date, datetime.date):
            return start_date

        if isinstance(start_date, str):
            try:
                return datetime.date.fromisoformat(start_date)
            except ValueError as exc:
                raise ValueError(
                    "CityLearnEnv start_date must be in ISO format 'YYYY-MM-DD'."
                ) from exc

        raise TypeError(
            "CityLearnEnv start_date must be a date, datetime, or ISO format string."
        )

    def export_final_kpis(
        self,
        model: "Agent" = None,
        filepath: str = "exported_kpis.csv",
        include_business_as_usual: bool = True,
        export_business_as_usual_timeseries: bool = True,
        kpi_round_decimals: Optional[int] = None,
    ):
        """Export episode KPIs to csv."""

        env = self.env
        self.ensure_output_dir()
        filepath = self._export_filename(filepath)
        file_path = os.path.join(env.new_folder_path, filepath)

        if model is not None and getattr(model, 'env', None) is not None:
            kpis = model.env.evaluate_v2(include_business_as_usual=include_business_as_usual)
            export_env = model.env.unwrapped
            identity = getattr(model, 'comparison_identity', None)
            if callable(identity):
                export_env.set_experiment_identity(**identity())
        else:
            kpis = env.evaluate_v2(include_business_as_usual=include_business_as_usual)
            export_env = env

        kpis = kpis.pivot(index='cost_function', columns='name', values='value')
        if kpi_round_decimals is not None:
            kpis = kpis.round(kpi_round_decimals)
        kpis = kpis.reset_index()
        kpis = kpis.rename(columns={'cost_function': 'KPI'})
        if self._render_file_format() == 'parquet':
            kpis.to_parquet(file_path, index=False)
        else:
            kpis.fillna('').to_csv(file_path, index=False, encoding='utf-8')
        if include_business_as_usual and export_business_as_usual_timeseries:
            self.export_business_as_usual_timeseries(export_env)
        from citylearn.internal.experiment import experiment_manifest
        from citylearn.utils.file_handler import FileHandler
        FileHandler.write_json(str(Path(file_path).with_suffix('.manifest.json')), experiment_manifest(export_env))
        FileHandler.write_json(str(Path(file_path).with_suffix('.deferrable_service.json')),
                               export_env.get_deferrable_service_audit())
        if export_env._robustness_service.enabled:
            FileHandler.write_json(str(Path(file_path).with_suffix('.robustness.json')),
                                   export_env.get_robustness_audit())
        env._final_kpis_exported = True

    def export_business_as_usual_timeseries(self, source_env: "CityLearnEnv" = None):
        """Export a compact time-series audit for the business-as-usual baseline."""

        env = self.env
        source_env = env if source_env is None else source_env
        result = source_env.run_business_as_usual_baseline()
        baseline_env = result.env
        episode_num = source_env.episode_tracker.episode
        final_index = int(result.time_step)
        filename = self._export_filename(f"exported_data_business_as_usual_ep{episode_num}.csv")
        file_path = Path(env.new_folder_path) / filename
        if file_path.exists():
            file_path.unlink()
        if self._render_file_format() == 'parquet':
            for part in file_path.parent.glob(f"{file_path.stem}_part*.parquet"):
                part.unlink()
            self._chunk_counters[str(file_path)] = 0
        file_path.parent.mkdir(parents=True, exist_ok=True)

        fieldnames = [
            'time_step',
            'name',
            'level',
            'net_electricity_consumption_kwh',
            'net_electricity_consumption_cost',
            'net_electricity_consumption_emission_kgco2',
            'solar_generation_kwh',
            'bess_electricity_consumption_kwh',
            'bess_soc',
            'ev_charger_electricity_consumption_kwh',
            'deferrable_appliance_electricity_consumption_kwh',
        ]

        if self._render_file_format() == 'parquet':
            rows = []
            chunk_size = self._render_chunk_size()
            for t in range(final_index + 1):
                building_rows = []
                for building in self._buildings_for_time_step(t, baseline_env):
                    row = self._business_as_usual_building_row(building, t, baseline_env)
                    building_rows.append(row)
                    rows.append(row)
                    if len(rows) >= chunk_size:
                        self.write_render_rows(filename, rows)
                        rows.clear()

                rows.append(self._business_as_usual_district_row(baseline_env, t, building_rows))
                if len(rows) >= chunk_size:
                    self.write_render_rows(filename, rows)
                    rows.clear()

            self.write_render_rows(filename, rows)
            return

        with file_path.open('w', encoding='utf-8', newline='') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()

            for t in range(final_index + 1):
                building_rows = []
                for building in self._buildings_for_time_step(t, baseline_env):
                    row = self._business_as_usual_building_row(building, t, baseline_env)
                    building_rows.append(row)
                    writer.writerow({field: row.get(field, '') for field in fieldnames})

                row = self._business_as_usual_district_row(baseline_env, t, building_rows)
                writer.writerow({field: row.get(field, '') for field in fieldnames})

    def _business_as_usual_building_row(self, building, time_step: int, baseline_env: "CityLearnEnv" = None) -> Dict[str, Any]:
        battery = self._electrical_storage_for_time_step(building, time_step, baseline_env)
        chargers = self._chargers_for_time_step(building, time_step, baseline_env)
        appliances = self._deferrable_appliances_for_time_step(building, time_step, baseline_env)
        return {
            'time_step': time_step,
            'name': building.name,
            'level': 'building',
            'net_electricity_consumption_kwh': self._series_value(building.net_electricity_consumption, time_step),
            'net_electricity_consumption_cost': self._series_value(building.net_electricity_consumption_cost, time_step),
            'net_electricity_consumption_emission_kgco2': self._series_value(building.net_electricity_consumption_emission, time_step),
            'solar_generation_kwh': self._series_value(building.solar_generation, time_step),
            'bess_electricity_consumption_kwh': self._numeric_series_value(
                getattr(battery, 'electricity_consumption', []),
                time_step,
            ),
            'bess_soc': self._series_value(getattr(battery, 'soc', []), time_step),
            'ev_charger_electricity_consumption_kwh': sum(
                self._numeric_series_value(getattr(charger, 'electricity_consumption', []), time_step)
                for charger in chargers
            ),
            'deferrable_appliance_electricity_consumption_kwh': sum(
                self._numeric_series_value(getattr(appliance, 'electricity_consumption', []), time_step)
                for appliance in appliances
            ),
        }

    def _business_as_usual_district_row(
        self,
        baseline_env: "CityLearnEnv",
        time_step: int,
        rows: Optional[List[Mapping[str, Any]]] = None,
    ) -> Dict[str, Any]:
        if rows is None:
            rows = [
                self._business_as_usual_building_row(building, time_step, baseline_env)
                for building in self._buildings_for_time_step(time_step, baseline_env)
            ]

        return {
            'time_step': time_step,
            'name': 'District',
            'level': 'district',
            'net_electricity_consumption_kwh': self._series_value(baseline_env.net_electricity_consumption, time_step),
            'net_electricity_consumption_cost': self._series_value(baseline_env.net_electricity_consumption_cost, time_step),
            'net_electricity_consumption_emission_kgco2': self._series_value(baseline_env.net_electricity_consumption_emission, time_step),
            'solar_generation_kwh': sum(row['solar_generation_kwh'] for row in rows),
            'bess_electricity_consumption_kwh': sum(row['bess_electricity_consumption_kwh'] for row in rows),
            'bess_soc': '',
            'ev_charger_electricity_consumption_kwh': sum(row['ev_charger_electricity_consumption_kwh'] for row in rows),
            'deferrable_appliance_electricity_consumption_kwh': sum(row['deferrable_appliance_electricity_consumption_kwh'] for row in rows),
        }

    @staticmethod
    def _series_value(values, index: int):
        try:
            return float(values[min(max(int(index), 0), len(values) - 1)])
        except Exception:
            return ''

    @classmethod
    def _numeric_series_value(cls, values, index: int) -> float:
        value = cls._series_value(values, index)
        try:
            return float(value)
        except Exception:
            return 0.0

    def render(self):
        """Render one time step to configured time-series outputs."""

        env = self.env

        if not getattr(env, 'render_enabled', False):
            return

        if not env._should_export_current_episode():
            return

        if env.render_mode == 'end' and getattr(env, '_defer_render_flush', False):
            return

        if env.render_mode == 'end' and (env.terminated or env.truncated):
            return

        self.ensure_output_dir()
        iso_timestamp = self.get_iso_timestamp()
        os.makedirs(env.new_folder_path, exist_ok=True)

        episode_num = env.episode_tracker.episode

        self.save_to_csv(
            self._export_filename(f"exported_data_community_ep{episode_num}.csv"),
            {"timestamp": iso_timestamp, **env.as_dict()},
        )

        buildings = self._buildings_for_time_step(env.time_step)

        for building in buildings:
            self.save_to_csv(
                self._export_filename(f"exported_data_{building.name.lower()}_ep{episode_num}.csv"),
                {"timestamp": iso_timestamp, **building.as_dict()},
            )

            battery = self._electrical_storage_for_time_step(building, env.time_step)
            if battery is not None:
                battery.time_step = env.time_step
                self.save_to_csv(
                    self._export_filename(f"exported_data_{building.name.lower()}_battery_ep{episode_num}.csv"),
                    {"timestamp": iso_timestamp, **battery.as_dict()},
                )

            for charger in self._chargers_for_time_step(building, env.time_step):
                charger.time_step = env.time_step
                self.save_to_csv(
                    self._export_filename(f"exported_data_{building.name.lower()}_{charger.charger_id}_ep{episode_num}.csv"),
                    {"timestamp": iso_timestamp, **charger.as_dict()},
                )

        if len(buildings) > 0:
            self.save_to_csv(
                self._export_filename(f"exported_data_pricing_ep{episode_num}.csv"),
                {"timestamp": iso_timestamp, **buildings[0].pricing.as_dict(env.time_step)},
            )

        for ev in self._electric_vehicles_for_time_step(env.time_step):
            self.save_to_csv(
                self._export_filename(f"exported_data_{ev.name.lower()}_ep{episode_num}.csv"),
                {"timestamp": iso_timestamp, **ev.as_dict()},
            )

    def _set_charger_render_state(self, charger, time_step: int, ev_lookup: Mapping[str, "ElectricVehicle"]):
        """Restore the actual connection and the scheduled incoming vehicle for a render row."""

        sim = charger.charger_simulation
        state = sim.electric_vehicle_charger_state[time_step] if time_step < len(sim.electric_vehicle_charger_state) else np.nan
        ev_id = sim.electric_vehicle_id[time_step] if time_step < len(sim.electric_vehicle_id) else None
        valid_ev_id = isinstance(ev_id, str) and ev_id.strip() not in {"", "nan"}

        connected_ev = charger.past_connected_evs[time_step] if time_step < len(charger.past_connected_evs) else None
        incoming_ev = ev_lookup.get(ev_id) if valid_ev_id and state == 2 else None

        charger.connected_electric_vehicle = connected_ev
        charger.incoming_electric_vehicle = incoming_ev

    def export_episode_render_data(self, final_index: int):
        """Export full episode render rows in one pass for ``render_mode='end'``."""

        env = self.env

        if final_index < 0:
            return

        if not env._should_export_current_episode():
            return

        self.ensure_output_dir()
        episode_num = env.episode_tracker.episode
        rows_by_filename: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
        chunk_size = self._render_chunk_size()
        prepared_files = set()

        def append_row(filename: str, row: Mapping[str, Any]):
            filename = self._export_filename(filename)
            if filename not in prepared_files:
                file_path = Path(env.new_folder_path) / filename
                if file_path.exists():
                    file_path.unlink()
                if self._render_file_format() == 'parquet':
                    for part in file_path.parent.glob(f"{file_path.stem}_part*.parquet"):
                        part.unlink()
                    self._chunk_counters[str(file_path)] = 0
                prepared_files.add(filename)
            rows = rows_by_filename[filename]
            rows.append(row)
            if len(rows) >= chunk_size:
                self.write_render_rows(filename, rows)
                rows.clear()

        if getattr(env, 'topology_mode', 'static') == 'dynamic' and getattr(env, '_topology_service', None) is not None:
            ev_lookup = dict(env._topology_service.ev_pool)
        else:
            ev_lookup = {ev.name: ev for ev in env.electric_vehicles}
        original_charger_state = {}
        original_active_buildings = list(env.buildings)
        original_active_evs = list(env.electric_vehicles)
        time_step_snapshot = self.override_render_time_step(0)
        original_year = env.year
        original_day = env.current_day
        original_start_datetime = getattr(env, '_render_start_datetime', None)

        try:
            self.reset_time_tracking()

            for t in range(final_index + 1):
                buildings = self._buildings_for_time_step(t)
                evs = self._electric_vehicles_for_time_step(t)
                if getattr(env, 'topology_mode', 'static') == 'dynamic':
                    env.buildings = buildings
                    env.electric_vehicles = evs

                for obj, _ in time_step_snapshot:
                    try:
                        obj.time_step = t
                    except AttributeError:
                        pass

                timestamp = self.get_iso_timestamp()
                append_row(
                    f"exported_data_community_ep{episode_num}.csv",
                    {"timestamp": timestamp, **env.as_dict()}
                )

                for building in buildings:
                    append_row(
                        f"exported_data_{building.name.lower()}_ep{episode_num}.csv",
                        {"timestamp": timestamp, **building.as_dict()}
                    )
                    battery = self._electrical_storage_for_time_step(building, t)
                    if battery is not None:
                        battery.time_step = t
                        append_row(
                            f"exported_data_{building.name.lower()}_battery_ep{episode_num}.csv",
                            {"timestamp": timestamp, **battery.as_dict()}
                        )

                    for charger in self._chargers_for_time_step(building, t):
                        charger.time_step = t
                        if charger not in original_charger_state:
                            original_charger_state[charger] = (
                                charger.connected_electric_vehicle,
                                charger.incoming_electric_vehicle,
                            )
                        self._set_charger_render_state(charger, t, ev_lookup)
                        append_row(
                            f"exported_data_{building.name.lower()}_{charger.charger_id}_ep{episode_num}.csv",
                            {"timestamp": timestamp, **charger.as_dict()}
                        )

                if len(buildings) > 0:
                    append_row(
                        f"exported_data_pricing_ep{episode_num}.csv",
                        {"timestamp": timestamp, **buildings[0].pricing.as_dict(t)}
                    )

                for ev in evs:
                    append_row(
                        f"exported_data_{ev.name.lower()}_ep{episode_num}.csv",
                        {"timestamp": timestamp, **ev.as_dict()}
                    )

        finally:
            for charger, state in original_charger_state.items():
                charger.connected_electric_vehicle, charger.incoming_electric_vehicle = state

            self.restore_render_time_step(time_step_snapshot)
            env.buildings = original_active_buildings
            env.electric_vehicles = original_active_evs
            env.year = original_year
            env.current_day = original_day
            env._render_start_datetime = original_start_datetime

        for filename, rows in rows_by_filename.items():
            self.write_render_rows(filename, rows)

    def save_to_csv(self, filename: str, data: Mapping[str, Any]):
        """Save one render row to configured output format."""

        env = self.env
        filename = self._export_filename(filename)

        if self._render_file_format() == 'parquet':
            env._render_buffer[filename].append(dict(data))
            if len(env._render_buffer[filename]) >= self._render_chunk_size():
                self.write_render_rows(filename, env._render_buffer[filename])
                env._render_buffer[filename].clear()
            return

        if env._buffer_render and getattr(env, '_defer_render_flush', False):
            env._render_buffer[filename].append(dict(data))
            return

        self.write_render_rows(filename, [dict(data)])

    def flush_render_buffer(self):
        """Write any buffered render rows to disk."""

        env = self.env

        if not getattr(env, '_render_buffer', None):
            return

        if not env._should_export_current_episode():
            env._render_buffer.clear()
            return

        has_pending_rows = any(env._render_buffer.values())
        if not has_pending_rows:
            env._render_buffer.clear()
            return

        try:
            target_dir = Path(env.new_folder_path)
        except Exception:
            target_dir = None

        if target_dir is not None:
            LOGGER.info("Writing buffered render exports to %s ...", target_dir)

        original_defer = env._defer_render_flush
        original_buffer_state = env._buffer_render
        env._defer_render_flush = False
        env._buffer_render = False

        try:
            for filename, rows in list(env._render_buffer.items()):
                if rows:
                    self.write_render_rows(filename, rows)
        finally:
            env._render_buffer.clear()
            env._buffer_render = original_buffer_state
            env._defer_render_flush = original_defer

    def write_render_rows(self, filename: str, rows: List[Mapping[str, Any]]):
        """Write one or more render rows to disk with minimal rewrites."""

        env = self.env
        file_path = Path(env.new_folder_path) / filename
        file_path.parent.mkdir(parents=True, exist_ok=True)

        if not rows:
            return

        buffered_fieldnames = list(dict.fromkeys(field for row in rows for field in row.keys()))

        if self._render_file_format() == 'parquet':
            self._write_parquet_rows(filename, rows)
            return

        if not file_path.exists():
            fieldnames = buffered_fieldnames
            with file_path.open('w', encoding='utf-8', newline='') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                for row in rows:
                    writer.writerow({field: row.get(field, '') for field in fieldnames})
            return

        with file_path.open('r', encoding='utf-8', newline='') as csvfile:
            reader = csv.DictReader(csvfile)
            existing_fieldnames = reader.fieldnames or []

        missing_fieldnames = [field for field in buffered_fieldnames if field not in existing_fieldnames]
        if missing_fieldnames:
            with file_path.open('r', encoding='utf-8', newline='') as csvfile:
                reader = csv.DictReader(csvfile)
                existing_rows = list(reader)
            extended_fieldnames = [*existing_fieldnames, *missing_fieldnames]
            with file_path.open('w', encoding='utf-8', newline='') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=extended_fieldnames)
                writer.writeheader()
                for row in existing_rows:
                    writer.writerow({field: row.get(field, '') for field in extended_fieldnames})
                for row in rows:
                    writer.writerow({field: row.get(field, '') for field in extended_fieldnames})
            return

        with file_path.open('a', encoding='utf-8', newline='') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=existing_fieldnames)
            for row in rows:
                writer.writerow({field: row.get(field, '') for field in existing_fieldnames})

    def _write_parquet_rows(self, filename: str, rows: List[Mapping[str, Any]]):
        env = self.env
        file_path = Path(env.new_folder_path) / filename
        file_path.parent.mkdir(parents=True, exist_ok=True)
        counter_key = str(file_path)
        counter = self._chunk_counters[counter_key]
        self._chunk_counters[counter_key] = counter + 1
        part_path = file_path.with_name(f"{file_path.stem}_part{counter:05d}{file_path.suffix}")

        try:
            import pandas as pd
        except ImportError as exc:
            raise ImportError(
                "Parquet render exports require pandas with a parquet engine such as pyarrow."
            ) from exc

        dataframe = pd.DataFrame(rows)
        dataframe = dataframe.where(dataframe.ne(''), np.nan)
        # Render dictionaries historically mix numeric strings used by the CSV
        # path with NumPy scalars used while an asset is active.  PyArrow cannot
        # infer a stable type for such object columns (for example charger state
        # is ``"-1.00"`` while idle and ``np.float32(1)`` while occupied).
        # Promote wholly numeric-like object/string columns to numbers before writing;
        # keep genuinely textual columns textual and normalize NumPy/mixed scalars.
        for column in dataframe.select_dtypes(include=['object', 'string']).columns:
            series = dataframe[column]
            non_null = series.dropna()
            if non_null.empty:
                continue

            numeric = pd.to_numeric(non_null, errors='coerce')
            if numeric.notna().all():
                dataframe[column] = pd.to_numeric(series, errors='coerce')
                continue

            has_string = any(isinstance(v, str) for v in non_null)
            dataframe[column] = series.map(
                lambda value, _to_str=has_string: (
                    value
                    if pd.isna(value)
                    else (
                        str(value.item() if isinstance(value, np.generic) else value)
                        if _to_str
                        else (value.item() if isinstance(value, np.generic) else value)
                    )
                )
            )
        dataframe.to_parquet(part_path, index=False)

    def ensure_output_dir(self, *, ensure_exists: bool = True):
        """Prepare the render output directory and optionally create it on disk."""

        env = self.env
        base_render_path = Path(
            getattr(env, 'render_output_root', Path(__file__).resolve().parents[1] / 'render_logs')
        ).expanduser()

        if ensure_exists:
            try:
                base_render_path.mkdir(parents=True, exist_ok=True)
            except PermissionError:
                fallback = (Path.cwd() / 'render_logs').resolve()
                fallback.mkdir(parents=True, exist_ok=True)
                env.render_output_root = fallback
                base_render_path = fallback

        render_dir = getattr(env, '_render_directory_path', None)
        needs_new_dir = render_dir is None

        if not needs_new_dir and ensure_exists:
            render_dir = Path(render_dir)
            try:
                needs_new_dir = not render_dir.is_relative_to(base_render_path)
            except AttributeError:
                needs_new_dir = base_render_path not in render_dir.parents and render_dir != base_render_path

        if needs_new_dir:
            if env.render_session_name:
                render_dir = (base_render_path / Path(env.render_session_name)).expanduser().resolve()
            else:
                if getattr(env, '_render_timestamp', None) is None:
                    env._render_timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                render_dir = (base_render_path / env._render_timestamp).resolve()

            env._render_directory_path = render_dir
        else:
            render_dir = Path(env._render_directory_path)

        if ensure_exists:
            render_dir.mkdir(parents=True, exist_ok=True)
            if not env._render_dir_initialized:
                if env.render_session_name:
                    for csv_file in render_dir.glob('exported_*.csv'):
                        try:
                            csv_file.unlink()
                        except OSError:
                            pass
                    for parquet_file in render_dir.glob('exported_*.parquet'):
                        try:
                            parquet_file.unlink()
                        except OSError:
                            pass
                env._render_dir_initialized = True

        env.new_folder_path = str(render_dir)

    def get_iso_timestamp(self) -> str:
        """Return current episode timestamp string in ISO format."""

        env = self.env

        if env.time_step == 0 or getattr(env, '_render_start_datetime', None) is None:
            self.reset_time_tracking()

        axis = getattr(env, '_time_axis', None)
        if axis is not None and axis.utc is not None and not getattr(env, '_render_origin_overridden', False):
            timestamp = axis.at(env.episode_tracker.episode_start_time_step+env.time_step)
            env.year, env.current_day = timestamp.year, timestamp.day
            return timestamp.isoformat()

        start_datetime = env._render_start_datetime
        timestamp_dt = start_datetime + datetime.timedelta(seconds=env.time_step * env.seconds_per_time_step)
        env.year = timestamp_dt.year
        env.current_day = timestamp_dt.day

        return timestamp_dt.strftime("%Y-%m-%dT%H:%M:%S")

    def override_render_time_step(self, index: int):
        """Temporarily set time_step to `index` for the environment and descendants."""

        env = self.env
        snapshot = []
        seen = set()

        def _record(obj):
            if obj is None:
                return
            marker = id(obj)
            if marker in seen:
                return
            seen.add(marker)
            if hasattr(obj, 'time_step'):
                snapshot.append((obj, obj.time_step))
                obj.time_step = index

        _record(env)
        if getattr(env, 'topology_mode', 'static') == 'dynamic' and getattr(env, '_topology_service', None) is not None:
            buildings_iterable = list(env._topology_service.member_pool.values())
            ev_iterable = list(env._topology_service.ev_pool.values())
        else:
            buildings_iterable = list(getattr(env, 'buildings', []))
            ev_iterable = list(getattr(env, 'electric_vehicles', []))

        for building in buildings_iterable:
            _record(building)
            electrical_storage = getattr(building, 'electrical_storage', None)
            if electrical_storage is not None:
                _record(electrical_storage)

            for charger in getattr(building, 'electric_vehicle_chargers', []) or []:
                _record(charger)

            for appliance in getattr(building, 'deferrable_appliances', []) or []:
                _record(appliance)

        for ev in ev_iterable:
            _record(ev)
            battery = getattr(ev, 'battery', None)
            if battery is not None:
                _record(battery)

        return snapshot

    @staticmethod
    def restore_render_time_step(snapshot):
        for obj, value in snapshot:
            try:
                obj.time_step = value
            except AttributeError:
                pass

    def reset_time_tracking(self):
        """Reset render timestamp tracking to episode start."""

        env = self.env
        start_offset = getattr(env.episode_tracker, 'episode_start_time_step', 0)
        base_datetime = datetime.datetime.combine(env.render_start_date, datetime.time())
        base_datetime += datetime.timedelta(seconds=start_offset * env.seconds_per_time_step)
        env._render_start_datetime = base_datetime
        env.year = base_datetime.year
        env.current_day = base_datetime.day
