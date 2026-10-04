from __future__ import annotations

import hashlib

from scaffold.runners import method_freeze


def classify():
    manifest = method_freeze.load_manifest().get("files", {})
    rows = []
    for relative in method_freeze.METHOD_FILES:
        raw = (method_freeze.PROJECT_DIR / relative).read_bytes()
        normalized = raw.replace(b"\r\n", b"\n")
        expected = manifest.get(relative)
        raw_digest = hashlib.sha256(raw).hexdigest()
        normalized_digest = hashlib.sha256(normalized).hexdigest()
        if raw_digest == expected:
            verdict = "match"
        elif normalized_digest == expected:
            verdict = "line_endings_only"
        else:
            verdict = "content_changed"
        rows.append({
            "file": relative,
            "verdict": verdict,
            "crlf_lines": raw.count(b"\r\n"),
            "lf_lines": normalized.count(b"\n"),
        })
    return rows


def main():
    rows = classify()
    width = max(len(row["verdict"]) for row in rows)
    for row in rows:
        print(
            f"{row['verdict']:<{width}}  "
            f"crlf={row['crlf_lines']:>4}/{row['lf_lines']:<4}  {row['file']}"
        )
    content = [row["file"] for row in rows if row["verdict"] == "content_changed"]
    churn = [row["file"] for row in rows if row["verdict"] == "line_endings_only"]
    print()
    print(f"content_changed: {len(content)}")
    for item in content:
        print(f"  {item}")
    print(f"line_endings_only: {len(churn)}")
    for item in churn:
        print(f"  {item}")
    return 1 if content else 0


if __name__ == "__main__":
    raise SystemExit(main())
