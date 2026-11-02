#!/usr/bin/env python3
"""Inspect equity differences with the same pairing gate as general comparisons."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import pandas as pd
from citylearn.internal.comparison import compare_exports


def resolve(path):
    return path/'exported_kpis.csv' if path.is_dir() else path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-a',type=Path,required=True)
    parser.add_argument('--run-b',type=Path,required=True)
    parser.add_argument('--mode',choices=['controller','sharing'],default='controller')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    report=compare_exports(resolve(args.run_a),resolve(args.run_b),args.mode)
    rows=[dict(cost_function=r['kpi'],run_a=r['left'],run_b=r['right'],
               delta_absolute_b_minus_a=r['delta_right_minus_left'],pairing_status=report['status'])
          for r in report['kpis'] if r['name']=='District' and 'equity_' in r['kpi']]
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        pd.DataFrame(rows).to_csv(args.output,index=False)
        args.output.with_suffix('.comparison.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    print(json.dumps(dict(status=report['status'],mismatches=report['mismatches'],
                          missing_evidence=report['missing_evidence'],equity_differences=rows),indent=2))
    # Equity directions require their own scientific interpretation. Even paired
    # inputs do not make every ratio universally higher-is-better.
    return 0 if report['status']=='paired' else 2


if __name__=='__main__':
    sys.exit(main())
