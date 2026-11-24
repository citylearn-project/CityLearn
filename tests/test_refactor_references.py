"""Frozen pre-refactor evidence and meaningful negative comparator tests."""

from copy import deepcopy
import json

import pytest

from scripts.audit import audit_refactor_parity as parity


@pytest.mark.parametrize("physics_version", sorted(parity.REFERENCES))
@pytest.mark.parametrize("name", parity.CASES)
def test_fixed_commands_match_frozen_physical_and_interface_reference(tmp_path, name, physics_version):
    reference = json.loads(parity.REFERENCES[physics_version].read_text())
    actual, proof = parity.run_case(name, tmp_path, physics_version)
    comparison = parity.compare(reference["cases"][name], actual)
    assert comparison["matches"], comparison["differences"]
    assert proof["status"] == "pass" and proof["intervals"] == 7
    assert proof["checks"] > 1000
    physical = [building for step in actual["transitions"] for building in step["physical"].values()]
    assert any(abs(row["storage_kwh"]) > 1e-5 for row in physical)
    service = actual["service"]["district"]
    assert sum(row["machine_kwh"] for row in physical) == pytest.approx(service["served_energy_kwh"], abs=1e-6)
    assert service["served_energy_kwh"] + service["final_unserved_energy_kwh"] == pytest.approx(service["requested_energy_kwh"], abs=1e-6)
    assert any(abs(value) > 1e-5 for row in physical for value in row["chargers"].values())


@pytest.mark.parametrize("physics_version", sorted(parity.REFERENCES))
def test_reference_covers_both_delivered_and_unserved_machine_requests(physics_version):
    cases = json.loads(parity.REFERENCES[physics_version].read_text())["cases"].values()
    service = [case["service"]["district"] for case in cases]
    assert any(row["served_energy_kwh"] > 0.0 for row in service)
    assert any(row["final_unserved_energy_kwh"] > 0.0 for row in service)


def test_physics_versions_have_distinct_references_for_the_same_inputs():
    # Both versions run the same schema and inputs, and version 2 changes the trajectories of every case, so a
    # refactor that alters the default physics cannot pass by matching the 3.6.0 reference.
    v1, v2 = (json.loads(parity.REFERENCES[version].read_text()) for version in (1, 2))
    assert v1["definition_version"] == v2["definition_version"] and v1["tolerances"] == v2["tolerances"]
    for name in parity.CASES:
        assert v1["cases"][name]["input_fingerprint"] == v2["cases"][name]["input_fingerprint"]
        assert not parity.compare(v1["cases"][name], v2["cases"][name])["matches"], name


@pytest.mark.parametrize("field,change", [
    ("storage_kwh", 0.001), ("cost_eur", 0.0001), ("storage_soc", 0.0001),
    ("served_cycles_count", 1), ("requested_power_kw", 0.01),
])
def test_numeric_changes_in_physics_cost_service_and_actions_are_detected(field, change):
    assert not parity.compare({field: 1.0}, {field: 1.0 + change})["matches"]


def test_unknown_zero_structure_order_and_tolerance_policy_are_distinct():
    assert not parity.compare({"coverage": None}, {"coverage": 0.0})["matches"]
    assert not parity.compare({"ids": ["A", "B"]}, {"ids": ["B", "A"]})["matches"]
    assert not parity.compare({"field": 1}, {})["matches"]
    assert not parity.compare({"available": True}, {"available": 1})["matches"]
    assert not parity.compare({"observed_count": 1}, {"observed_count": 1.00000001})["matches"]
    assert not parity.compare({"tolerances": {"atol": 1e-6}}, {"tolerances": {"atol": 1.00001e-6}})["matches"]
    assert parity.compare({"energy_kwh": 1.0}, {"energy_kwh": 1.0 + 1e-8})["matches"]


def test_missing_reference_fails_without_capturing_or_creating_one(tmp_path, monkeypatch):
    def unexpected_capture(*args):
        pytest.fail("Verification must load its reference before running/capturing candidates.")
    monkeypatch.setattr(parity, "capture", unexpected_capture)
    missing, output = tmp_path / "missing.json", tmp_path / "report.json"
    assert parity.main(["--reference", str(missing), "--physics-version", "1", "--output", str(output)]) == 1
    assert json.loads(output.read_text())["verification_passed"] is False
    assert not missing.exists()


def test_existing_reference_proposal_cannot_be_overwritten(tmp_path):
    path = tmp_path / "reference.json"
    path.write_text("original")
    with pytest.raises(SystemExit) as error:
        parity.main(["--capture-reference", str(path), "--physics-version", "2", "--output", str(tmp_path / "report.json")])
    assert error.value.code == 2 and path.read_text() == "original"
    with pytest.raises(SystemExit) as error:
        parity.main(["--reference", str(path), "--physics-version", "1",
                     "--output", str(path.parent / "sub/../reference.json")])
    assert error.value.code == 2 and path.read_text() == "original"


def test_a_reference_file_needs_exactly_one_physics_version(tmp_path):
    for flags in ([], ["--physics-version", "1", "--physics-version", "2"]):
        with pytest.raises(SystemExit) as error:
            parity.main(["--reference", str(parity.REFERENCES[1]), *flags, "--output", str(tmp_path / "report.json")])
        assert error.value.code == 2


@pytest.mark.parametrize("changed", sorted(parity.REFERENCES))
def test_cli_verifies_every_physics_version_and_fails_for_a_changed_trajectory(tmp_path, monkeypatch, changed):
    references = {version: json.loads(path.read_text()) for version, path in parity.REFERENCES.items()}
    captured = []

    def capture(directory, physics_version):
        captured.append(physics_version)
        actual = deepcopy(references[physics_version])
        if physics_version == changed:
            actual["cases"]["entity_900s"]["transitions"][0]["physical"]["Building_1"]["storage_kwh"] += 0.001
        return actual, {}

    monkeypatch.setattr(parity, "capture", capture)
    output = tmp_path / "report.json"
    assert parity.main(["--output", str(output)]) == 1
    assert captured == sorted(parity.REFERENCES)
    report = json.loads(output.read_text())
    assert not report["verification_passed"]
    for version, row in report["versions"].items():
        assert row["verification_passed"] is (int(version) != changed)
    comparison = report["versions"][str(changed)]["comparison"]
    assert comparison["difference_count"] == 1
    assert comparison["differences"][0]["path"].endswith("storage_kwh")
