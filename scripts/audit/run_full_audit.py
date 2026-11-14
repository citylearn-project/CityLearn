#!/usr/bin/env python3
"""Verify selected simulator audits; report-only and algorithm audits are explicit."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List


ROOT = Path(__file__).resolve().parents[2]
AUDIT_DIR = ROOT / "scripts" / "audit"
OUTPUT_DIR_DEFAULT = ROOT / "outputs" / "audit"
DEFAULT_AUDITS = ("physics", "entity_contract", "datasets", "refactor_parity")
AUDIT_COVERAGE = {
    "physics": "Physical units, power, SOC and energy across step durations and topology boundaries.",
    "entity_contract": "Entity IDs, features, relations and saved interface contracts.",
    "datasets": "Declared dataset schemas and bounded supported-interface rollouts.",
    "refactor_parity": "Fixed-command physical trajectories, service, cash, KPIs, interfaces and exports.",
    "performance_results": "Legacy performance and RBC/SAC result snapshots; opt-in only.",
}


def _utc_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None, microsecond=0).isoformat() + "Z"


def _run(cmd: List[str], cwd: Path) -> Dict[str, Any]:
    started = _utc_now_iso()
    result = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)
    ended = _utc_now_iso()

    return {
        "cmd": cmd,
        "returncode": int(result.returncode),
        "started_utc": started,
        "ended_utc": ended,
        "stdout": result.stdout[-20000:],
        "stderr": result.stderr[-20000:],
    }


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR_DEFAULT)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--strict", dest="strict", action="store_true", help="Verify all selected audits (the default).")
    mode.add_argument("--report-only", dest="strict", action="store_false", help="Collect diagnostics; return zero even when verification fails.")
    parser.set_defaults(strict=True)
    parser.add_argument("--audits", nargs="+", choices=tuple(AUDIT_COVERAGE), default=DEFAULT_AUDITS,
                        help="Audits to run. Algorithm/result comparisons are excluded by default.")
    parser.add_argument("--episode-steps", type=int, default=2000, help="Passed to perf/results audit where supported.")
    parser.add_argument("--seed", type=int, default=0, help="Passed to sub-audits where supported.")
    parser.add_argument("--update-snapshots", action="store_true", help="Update contract/KPI baselines in snapshot-aware audits.")
    args = parser.parse_args(argv)
    if args.update_snapshots and args.strict:
        parser.error("Snapshot updates require --report-only; verification must not rewrite its references.")
    args.output_dir = args.output_dir.expanduser().resolve()
    return args


def main(argv=None) -> int:
    args = parse_args(argv)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    audit_scripts = [
        {
            "name": "physics",
            "path": AUDIT_DIR / "audit_physics.py",
            "extra_args": [
                "--output",
                str(args.output_dir / "physics_audit.json"),
            ],
        },
        {
            "name": "entity_contract",
            "path": AUDIT_DIR / "audit_entity_contract.py",
            "extra_args": [
                "--output-dir",
                str(args.output_dir),
                "--strict",
            ] + (["--update-snapshots"] if args.update_snapshots else []),
        },
        {
            "name": "datasets",
            "path": AUDIT_DIR / "audit_datasets.py",
            "extra_args": [
                "--output",
                str(args.output_dir / "datasets_audit.json"),
                "--offline",
                "--max-steps", "8",
            ],
        },
        {
            "name": "refactor_parity",
            "path": AUDIT_DIR / "audit_refactor_parity.py",
            "extra_args": ["--output", str(args.output_dir / "refactor_parity.json")],
        },
        {
            "name": "performance_results",
            "path": AUDIT_DIR / "audit_performance_results.py",
            "extra_args": [
                "--output",
                str(args.output_dir / "performance_results_audit.json"),
                "--episode-steps",
                str(args.episode_steps),
                "--seed",
                str(args.seed),
                "--strict",
            ] + (["--update-baselines"] if args.update_snapshots else []),
        },
    ]

    runs: List[Dict[str, Any]] = []
    hard_fail = False
    selected = set(args.audits)
    for item in audit_scripts:
        if item["name"] not in selected:
            continue
        script_path: Path = item["path"]
        if not script_path.is_file():
            runs.append(
                {
                    "name": item["name"],
                    "status": "missing",
                    "path": str(script_path.relative_to(ROOT)),
                }
            )
            hard_fail = True
            continue

        cmd = [sys.executable, str(script_path), *item["extra_args"]]
        try:
            run = _run(cmd, ROOT)
        except OSError as error:
            run = {"cmd": cmd, "returncode": None, "error": str(error)}
        run["name"] = item["name"]
        run["path"] = str(script_path.relative_to(ROOT))

        if run["returncode"] == 0:
            run["status"] = "ok"
        elif run["returncode"] == 2:
            run["status"] = "skipped_deps"
            hard_fail = True
        else:
            run["status"] = "failed"
            hard_fail = True

        runs.append(run)

    summary = {
        "generated_utc": _utc_now_iso(),
        "python": sys.version,
        "strict": bool(args.strict),
        "mode": "verify" if args.strict else "report_only",
        "verification_passed": not hard_fail and not args.update_snapshots,
        "coverage": {name: AUDIT_COVERAGE[name] for name in AUDIT_COVERAGE if name in selected},
        "scope": "Selected audits only; not the full pytest suite or empirical calibration.",
        "default_audits_selected": set(DEFAULT_AUDITS).issubset(selected),
        "snapshot_updates_requested": bool(args.update_snapshots),
        "output_dir": str(args.output_dir),
        "runs": runs,
    }
    summary_path = args.output_dir / "full_audit_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2))

    print(f"[audit] wrote summary: {summary_path}")
    for run in runs:
        print(f"[audit] {run['name']}: {run['status']}")

    if args.strict and hard_fail:
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
