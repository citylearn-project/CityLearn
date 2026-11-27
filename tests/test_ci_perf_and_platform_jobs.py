"""CI checks for performance (#468), Windows and the end-use load profile pipeline (#471)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


@pytest.fixture(scope="module")
def perf_smoke():
    spec = importlib.util.spec_from_file_location("perf_smoke_under_test", ROOT / "scripts/ci/perf_smoke.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _workflow(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def _triggers(workflow: dict) -> dict:
    # PyYAML reads the bare key `on` as True.
    return workflow.get("on", workflow.get(True))


def test_perf_baseline_records_every_case_and_no_thresholds(perf_smoke):
    baseline = json.loads((ROOT / "scripts/ci/perf_baseline.json").read_text(encoding="utf-8"))

    assert "thresholds" not in baseline
    assert set(baseline["cases"]) == set(perf_smoke.ALL_CASES)
    pt_rec = baseline["cases"]["pt_rec"]
    assert pt_rec["schema"] == "data/datasets/pt_rec_4/schema.json"
    assert pt_rec["time_step_ratio_mode"] == "reject"
    assert pt_rec["physics_invariant_checks"] is True
    assert pt_rec["seconds_per_time_step"] == 900
    construction = baseline["cases"]["construction_15s"]
    assert construction["seconds_per_time_step"] == 15
    assert construction["schema"].endswith("_15s_parquet/schema.json")


def test_perf_summary_shows_ratios_and_marks_one_case_that_changed(perf_smoke):
    baseline = {"cases": {
        "none": {"avg_step_ms": 10.0, "p95_step_ms": 12.0},
        "pt_rec": {"avg_step_ms": 10.0, "p95_step_ms": 12.0},
        "construction_15s": {"init_s": 10.0},
    }}
    report = {"cases": {
        "none": {"avg_step_ms": 10.0, "p95_step_ms": 12.0},
        "pt_rec": {"avg_step_ms": 12.5, "p95_step_ms": 12.0},
        "construction_15s": {"init_s": 10.0},
        "entity_none": {"avg_step_ms": 10.0, "p95_step_ms": 12.0},
    }}
    rows = perf_smoke._baseline_rows(report, baseline, 4.5, 15.0, 3.0, 5.0)
    summary = perf_smoke._summary_markdown(rows, baseline, perf_smoke.DEFAULT_BASELINE_FILE, [])

    pt_rec_row = next(line for line in summary.splitlines() if line.startswith("| pt_rec | avg_step_ms"))
    assert "1.25x" in pt_rec_row and "slower" in pt_rec_row
    assert "slower" not in next(line for line in summary.splitlines() if line.startswith("| none | avg_step_ms"))
    assert "| entity_none | avg_step_ms | missing |" in summary
    assert perf_smoke._missing_baselines(report, baseline) == ["entity_none"]


def test_perf_construction_time_is_gated_loosely(perf_smoke):
    baseline = {"cases": {"construction_15s": {"init_s": 10.0}}}
    within = {"cases": {"construction_15s": {"init_s": 34.0}}}
    over = {"cases": {"construction_15s": {"init_s": 36.0}}}

    assert perf_smoke._compare_to_baseline(within, baseline, 4.5, 15.0, 3.0, 5.0) == []
    errors = perf_smoke._compare_to_baseline(over, baseline, 4.5, 15.0, 3.0, 5.0)
    assert len(errors) == 1 and errors[0].startswith("construction_15s init_s regression")


def test_ci_perf_step_uses_the_script_thresholds_and_requires_the_baseline():
    steps = _workflow("run_tests.yml")["jobs"]["test"]["steps"]
    run = next(step["run"] for step in steps if "perf_smoke.py" in step.get("run", ""))

    assert "--require-baseline" in run
    for flag in ("--none-max-ms", "--end-max-ms", "--entity-max-ms", "--baseline-regression-ratio", "--baseline-slack-ms"):
        assert flag not in run


def test_windows_job_runs_the_windows_only_test_and_fails_when_it_skips():
    job = _workflow("run_tests.yml")["jobs"]["test-windows"]

    assert job["runs-on"] == "windows-2025"
    assert "strategy" not in job
    assert job["timeout-minutes"] <= 20
    run = next(step["run"] for step in job["steps"] if "python -m pytest" in step.get("run", ""))
    assert "tests/test_portable_pairing_evidence.py" in run
    assert "::error" in run and "SKIPPED" in run


def test_end_use_load_profile_job_runs_weekly_and_on_dispatch_only():
    workflow = _workflow("end_use_load_profiles.yml")

    assert set(_triggers(workflow)) == {"schedule", "workflow_dispatch"}
    steps = workflow["jobs"]["end-use-load-profiles"]["steps"]
    install = next(step["run"] for step in steps if "end_use_load_profiles]" in step.get("run", ""))
    assert "::error" in install and "GITHUB_STEP_SUMMARY" in install
    run = next(step["run"] for step in steps if "python -m pytest" in step.get("run", ""))
    assert "tests/test_end_use_load_profiles_pipeline.py" in run
    assert "tests/test_engineering_gaps.py" in run
    assert "::error" in run and "SKIPPED" in run
