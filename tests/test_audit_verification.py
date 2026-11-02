"""Mandatory audit failures propagate through the actual command-line runner."""

import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
NAMES = ("physics", "entity_contract", "datasets", "refactor_parity")


def _run(tmp_path, *, failure=None, code=1, missing=None, flags=()):
    checkout = tmp_path / "checkout"
    scripts = checkout / "scripts/audit"
    scripts.mkdir(parents=True)
    for name in NAMES:
        if name == missing:
            continue
        result = code if name == failure else 0
        (scripts / f"audit_{name}.py").write_text(
            "import json, os, sys\n"
            "print(json.dumps({'cwd': os.getcwd(), 'args': sys.argv[1:]}))\n"
            f"raise SystemExit({result})\n"
        )
    program = (
        "import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); "
        "import scripts.audit.run_full_audit as runner; "
        "runner.ROOT = Path(sys.argv[2]); runner.AUDIT_DIR = runner.ROOT/'scripts/audit'; "
        "raise SystemExit(runner.main(sys.argv[3:]))"
    )
    process = subprocess.run(
        [sys.executable, "-c", program, str(ROOT), str(checkout), "--output-dir", "evidence", *flags],
        cwd=tmp_path, text=True, capture_output=True,
    )
    path = tmp_path / "evidence/full_audit_summary.json"
    return process, json.loads(path.read_text()) if path.exists() else None


@pytest.mark.parametrize("name", NAMES)
def test_default_verification_fails_for_each_required_child(tmp_path, name):
    process, report = _run(tmp_path, failure=name)
    assert process.returncode == 1
    assert report["verification_passed"] is False
    assert report["mode"] == "verify"
    assert {row["name"] for row in report["runs"] if row["status"] == "failed"} == {name}
    assert len(report["runs"]) == 4  # Remaining diagnostics are still collected.


def test_missing_dependencies_are_not_a_successful_verification(tmp_path):
    process, report = _run(tmp_path, failure="physics", code=2)
    assert process.returncode == 1
    assert not report["verification_passed"]
    assert report["runs"][0]["returncode"] == 2


def test_missing_auditor_blocks_verification(tmp_path):
    process, report = _run(tmp_path, missing="datasets")
    assert process.returncode == 1
    assert not report["verification_passed"]
    assert next(row for row in report["runs"] if row["name"] == "datasets")["status"] == "missing"


def test_report_only_is_explicit_and_does_not_claim_to_pass(tmp_path):
    process, report = _run(tmp_path, failure="physics", flags=("--report-only",))
    assert process.returncode == 0
    assert report["mode"] == "report_only"
    assert not report["verification_passed"]


def test_successful_gate_resolves_outputs_from_callers_directory(tmp_path):
    process, report = _run(tmp_path)
    assert process.returncode == 0
    assert report["verification_passed"]
    assert report["default_audits_selected"]
    assert set(report["coverage"]) == set(NAMES)
    assert "performance_results" not in report["coverage"]
    for row in report["runs"]:
        child = json.loads(row["stdout"])
        assert child["cwd"] == str(tmp_path / "checkout")
        args = child["args"]
        option = "--output-dir" if row["name"] == "entity_contract" else "--output"
        assert Path(args[args.index(option) + 1]).is_absolute()
        assert str(tmp_path / "evidence") in args[args.index(option) + 1]


def test_strict_alias_and_selected_scope_remain_explicit(tmp_path):
    process, report = _run(tmp_path, flags=("--strict", "--audits", "datasets"))
    assert process.returncode == 0
    assert report["strict"] and report["verification_passed"]
    assert list(report["coverage"]) == ["datasets"]
    assert not report["default_audits_selected"]


def test_verification_cannot_update_its_own_references(tmp_path):
    process, report = _run(tmp_path, flags=("--strict", "--update-snapshots"))
    assert process.returncode == 2
    assert "require --report-only" in process.stderr
    assert report is None


def test_explicit_snapshot_updates_cannot_be_reported_as_verified(tmp_path):
    process, report = _run(tmp_path, flags=("--report-only", "--update-snapshots"))
    assert process.returncode == 0
    assert report["snapshot_updates_requested"]
    assert not report["verification_passed"]
