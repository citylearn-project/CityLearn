#!/usr/bin/env python3
"""Benchmark single- and multi-episode CityLearnEnv construction and BAU evaluation."""

from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Dict, List

import numpy as np

ROOT = Path(__file__).resolve().parents[2]


def _peak_rss_mib() -> float:
    """Return process peak resident set size in MiB on Linux, macOS, or Windows."""
    if sys.platform == "win32":
        class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
        get_current_process = ctypes.windll.kernel32.GetCurrentProcess
        get_current_process.restype = wintypes.HANDLE
        get_mem_info = ctypes.windll.psapi.GetProcessMemoryInfo
        get_mem_info.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESS_MEMORY_COUNTERS), wintypes.DWORD]
        get_mem_info.restype = wintypes.BOOL
        handle = get_current_process()
        if get_mem_info(handle, ctypes.byref(counters), counters.cb):
            return float(counters.PeakWorkingSetSize) / (1024.0 * 1024.0)
        return 0.0

    import resource

    ru = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == "darwin":
        return float(ru) / (1024.0 * 1024.0)
    return float(ru) / 1024.0


def _run_worker(
    dataset: str,
    episode_steps: int,
    episodes: int,
    include_bau: bool,
    seed: int,
    random_split: bool = False,
) -> Dict[str, Any]:
    from citylearn.citylearn import CityLearnEnv

    t0 = time.perf_counter()
    env = CityLearnEnv(
        dataset,
        central_agent=True,
        episode_time_steps=episode_steps,
        rolling_episode_split=(episodes > 1 and not random_split),
        random_episode_split=random_split,
        random_seed=seed,
        offline=True,
        render_mode="none",
    )
    t_init = time.perf_counter() - t0

    step_total = 0.0
    eval_total = 0.0
    net_sum = 0.0
    kpi_rows = 0

    for ep in range(episodes):
        s0 = time.perf_counter()
        env.reset(seed=seed + ep)
        zeros = [np.zeros(len(names), dtype="float32").tolist() for names in env.action_names]
        while not (env.terminated or env.truncated):
            env.step(zeros)
        step_total += time.perf_counter() - s0

        e0 = time.perf_counter()
        kpis = env.evaluate_v2(include_business_as_usual=include_bau)
        eval_total += time.perf_counter() - e0
        kpi_rows = int(len(kpis))
        net_sum += float(np.sum(env.net_electricity_consumption))

    total_s = time.perf_counter() - t0
    peak_mib = _peak_rss_mib()
    env.close()
    return {
        "dataset": dataset,
        "episode_steps": episode_steps,
        "episodes": episodes,
        "bau": include_bau,
        "init_s": round(t_init, 3),
        "rollout_s": round(step_total, 3),
        "eval_s": round(eval_total, 3),
        "total_s": round(total_s, 3),
        "peak_rss_mib": round(peak_mib, 1),
        "kpi_rows": kpi_rows,
        "net_kwh_sum": round(net_sum, 6),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        default="citylearn_three_phase_electrical_service_demo_15s_parquet",
        help="Bundled dataset name or schema.json path.",
    )
    parser.add_argument("--episode-steps", type=int, default=240, help="Steps per episode (default: 240).")
    parser.add_argument(
        "--episodes",
        nargs="+",
        type=int,
        default=[1, 5],
        help="Episode counts per environment instance (default: 1 5).",
    )
    parser.add_argument(
        "--bau",
        choices=["off", "on", "both"],
        default="both",
        help="Whether to evaluate with include_business_as_usual False, True, or both.",
    )
    parser.add_argument("--repeats", type=int, default=2, help="Fresh-process repeats per case (default: 2).")
    parser.add_argument("--seed", type=int, default=0, help="Base random seed (default: 0).")
    parser.add_argument(
        "--random-episode-split",
        action="store_true",
        help="Sample episode windows across the loaded horizon with random_episode_split=True.",
    )
    parser.add_argument("--label", default=None, help="Optional label attached to each JSON output line.")
    parser.add_argument(
        "--pythonpath",
        default=None,
        help="Optional CityLearn source root prepended to PYTHONPATH for worker subprocesses.",
    )
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--worker-episodes", type=int, default=1, help=argparse.SUPPRESS)
    parser.add_argument("--worker-bau", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.worker:
        worker_root = str(Path(args.pythonpath).resolve()) if args.pythonpath else str(ROOT)
        if worker_root not in sys.path:
            sys.path.insert(0, worker_root)
        result = _run_worker(
            dataset=args.dataset,
            episode_steps=args.episode_steps,
            episodes=args.worker_episodes,
            include_bau=args.worker_bau,
            seed=args.seed,
            random_split=args.random_episode_split,
        )
        print(json.dumps(result))
        return

    bau_modes: List[bool] = (
        [False] if args.bau == "off" else ([True] if args.bau == "on" else [False, True])
    )
    target_root = str(Path(args.pythonpath).resolve()) if args.pythonpath else str(ROOT)
    env_vars = os.environ.copy()
    env_vars["PYTHONPATH"] = target_root

    for episodes in args.episodes:
        for include_bau in bau_modes:
            for run_idx in range(1, args.repeats + 1):
                cmd = [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    "--worker",
                    "--pythonpath",
                    target_root,
                    "--dataset",
                    args.dataset,
                    "--episode-steps",
                    str(args.episode_steps),
                    "--worker-episodes",
                    str(episodes),
                    "--seed",
                    str(args.seed),
                ]
                if args.random_episode_split:
                    cmd.append("--random-episode-split")
                if include_bau:
                    cmd.append("--worker-bau")
                proc = subprocess.run(cmd, capture_output=True, text=True, env=env_vars, check=True)
                lines = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]
                payload = json.loads(lines[-1])
                if args.label is not None:
                    payload["label"] = args.label
                payload["run"] = run_idx
                print(json.dumps(payload), flush=True)


if __name__ == "__main__":
    main()
