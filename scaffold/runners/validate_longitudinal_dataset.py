import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scaffold.statewise.evaluation.longitudinal_schema import load_dataset, validate_dataset

parser = argparse.ArgumentParser()
parser.add_argument("dataset", type=Path)
parser.add_argument(
    "--expect-sequences",
    type=int,
    default=None,
    help="assert the frozen sequence count (omit to only require a balanced dataset)",
)
args = parser.parse_args()
report = validate_dataset(
    load_dataset(args.dataset), expected_sequences=args.expect_sequences
)
print(json.dumps(report, ensure_ascii=False, indent=2))
raise SystemExit(0 if report["valid"] else 1)
