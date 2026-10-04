from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from scaffold.statewise.evaluation import case_schema


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "dataset_design" / "artifacts" / "paper_heldout_materialization_v1"
REGISTRY = PACKAGE / "materialization_registry.json"
ANNOTATIONS = PACKAGE / "annotations" / "canary_annotator_a" / "records.jsonl"
OUTPUT = PACKAGE / "canary_seal_manifest.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def main() -> int:
    registry_doc = json.loads(REGISTRY.read_text(encoding="utf-8"))
    records = [item for item in registry_doc["cases"] if item["selection_role"] == "infrastructure_canary"]
    annotations = [json.loads(line) for line in ANNOTATIONS.read_text(encoding="utf-8").splitlines() if line.strip()]
    by_slot = {item["slot_id"]: item for item in annotations}
    errors: list[str] = []
    sealed_cases = []

    if len(records) != 10:
        errors.append(f"expected 10 registry canaries, found {len(records)}")
    if len(annotations) != 10 or len(by_slot) != 10:
        errors.append(f"expected 10 unique Annotator-A rows, found {len(annotations)}/{len(by_slot)}")

    domain_counts = Counter(item["operational_domain"] for item in records)
    if sorted(domain_counts.values()) != [2, 2, 2, 2, 2]:
        errors.append(f"expected 2 canaries per domain, found {dict(domain_counts)}")

    for record in sorted(records, key=lambda item: item["slot_id"]):
        slot = record["slot_id"]
        if record["materialization_status"] != "MATERIALIZED_CANARY":
            errors.append(f"{slot}: not materialized")
            continue
        matches = list((PACKAGE / "cases").rglob(f"{record['case_id']}.json"))
        if len(matches) != 1:
            errors.append(f"{slot}: expected one case file, found {len(matches)}")
            continue
        case_path = matches[0]
        actual_hash = _sha256(case_path)
        if actual_hash != record["case_sha256"]:
            errors.append(f"{slot}: registry/case hash mismatch")
        case = json.loads(case_path.read_text(encoding="utf-8"))
        schema_errors = case_schema.validate_case(case)
        if schema_errors:
            errors.append(f"{slot}: schema errors {schema_errors}")
        annotation = by_slot.get(slot)
        if annotation is None:
            errors.append(f"{slot}: missing Annotator-A row")
        elif annotation.get("case_sha256") != actual_hash:
            errors.append(f"{slot}: annotation/case hash mismatch")
        elif annotation.get("annotation_status") != "COMPLETE":
            errors.append(f"{slot}: Annotator-A incomplete")
        sealed_cases.append({
            "slot_id": slot,
            "case_id": record["case_id"],
            "domain": record["operational_domain"],
            "case_path": case_path.relative_to(ROOT).as_posix(),
            "case_sha256": actual_hash,
            "fixture_sha256": record["fixture_sha256"],
            "oracle_sha256": record["oracle_sha256"],
            "annotation_a_status": record["annotation_a_status"],
            "headline_eligible": False,
        })

    closure_files = sorted((PACKAGE / "closure").glob("canary_wave*_closure.json"))
    closure_docs = [json.loads(path.read_text(encoding="utf-8")) for path in closure_files]
    if sum(doc.get("case_count", 0) for doc in closure_docs) != 10:
        errors.append("closure manifests do not cover exactly 10 cases")
    if not all(doc.get("all_valid") is True for doc in closure_docs):
        errors.append("one or more closure manifests are invalid")

    if errors:
        raise ValueError("canary seal failed:\n- " + "\n- ".join(errors))

    manifest = {
        "schema_version": "swe-statebench-canary-seal-v1",
        "status": "SEALED_INFRASTRUCTURE_CANARY_ONLY",
        "selection_manifest_sha256": _sha256(PACKAGE / "selection_manifest.json"),
        "registry_sha256": _sha256(REGISTRY),
        "annotator_a_package_sha256": _sha256(ANNOTATIONS),
        "runtime_sources": {
            "lightweight_runtime_sha256": _sha256(ROOT / "scaffold/statewise/runtime/lightweight_runtime.py"),
            "structured_mutation_runtime_sha256": _sha256(ROOT / "scaffold/statewise/runtime/structured_mutation_runtime.py"),
        },
        "closure_manifests": [{"path": path.relative_to(ROOT).as_posix(), "sha256": _sha256(path)} for path in closure_files],
        "case_count": len(sealed_cases),
        "domain_counts": dict(sorted(domain_counts.items())),
        "rules": [
            "never include canary trajectories in headline statistics",
            "do not replace a frozen headline slot using canary outcomes",
            "canary repository reuse is declared and does not satisfy headline pinned-commit requirements",
        ],
        "cases": sealed_cases,
    }
    _write_json(OUTPUT, manifest)
    print(json.dumps({"status": manifest["status"], "sealed": len(sealed_cases), "domain_counts": manifest["domain_counts"], "manifest": str(OUTPUT)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
