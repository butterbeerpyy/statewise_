from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path


DEFAULT_SNAPSHOT = Path(
    'scaffold\\experiments'
    r"\w1_contract_corrected_v9\snapshot.json"
)


def _compact(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument(
        "--output-dir", type=Path,
        default=Path('paper_experiments/results/shared/annotation_b_v9'),
    )
    args = parser.parse_args()
    snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
    cases_root = args.snapshot.parent / "cases"
    blinded, private = [], []
    for index, entry in enumerate(snapshot["cases"], start=1):
        case = json.loads((cases_root / entry["file"]).read_text(encoding="utf-8"))
        memories = [{
            "memory_id": case.get("memory_id"),
            "key": case.get("memory_key"),
            "value": (case.get("corrupted_state") or {}).get("value"),
            "text": (case.get("corrupted_state") or {}).get("text"),
            "metadata": case.get("state_metadata"),
        }, *(case.get("context_memories") or [])]
        blinded.append({
            "item_id": f"B{index:03d}",
            "case_id": case["case_id"],
            "domain": case.get("domain"),
            "task": case.get("task"),
            "environment_scope": _compact((case.get("environment") or {}).get("scope")),
            "environment_evidence": _compact((case.get("environment") or {}).get("evidence")),
            "candidate_memories": _compact(memories),
            "observable_fixture": _compact((case.get("execution") or {}).get("fixture")),
            "b_expected_behavior_SHOULD_ACT_or_SHOULD_STOP": "",
            "b_support_memory_ids_semicolon_separated": "",
            "b_correct_state_value_json": "",
            "b_safety_invariant": "",
            "b_notes": "",
        })
        oracle = (case.get("execution") or {}).get("oracle") or {}
        private.append({
            "item_id": f"B{index:03d}",
            "case_id": case["case_id"],
            "a_expected_behavior": (
                "SHOULD_STOP" if oracle.get("safe_terminal_actions")
                or oracle.get("safe_terminal_outcome") else "SHOULD_ACT"
            ),
            "a_support_memory_ids": ";".join(sorted(
                str(item.get("memory_id"))
                for item in case.get("oracle_support_states") or []
                if item.get("memory_id")
            )),
            "a_correct_state_value_json": _compact(
                (case.get("correct_state") or {}).get("value")
            ),
            "a_safety_invariant": (case.get("safety") or {}).get("invariant"),
        })
    args.output_dir.mkdir(parents=True, exist_ok=True)
    packet = args.output_dir / "ANNOTATOR_B_BLINDED.csv"
    key = args.output_dir / "ANNOTATION_A_PRIVATE_KEY.csv"
    _write_csv(packet, blinded)
    _write_csv(key, private)
    readme = args.output_dir / "README.md"
    readme.write_text(
        "# Final-150 v9 independent annotation B\n\n"
        "Give only `ANNOTATOR_B_BLINDED.csv` to annotator B. The private key "
        "contains annotation A and must remain hidden until B submits a locked "
        "file. Do not edit case files from this workflow. Blank B fields mean "
        "unannotated, not disagreement. Agreement is not computable until all "
        "required B fields are completed.\n",
        encoding="utf-8",
    )
    report = {
        "snapshot_id": snapshot.get("snapshot_id"),
        "snapshot_sha256": hashlib.sha256(args.snapshot.read_bytes()).hexdigest(),
        "items": len(blinded),
        "blinded_packet": str(packet.resolve()),
        "private_key": str(key.resolve()),
        "annotation_b_status": "NOT_STARTED",
        "agreement": "NOT_COMPUTABLE",
    }
    (args.output_dir / "packet_manifest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
