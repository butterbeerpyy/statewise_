from pathlib import Path
import argparse
from export_paper_xlsx import export

MAIN = Path('runs/formal_v9_rq1_rq3_main150_gpt56sol_20260812_r1')
RQ2 = Path('runs/formal_v9_rq2_baselines150_gpt56sol_20260813_r1')

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--main", type=Path, default=MAIN)
    p.add_argument("--run", type=Path, default=RQ2)
    p.add_argument("--recovery", action="append", type=Path, default=[])
    p.add_argument("--output", type=Path, default=Path('paper_experiments/results/rq2/rq2_results.xlsx'))
    a = p.parse_args()
    export([a.main, a.run], a.output, replacement_paths=a.recovery)
    print(a.output.resolve())

if __name__ == "__main__":
    main()
