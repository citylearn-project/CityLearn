"""Offline independent balance audit using a directed physical-flow network.

No production accounting, settlement or KPI formula is used to calculate expected
values. Battery journals are physical measurements and are checked against device
terminals and stored energy. This is model-consistency evidence, not calibration.
"""

from collections import defaultdict
from copy import deepcopy
import csv
from pathlib import Path

import numpy as np

DEFINITION_VERSION = "independent-flow-audit-v1"
DESTINATIONS = (
    "load",
    "mobility",
    "grid_export",
    "loss",
    "asset_exit",
    "external_reset",
    "curtailment",
    "stored",
)


class BalanceAuditError(AssertionError):
    pass


def plus(target, values, factor=1.0):
    for key, value in values.items():
        target[key] = target.get(key, np.zeros(2)) + np.asarray(value) * factor
    return target


def total(values):
    return sum(float(v[0]) for v in values.values())


class FlowNetwork:
    """Solve concentrations from Kirchhoff balances on explicit operation nodes."""

    def __init__(self):
        self.mass, self.inputs, self.edges, self.sinks = [], [], [], []

    def node(self, mass, inputs=None):
        i = len(self.mass)
        self.mass.append(float(mass))
        self.inputs.append(inputs or {})
        return i

    def edge(self, source, target, amount):
        self.edges.append((source, target, float(amount)))

    def sink(self, node, key, amount):
        self.sinks.append((node, key, float(amount)))

    def solve(self, check):
        size = len(self.mass)
        labels = sorted({key for source in self.inputs for key in source})
        index = {key: i for i, key in enumerate(labels)}
        matrix = np.diag(self.mass)
        rhs = np.zeros((size, 2 * len(labels)))
        incoming = np.zeros(size)
        outgoing = np.zeros(size)
        for node, source in enumerate(self.inputs):
            incoming[node] += total(source)
            for key, value in source.items():
                rhs[node, 2 * index[key] : 2 * index[key] + 2] += value
        for a, b, flow in self.edges:
            if flow < -1e-10:
                raise BalanceAuditError("Negative physical edge")
            matrix[b, a] -= flow
            incoming[b] += flow
            outgoing[a] += flow
        for node, key, flow in self.sinks:
            outgoing[node] += flow
        for i, mass in enumerate(self.mass):
            check(f"node_{i}_input", incoming[i], mass)
            check(f"node_{i}_output", outgoing[i], mass)
        active = np.flatnonzero(np.asarray(self.mass) > 1e-12)
        concentrations = np.zeros_like(rhs)
        rank = len(active)
        if len(active):
            a = matrix[np.ix_(active, active)] / np.asarray(self.mass)[active, None]
            b = rhs[active] / np.asarray(self.mass)[active, None]
            x, _, rank, _ = np.linalg.lstsq(a, b, rcond=1e-12)
            for value in (a @ x - b).ravel():
                check("flow_network_equation", float(value), 0.0)
            if x.size and float(x.min()) < -1e-7:
                raise BalanceAuditError("Negative source concentration")
            concentrations[active] = np.maximum(x, 0.0)
        output = {}
        for node, key, flow in self.sinks:
            bag = {
                label: concentrations[node, 2 * i : 2 * i + 2] * flow
                for i, label in enumerate(labels)
            }
            plus(output.setdefault(key, {}), bag)
        return output, concentrations, labels, len(active) - rank


def weighted_imports(demands, traded, weights):
    """Independent progressive filling at demand-saturation breakpoints."""
    demands = np.asarray(demands, dtype=float)
    weights = np.maximum(np.asarray(weights, dtype=float), 0.0)
    result = np.zeros_like(demands)
    remaining = float(traded)
    for _ in range(len(demands) + 1):
        active = demands - result > 1e-12
        if not np.any(active) or remaining <= 1e-12:
            break
        rates = (
            weights[active]
            if weights[active].sum() > 1e-9
            else np.ones(int(active.sum()))
        )
        positive = rates > 0.0
        next_cap = float(
            ((demands[active] - result[active])[positive] / rates[positive]).min()
        )
        level = min(remaining / float(rates.sum()), next_cap)
        granted = rates * level
        result[active] += granted
        remaining -= float(granted.sum())
    return result


class IndependentBalanceAudit:
    """Attach after reset at interval zero; detach before resetting the episode.

    The optional instrumentation observes both normal and no-feedback transitions.
    It adds no dispatch decisions and preserves the original runtime methods.
    """

    def __init__(self, env, *, absolute_tolerance=1e-5, relative_tolerance=1e-7):
        if env.time_step != 0:
            raise ValueError("Start an audit immediately after reset, before actions")
        self.env = env
        self.atol = float(absolute_tolerance)
        self.rtol = float(relative_tolerance)
        self.stocks = {}
        self.sources = {}
        self.sinks = {}
        self.transfers = {}
        self.members = defaultdict(lambda: defaultdict(float))
        self.intervals = []
        self.check_count = 0
        self.max_error = 0.0
        self.max_scaled_error = 0.0
        self.singular_networks = 0
        self._original = {}
        self._tariffs = {}
        root = Path(env.schema.get("root_directory") or ".")
        for name, filename in (
            (env.schema.get("community_market") or {}).get("tariff_files", {}).items()
        ):
            with (root / filename).open() as stream:
                self._tariffs[name] = list(csv.DictReader(stream))
        self.boundary()
        self.initial_inventory = {
            str(k): total(s["mix"]) for k, s in self.stocks.items()
        }

    def check(self, label, actual, expected):
        if expected is None:
            self.check_count += 1
            if actual is not None and np.isfinite(float(actual)):
                raise BalanceAuditError(label + ": expected undefined value")
            return
        actual, expected = float(actual), float(expected)
        error = abs(actual - expected)
        limit = self.atol + self.rtol * max(abs(actual), abs(expected))
        self.check_count += 1
        self.max_error = max(self.max_error, error)
        self.max_scaled_error = max(self.max_scaled_error, error / limit)
        if not np.isfinite(actual) or not np.isfinite(expected) or error > limit:
            raise BalanceAuditError(
                f"{label}: actual={actual:.12g}, expected={expected:.12g}, tolerance={limit:.3g}"
            )

    def _assets(self):
        result = {}
        for b in self.env.buildings:
            candidates = []
            if b.electrical_storage is not None and b.electrical_storage.capacity > 0:
                candidates.append((b.electrical_storage, "stationary", None))
            for charger in b.electric_vehicle_chargers or []:
                ev = charger.connected_electric_vehicle
                if ev is not None:
                    candidates.append((ev.battery, "ev", charger))
            for battery, kind, connection in candidates:
                if id(battery) in result:
                    raise BalanceAuditError(
                        "One battery appears on multiple active ports"
                    )
                result[id(battery)] = dict(
                    battery=battery, owner=b.name, kind=kind, connection=connection
                )
        return result

    def _pending(self, stock):
        battery = stock["battery"]
        if stock["step"] != battery.time_step:
            stock["step"], stock["cursor"] = battery.time_step, 0
        return battery.energy_provenance_events[stock["cursor"] :]

    def _source(self, key, amount, carbon=0.0):
        bag = {key: np.array([amount, carbon])}
        plus(self.sources, bag)
        return bag

    def _sink(self, owner, destination, bag):
        plus(self.sinks.setdefault((owner, destination), {}), bag)

    def boundary(self):
        for building in self.env.buildings:
            self.members[building.name]
        assets = self._assets()
        chargers = {
            id(c) for b in self.env.buildings for c in b.electric_vehicle_chargers or []
        }
        for key, stock in list(self.stocks.items()):
            if key not in assets or stock["owner"] != assets[key]["owner"]:
                destination = (
                    "mobility"
                    if stock["kind"] == "ev" and id(stock["connection"]) in chargers
                    else "asset_exit"
                )
                self._sink(stock["owner"], destination, stock["mix"])
                del self.stocks[key]
        for key, asset in assets.items():
            battery = asset["battery"]
            owner = asset["owner"]
            if key not in self.stocks:
                self.stocks[key] = dict(
                    asset,
                    mix=self._source(("unknown", owner), float(battery.energy_init)),
                    step=battery.time_step,
                    cursor=len(battery.energy_provenance_events),
                )
                continue
            stock = self.stocks[key]
            for event in self._pending(stock):
                if event["kind"] == "transfer":
                    raise BalanceAuditError(
                        "Unobserved transfer at an interval boundary"
                    )
                self.check(
                    "boundary stored energy", total(stock["mix"]), event["before"]
                )
                if event["kind"] == "external":
                    self._sink(owner, "external_reset", stock["mix"])
                    stock["mix"] = self._source(("unknown", owner), event["after"])
                else:
                    ratio = (
                        event["after"] / event["before"] if event["before"] > 0 else 0.0
                    )
                    self._sink(
                        owner,
                        "loss",
                        {k: v * (1 - ratio) for k, v in stock["mix"].items()},
                    )
                    stock["mix"] = {k: v * ratio for k, v in stock["mix"].items()}
                stock["cursor"] += 1
            self.check("boundary inventory", total(stock["mix"]), battery.energy_init)
        self._check_cohorts()

    def __enter__(self):
        runtime = self.env._runtime_service
        if getattr(runtime, "_independent_audit_attached", False):
            raise ValueError("An audit is already attached")
        runtime._independent_audit_attached = True
        for name in ("update_variables", "_step_once", "step_without_feedback"):
            original = getattr(runtime, name)
            self._original[name] = original
            if name == "update_variables":

                def wrapper(*args, _original=original, **kwargs):
                    value = _original(*args, **kwargs)
                    self.record()
                    return value
            else:

                def wrapper(*args, _original=original, **kwargs):
                    value = _original(*args, **kwargs)
                    self.boundary()
                    return value

            setattr(runtime, name, wrapper)
        return self

    def __exit__(self, *args):
        for name, method in self._original.items():
            setattr(self.env._runtime_service, name, method)
        self.env._runtime_service._independent_audit_attached = False

    def prices(self, building, t):
        price = float(building.pricing.electricity_pricing[t])
        if building.name in self._tariffs:
            row = self._tariffs[building.name][
                self.env.episode_tracker.episode_start_time_step + t
            ]
            return (
                price,
                float(row["grid_export_price"]),
                float(row["community_buy_price"]),
                float(row["community_sell_price"]),
            )
        config = self.env.schema.get("community_market") or {}
        ratio = min(
            max(
                float(
                    config.get(
                        "local_price_ratio_to_grid_import",
                        config.get("intra_community_sell_ratio", 0.8),
                    )
                ),
                0.0,
            ),
            1.0,
        )
        export = (
            float(config.get("grid_export_price", 0.0))
            if config.get("settlement_version") == 2
            else 0.0
        )
        return price, export, ratio * price, ratio * price

    def record(self):
        env = self.env
        t = int(env.time_step)
        if t != len(self.intervals):
            raise BalanceAuditError("Repeated/missing interval or reset during audit")
        graph = FlowNetwork()
        buses = {}
        rows = {}
        transfers = defaultdict(float)
        for key, stock in self.stocks.items():
            movements = [
                e["bus"] for e in self._pending(stock) if e["kind"] == "transfer"
            ]
            transfers[stock["owner"]] += sum(movements)
            if stock["kind"] == "stationary":
                power = float(stock["battery"].nominal_power)
                duty = sum(abs(v) for v in movements) / power if power > 0 else 0.0
            else:
                port = stock["connection"]
                duty = sum(
                    v / port.max_charging_power
                    if v >= 0
                    else -v / port.max_discharging_power
                    for v in movements
                    if v
                )
            self.check(
                "interval nameplate duty",
                max(duty - float(env.seconds_per_time_step) / 3600.0, 0.0),
                0.0,
            )
        for b in env.buildings:
            load = sum(
                float(getattr(b, name)[t])
                for name in (
                    "non_shiftable_load_electricity_consumption",
                    "cooling_electricity_consumption",
                    "heating_electricity_consumption",
                    "dhw_electricity_consumption",
                    "deferrable_appliances_electricity_consumption",
                    "escalators_electricity_consumption",
                )
            )
            pv = max(-float(b.solar_generation[t]), 0.0)
            measured_ac = float(
                b.electrical_storage_electricity_consumption[t]
            ) + float(b.chargers_electricity_consumption[t])
            self.check("device terminal journal", transfers[b.name], measured_ac)
            net = load + measured_ac - pv
            curtailed = max(-net, 0.0) if bool(b.power_outage) else 0.0
            self.check(
                "curtailment cannot exceed available PV", max(curtailed - pv, 0.0), 0.0
            )
            net += curtailed
            if hasattr(b, "pv_curtailment"):
                self.check(
                    "physical PV curtailment", float(b.pv_curtailment[t]), curtailed
                )
            self.check(
                "physical building bus " + b.name,
                float(b.net_electricity_consumption[t]),
                net,
            )
            rows[b.name] = dict(
                load=load,
                pv=pv,
                curtailed=curtailed,
                net=net,
                building=b,
                charge=0.0,
                discharge=0.0,
            )
        names = list(rows)
        imports = np.maximum([rows[n]["net"] for n in names], 0.0)
        exports = np.maximum([-rows[n]["net"] for n in names], 0.0)
        config = env.schema.get("community_market") or {}
        financial = bool(env.community_market_enabled)
        physical_trading = not financial or bool(
            config.get("local_trading_enabled", True)
        )
        traded = (
            min(float(imports.sum()), float(exports.sum())) if physical_trading else 0.0
        )
        weights = [
            (config.get("import_member_weights") or {}).get(n, 1.0) for n in names
        ]
        local_in = weighted_imports(imports, traded, weights)
        local_out = (
            exports * (traded / exports.sum())
            if exports.sum() > 0
            else np.zeros_like(exports)
        )
        for i, name in enumerate(names):
            row = rows[name]
            b = row["building"]
            grid_in = max(float(imports[i] - local_in[i]), 0.0)
            grid_out = max(float(exports[i] - local_out[i]), 0.0)
            ci = float(b.carbon_intensity.carbon_intensity[t])
            origin = "grid" if np.isfinite(ci) else "grid_unknown_carbon"
            inputs = {}
            available = self._source(("pv", name), row["pv"])
            plus(
                inputs,
                available,
                (row["pv"] - row["curtailed"]) / row["pv"] if row["pv"] > 0 else 0.0,
            )
            if row["curtailed"] > 0:
                self._sink(
                    name,
                    "curtailment",
                    {("pv", name): np.array([row["curtailed"], 0.0])},
                )
            plus(
                inputs,
                self._source(
                    (origin, name), grid_in, grid_in * ci if np.isfinite(ci) else 0.0
                ),
            )
            discharge = sum(
                -e["bus"]
                for s in self.stocks.values()
                if s["owner"] == name
                for e in self._pending(s)
                if e["kind"] == "transfer" and e["bus"] < 0.0
            )
            charge = sum(
                e["bus"]
                for s in self.stocks.values()
                if s["owner"] == name
                for e in self._pending(s)
                if e["kind"] == "transfer" and e["bus"] >= 0.0
            )
            supply = row["pv"] - row["curtailed"] + discharge + imports[i]
            buses[name] = graph.node(supply, inputs)
            graph.sink(buses[name], (name, "load"), row["load"])
            graph.sink(buses[name], (name, "grid_export"), grid_out)
            row.update(
                grid_import=grid_in,
                grid_export=grid_out,
                local_import=float(local_in[i]),
                local_export=float(local_out[i]),
            )
            member = self.members[name]
            for field, value in [
                ("pv_generated_kwh", row["pv"]),
                ("pv_curtailment_kwh", row["curtailed"]),
                ("import_kwh", imports[i]),
                ("export_kwh", exports[i]),
                ("net_kwh", row["net"]),
                ("external_import_kwh", grid_in),
                ("load_kwh", row["load"]),
                (
                    "external_purchase_emissions_kgco2",
                    grid_in * ci if np.isfinite(ci) else 0.0,
                ),
            ]:
                member[field] += float(value)
            member["appliance_kwh"] += float(
                b.deferrable_appliances_electricity_consumption[t]
            )
            p, pe, pb, ps = self.prices(b, t)
            cost = (
                grid_in * p + local_in[i] * pb - local_out[i] * ps - grid_out * pe
                if financial
                else imports[i] * p
            )
            operator = local_in[i] * pb - local_out[i] * ps if financial else 0.0
            member["cost_eur"] += float(cost)
            member["operator_balance_eur"] += float(operator)
            self.check(
                "member settled cost " + name,
                float(b.net_electricity_consumption_cost[t]),
                cost,
            )
            if financial:
                observed = {
                    r["building"]: r for r in env._last_community_market_settlement
                }[name]
                for field, expected in [
                    ("grid_import_kwh", grid_in),
                    ("grid_export_kwh", grid_out),
                    ("local_import_kwh", local_in[i]),
                    ("local_export_kwh", local_out[i]),
                    ("grid_import_price", p),
                    ("grid_export_price", pe),
                    ("local_buy_price", pb),
                    ("local_sell_price", ps),
                    ("operator_balance_eur", operator),
                    ("settled_cost_eur", cost),
                ]:
                    self.check(
                        "market " + name + " " + field, observed[field], expected
                    )
        # Trade is a complete bipartite graph between net sellers and buyers.
        for i, seller in enumerate(names):
            for j, buyer in enumerate(names):
                flow = float(local_out[i] * local_in[j] / traded) if traded > 0 else 0.0
                if flow:
                    graph.edge(buses[seller], buses[buyer], flow)
        final_nodes = {}
        for key, stock in self.stocks.items():
            owner = stock["owner"]
            mix = stock["mix"]
            current = total(mix)
            for event in self._pending(stock):
                if event["kind"] == "transfer":
                    self.members[owner][stock["kind"] + "_charge_kwh"] += max(
                        event["bus"], 0.0
                    )
                    self.members[owner][stock["kind"] + "_discharge_kwh"] += max(
                        -event["bus"], 0.0
                    )
            previous = graph.node(current, mix)
            for event in self._pending(stock):
                self.check("operation initial energy", current, event["before"])
                after = float(event["after"])
                if event["kind"] == "external":
                    graph.sink(previous, (owner, "external_reset"), current)
                    previous = graph.node(
                        after, self._source(("unknown", owner), after)
                    )
                    current = after
                else:
                    ac = float(event["bus"]) if event["kind"] == "transfer" else 0.0
                    loss = current + ac - after
                    if loss < -self.atol:
                        raise BalanceAuditError(
                            "Physical operation creates stored energy"
                        )
                    # Conversion loss is upstream of mixing on charge. Old
                    # inventory must not inherit the fresh input's charge losses.
                    stored = max(after - current, 0.0) if ac >= 0 else 0.0
                    node = graph.node(current + stored)
                    graph.edge(previous, node, current)
                    if ac >= 0:
                        graph.edge(buses[owner], node, stored)
                        graph.sink(buses[owner], (owner, "loss"), max(loss, 0.0))
                    else:
                        graph.edge(node, buses[owner], -ac)
                        graph.sink(node, (owner, "loss"), max(loss, 0.0))
                    previous = node
                    current = after
                stock["cursor"] += 1
            graph.sink(previous, ("inventory", key), current)
            final_nodes[key] = previous
            self.check(
                "operation final inventory", current, stock["battery"].energy_init
            )
        result, concentrations, labels, singular = graph.solve(self.check)
        self.singular_networks += int(singular > 0)
        for (owner, destination), bag in result.items():
            if owner == "inventory":
                self.stocks[destination]["mix"] = bag
            else:
                self._sink(owner, destination, bag)
        for i, name in enumerate(names):
            for direction, amount in [
                ("local_import", local_in[i]),
                ("local_export", local_out[i]),
            ]:
                if direction == "local_export":
                    node = buses[name]
                    mix = {
                        label: concentrations[node, 2 * k : 2 * k + 2] * amount
                        for k, label in enumerate(labels)
                    }
                else:
                    mix = {}
                    for j, seller in enumerate(names):
                        flow = local_out[j] * amount / traded if traded > 0 else 0.0
                        for k, label in enumerate(labels):
                            plus(
                                mix,
                                {
                                    label: concentrations[
                                        buses[seller], 2 * k : 2 * k + 2
                                    ]
                                    * flow
                                },
                            )
                plus(self.transfers.setdefault((name, direction), {}), mix)
        # A second network tracks fresh PV without carrying it through storage.
        direct_matrix = np.diag([graph.mass[buses[n]] for n in names])
        direct_rhs = np.array([rows[n]["pv"] - rows[n]["curtailed"] for n in names])
        for i, seller in enumerate(names):
            for j, buyer in enumerate(names):
                if traded > 0:
                    direct_matrix[j, i] -= local_out[i] * local_in[j] / traded
        direct = (
            np.linalg.lstsq(direct_matrix, direct_rhs, rcond=1e-12)[0] if names else []
        )
        for i, name in enumerate(names):
            self.members[name]["pv_load_direct_kwh"] += float(
                direct[i] * rows[name]["load"]
            )
        external_cash = sum(
            r["grid_import"] * self.prices(r["building"], t)[0]
            - r["grid_export"] * self.prices(r["building"], t)[1]
            for r in rows.values()
        )
        if financial:
            self.check(
                "operator/member/external cash conservation",
                sum(v["cost_eur"] for v in self.members.values())
                - sum(v["operator_balance_eur"] for v in self.members.values()),
                sum(x["external_cash_eur"] for x in self.intervals) + external_cash,
            )
        self.intervals.append(
            dict(
                time_step=t,
                names=names,
                external_cash_eur=external_cash,
                net_kwh=sum(r["net"] for r in rows.values()),
                cost_eur=sum(
                    float(r["building"].net_electricity_consumption_cost[t])
                    for r in rows.values()
                ),
            )
        )

    def expected_rows(self):
        rows = {}
        bags = dict(self.sinks)
        for stock in self.stocks.values():
            plus(bags.setdefault((stock["owner"], "stored"), {}), stock["mix"])
        for (recipient, destination), bag in bags.items():
            for (origin, producer), value in bag.items():
                if abs(value[0]) > 1e-10:
                    rows[origin, producer, recipient, destination] = np.asarray(value)
        return rows

    def _check_cohorts(self):
        observed = {}
        for row in self.env._provenance_service.source_destinations():
            key = tuple(
                row[k] for k in ("origin", "producer", "recipient", "destination")
            )
            observed[key] = np.array([row["energy_kwh"], row["carbon_kgco2"]])
        expected = self.expected_rows()
        for key in set(expected) | set(observed):
            for component, unit in enumerate(("kwh", "kgco2")):
                self.check(
                    "provenance " + str(key) + " " + unit,
                    observed.get(key, np.zeros(2))[component],
                    expected.get(key, np.zeros(2))[component],
                )

    def finish(self, *, check_kpis=True):
        self.boundary()
        expected = self.expected_rows()
        source = defaultdict(lambda: np.zeros(2))
        destination = defaultdict(lambda: np.zeros(2))
        for (origin, producer), value in self.sources.items():
            source[origin] += value
        for (origin, producer, recipient, dest), value in expected.items():
            destination[origin] += value
        for origin in set(source) | set(destination):
            for i, unit in enumerate(("kwh", "kgco2")):
                self.check(
                    "global source/destination " + origin + " " + unit,
                    source[origin][i],
                    destination[origin][i],
                )
        actual_members, actual_district = self.env._provenance_service.summary()
        for name, values in self.members.items():
            self.check(
                "direct PV " + name,
                actual_members[name]["pv_load_direct_kwh"],
                values["pv_load_direct_kwh"],
            )
        for direction in ("local_import", "local_export"):
            for name in self.members:
                bag = self.transfers.get((name, direction), {})
                self.check(
                    "local transfer " + name + " " + direction,
                    actual_members[name][direction + "_kwh"],
                    total(bag),
                )
        if check_kpis:
            frame = self.env.evaluate_v2(include_business_as_usual=False)
            values = {(r.name, r.cost_function): r.value for r in frame.itertuples()}
            for name, row in self.members.items():
                for suffix, key in [
                    ("cost_total_control_eur", "cost_eur"),
                    ("energy_grid_total_import_control_kwh", "import_kwh"),
                    ("energy_grid_total_export_control_kwh", "export_kwh"),
                    ("solar_self_consumption_total_generation_kwh", "pv_generated_kwh"),
                ]:
                    self.check(
                        "KPI " + name + " " + suffix,
                        values[name, "building_" + suffix],
                        row[key],
                    )
                for kind, prefix in [("stationary", "battery"), ("ev", "ev")]:
                    for direction in ("charge", "discharge"):
                        suffix = (
                            "v2g_export"
                            if kind == "ev" and direction == "discharge"
                            else direction
                        )
                        self.check(
                            "equipment KPI " + name + " " + kind + " " + direction,
                            values[
                                name, "building_" + prefix + "_total_" + suffix + "_kwh"
                            ],
                            row.get(kind + "_" + direction + "_kwh", 0.0),
                        )
            appliance_audit = self.env.get_deferrable_service_audit()
            for name, row in self.members.items():
                self.check(
                    "appliance physical service " + name,
                    appliance_audit["buildings"]
                    .get(name, {})
                    .get("served_energy_kwh", 0.0),
                    row.get("appliance_kwh", 0.0),
                )
            for name, summary in self.expected_summary().items():
                level = "district" if name == "District" else "building"
                for key, expected_value in summary.items():
                    self.check(
                        "provenance KPI " + name + " " + key,
                        values[name, level + "_energy_provenance_" + key],
                        expected_value,
                    )
            for key, suffix in [
                ("net_kwh", "energy_grid_total_net_exchange_control_kwh"),
                ("cost_eur", "cost_total_control_eur"),
            ]:
                self.check(
                    "district KPI " + suffix,
                    values["District", "district_" + suffix],
                    sum(r[key] for r in self.members.values()),
                )
        return dict(
            definition_version=DEFINITION_VERSION,
            status="pass",
            completed_intervals=len(self.intervals),
            checks=self.check_count,
            max_absolute_error=self.max_error,
            max_tolerance_fraction=self.max_scaled_error,
            absolute_tolerance=self.atol,
            relative_tolerance=self.rtol,
            source_free_circulation_intervals=self.singular_networks,
            members={k: dict(v) for k, v in self.members.items()},
            carbon_boundary="acquisition_carbon; unknown input energy remains in explicit unknown cohorts",
            initial_inventory_kwh=sum(self.initial_inventory.values()),
            final_inventory_kwh=sum(total(s["mix"]) for s in self.stocks.values()),
            expected_provenance=self.expected_summary(),
            source_destinations=[
                dict(
                    origin=k[0],
                    producer=k[1],
                    recipient=k[2],
                    destination=k[3],
                    energy_kwh=float(v[0]),
                    carbon_kgco2=float(v[1]),
                )
                for k, v in sorted(expected.items())
            ],
        )

    def expected_summary(self):
        rows = {}
        expected = self.expected_rows()
        for name, stats in self.members.items():
            summary = {
                key: stats[key]
                for key in (
                    "pv_generated_kwh",
                    "external_import_kwh",
                    "external_purchase_emissions_kgco2",
                    "pv_load_direct_kwh",
                )
            }
            summary["unknown_input_kwh"] = sum(
                v[0]
                for (origin, producer), v in self.sources.items()
                if producer == name and origin == "unknown"
            )
            summary["external_purchase_unknown_carbon_kwh"] = sum(
                v[0]
                for (origin, producer), v in self.sources.items()
                if producer == name and origin == "grid_unknown_carbon"
            )
            for dest in DESTINATIONS:
                entries = [
                    (key[0], v)
                    for key, v in expected.items()
                    if key[2] == name and key[3] == dest
                ]
                for prefix, origins in [
                    ("pv", {"pv"}),
                    ("grid", {"grid", "grid_unknown_carbon"}),
                    ("unknown", {"unknown"}),
                ]:
                    summary[prefix + "_" + dest + "_kwh"] = sum(
                        v[0] for origin, v in entries if origin in origins
                    )
                summary["carbon_" + dest + "_kgco2"] = sum(
                    v[1] for origin, v in entries
                )
                summary["carbon_unknown_" + dest + "_kwh"] = sum(
                    v[0]
                    for origin, v in entries
                    if origin in {"unknown", "grid_unknown_carbon"}
                )
            for direction in ("local_import", "local_export"):
                bag = self.transfers.get((name, direction), {})
                summary[direction + "_kwh"] = total(bag)
                summary["pv_" + direction + "_kwh"] = sum(
                    v[0] for (origin, _), v in bag.items() if origin == "pv"
                )
                summary["grid_" + direction + "_kwh"] = sum(
                    v[0]
                    for (origin, _), v in bag.items()
                    if origin in {"grid", "grid_unknown_carbon"}
                )
            summary["pv_load_after_storage_kwh"] = max(
                summary["pv_load_kwh"] - summary["pv_load_direct_kwh"], 0.0
            )
            rows[name] = summary
        district = {
            key: sum(r[key] for r in rows.values())
            for key in next(iter(rows.values()), {})
        }
        for origin, source_key in [
            ("pv", "pv_generated_kwh"),
            ("grid", "external_import_kwh"),
            ("unknown", "unknown_input_kwh"),
            ("carbon", "external_purchase_emissions_kgco2"),
        ]:
            unit = "kgco2" if origin == "carbon" else "kwh"
            district[origin + "_balance_residual_" + unit] = district.get(
                source_key, 0.0
            ) - sum(
                district.get(origin + "_" + dest + "_" + unit, 0.0)
                for dest in DESTINATIONS
            )
        pv = district.get("pv_generated_kwh", 0.0)
        district["pv_useful_building_ratio"] = (
            district.get("pv_load_kwh", 0.0) / pv if pv > 0 else None
        )
        district["pv_useful_with_mobility_ratio"] = (
            (district.get("pv_load_kwh", 0.0) + district.get("pv_mobility_kwh", 0.0))
            / pv
            if pv > 0
            else None
        )
        rows["District"] = district
        return rows
