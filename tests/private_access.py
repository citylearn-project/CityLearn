"""Shared test access to CityLearn internals.

Many tests need state that CityLearn does not expose publicly, such as an environment's
internal services or a building's charging-constraint ledger. They read it through these
helpers, so that renaming an internal member means changing one line here instead of
every test that uses it. Tests that exercise a private function or method directly still
call it by name.
"""

from __future__ import annotations


def topology_service(env):
    return env._topology_service


def member_pool(env):
    """Every member the environment has loaded, active or not, keyed by name."""
    return env._topology_service.member_pool


def kpi_service(env):
    return env._kpi_service


def kpi_buildings(env):
    """The buildings the KPI service evaluates."""
    return env._kpi_service._get_kpi_buildings()


def robustness_service(env):
    return env._robustness_service


def entity_service(env):
    return env._entity_service


def provenance_service(env):
    return env._provenance_service


def runtime_service(env):
    return env._runtime_service


def ops_service(env):
    return env._ops_service


def physics_invariant_service(env):
    return env._physics_invariant_service


def demand_response_service(env):
    return env._demand_response_service


def baseline_service(env):
    """The native business-as-usual baseline service."""
    return env._business_as_usual_baseline_service


def market_settlement_history(env):
    """Per-step community market settlement rows."""
    return env._community_market_settlement_history


def ev_drift_seed(env):
    return env._ev_drift_seed


def charging_constraints_state(building):
    return building._charging_constraints_state


def charging_constraint_last_penalty_kwh(building):
    return building._charging_constraint_last_penalty_kwh
