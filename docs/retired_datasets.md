# Retired dataset format notes

Portuguese version: [pt/retired_datasets.md](pt/retired_datasets.md).

## Retired 2023 Annual REC Suite

Versions 1.8.0 through 3.0.1 included a reproducible hybrid annual scenario ladder for thesis and
algorithm experiments. Every family uses the full 2023 UTC timeline, 35,040
15-minute steps, Lisbon local-calendar attributes and self-contained Parquet
files. The old hourly 17-building scenario remains available for historical
reproduction but is not part of this suite.

These five `rec_2023_*` datasets were removed from the public repository and
default dataset registry in CityLearn 3.0.2. This section is retained only as
historical format documentation; users must supply their own local data files.

Routine schedules are constructed as `Europe/Lisbon` civil wall-clock times
before conversion to UTC. The missing spring hour is shifted forward by one
hour and the first occurrence of the repeated autumn hour is selected
deterministically. This preserves intended local routines on both DST
transition days while retaining an unambiguous physical UTC timeline.

| Family | Members | PV | BESS | Charging members | Chargers | Deferrables | Variants |
|---|---:|---:|---:|---:|---:|---:|---|
| `rec_2023_micro_4_q` | 4 | 2 | 1 | 2 | 2 | 1 | `MICRO-4-Q` |
| `rec_2023_core_15_stripped` | 15 | 7 | 3 | 6 | 7 | 4 | `CORE-15-STRIPPED` |
| `rec_2023_core_30` | 30 | 15 | 6 | 12 | 15 | 8 | Nominal, Safety, Health, Dynamic and Combined |
| `rec_2023_premium_100` | 100 | 55 | 22 | 45 | 80 | 30 | Clean and AllIn |

Each family has a default `schema.json`; alternative variants are under
`schemas/`. The variants point to the same physical files, making Safety,
Health, Dynamic and AllIn comparisons clean twins. `catalogs/` separates
member, physical-charger, EV and charging-session identities. This permits
multiple chargers at one member and different EV sessions on the same shared
charger without conflating infrastructure and mobility.

Contract `2023-q15-v1.9` also stratifies installed assets instead of nesting
every flexible asset in the lowest-numbered PV members. In Core-15, Core-30 and
Premium, charging members include both PV and non-PV hosts; the Micro case also
includes one of each. Batteries remain
PV-coupled but are distributed across routines and member indices. This keeps
the declared composition unchanged while reducing PV/EV allocation
confounding. Variant schemas use an explicit parent-relative root so they can
be opened directly from `schemas/`.

Demand shapes are synthetic but their annual targets are anchored to 2023
Portuguese per-consumer residential, non-domestic and industrial consumption
classes. Five stratified routine archetypes per full category change operating
hours, peaks, occupancy, reduced-activity days, EV windows and deferrable-load
requests. PV capacity is coupled to host annual demand and varies with
orientation and derating. Stationary storage uses product-like capacity/power
classes sized from stratified daily-load autonomy with a host-PV floor; SOC,
efficiency and degradation parameters vary by member. Weather forecasts have
reproducible horizon-dependent error. Derived load and PV forecasts use causal
previous-day persistence, with a current-step cold start during the first day,
so algorithms cannot observe future load/PV truth through this bundle. OMIE
price horizons are publication-aware: realised values are used only after the
declared day-ahead cut-off, with causal daily persistence beforehand. These are
controlled scenario distributions, not a statistically fitted sample of
Portuguese RECs.

Every ordinary EV session is individually feasible at its declared charger
power and 95% efficiency. Residential requests use at most 85% of the
charger-window energy; shared-service requests use at most 72%, which reserves
at least one control step even for the shortest ordinary sessions. Safety and
AllIn can still make joint service
infeasible through concurrent demand, total/per-phase limits, deadlines and
faults. Dynamic variants separately exercise member lifecycle and independent
charger, PV, stationary-storage and deferrable-asset removal/restoration.
Members that join do not inherit service failures from requests that expired
before their membership began. Departures are permanent within the benchmark
year, avoiding an implicit reset of accumulated participant state. Residential
chargers with an individual phase connection are allocated by a deterministic
family-level rotation whose L1/L2/L3 counts differ by at most one.

A reinstalled stateful asset is a new runtime instance initialized at its
declared boundary state; it does not silently inherit the removed instance's
SoC or pending service. The pre-removal instance remains available to KPI
aggregation. Energy carried into the REC at such an activation boundary is an
exogenous initial condition, not grid energy created inside a control step.

`catalogs/electrical_services.parquet` records each member's Portuguese
BTN/BTE-level connection surrogate, single-/three-phase assignment and total
and per-phase import/export limits. kVA is mapped to kW at an explicit unity
power factor; this tests connection headroom, not feeder power flow or
protection. The generator verifies the native non-shiftable-load/PV envelope
before flexible assets act and, where necessary, moves the member to the next
declared BTE level with a 2% native margin. Thus an ordinary safety violation
must arise from controllable concurrency or a labelled event, not an impossible
exogenous baseline. `file_checksums.sha256` freezes all generated family files.

Electricity prices come from the official OMIE Portugal day-ahead archive.
Each 2023 physical hourly market period is repeated over its four quarter-hour
simulation steps without interpolation and converted from EUR/MWh to EUR/kWh.
Daily source URLs, revision numbers and SHA-256 hashes are retained under
`sources/`. Settlement uses same-step local matching, a local price equal to
80% of OMIE, equal importer weights, zero residual-export remuneration and a
grid-only counterfactual.

Generate and validate the complete suite with:

```console
.venv/bin/python scripts/generate_annual_rec_suite.py --families all
.venv/bin/python scripts/audit/audit_annual_rec_suite.py
.venv/bin/python scripts/audit/audit_annual_rec_suite_diversity.py
.venv/bin/python scripts/audit/audit_annual_rec_suite_scientific.py
.venv/bin/python scripts/audit/smoke_annual_rec_suite.py
```

The audit checks the common time contract, OMIE expansion and provenance,
asset and session identities, individual EV feasibility, deferrable deadlines,
Portuguese connection levels and phase sums, multi-charger membership, dynamic
asset coverage, complete file checksums, scenario-twin invariants and the
byte-identical Core-15 subset of Core-30. The diversity audit additionally
measures exact duplicate traces, pairwise and cross-archetype profile
correlations, peak times, PV/BESS distributions, EV arrival/duration/slack
distributions and deferrable schedule duplication.
