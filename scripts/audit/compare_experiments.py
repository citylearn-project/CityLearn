#!/usr/bin/env python3
"""Compare V2 exports with versioned pairing evidence and visible service/inventory."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from citylearn.internal.comparison import compare_exports


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--left', type=Path, required=True)
    parser.add_argument('--right', type=Path, required=True)
    parser.add_argument('--mode', choices=['controller', 'sharing'], default='controller')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = compare_exports(args.left, args.right, args.mode)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')
    print(json.dumps({k: report[k] for k in ('status', 'permitted_claim', 'mismatches', 'missing_evidence')}))
    return 0 if report['status'] == 'paired' else 2


if __name__ == '__main__':
    sys.exit(main())
