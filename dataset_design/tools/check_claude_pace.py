import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
RUN = ROOT / "runs" / "rq5_longitudinal" / "rq5v2_method_claude_temp1"

manifest = json.loads((RUN / "manifest.json").read_text(encoding="utf-8"))
episodes = manifest.get("episodes") or {}
episodes = list(episodes.values()) if isinstance(episodes, dict) else episodes

done, running = [], 0
for ep in episodes:
    if not isinstance(ep, dict):
        continue
    if ep.get("status") == "SUCCEEDED":
        for attempt in ep.get("attempts") or []:
            if attempt.get("wall_seconds"):
                done.append(attempt["wall_seconds"])
    elif ep.get("attempts"):
        running += 1

print(f"episodes total={len(episodes)} succeeded={len(done)} in_flight={running}")
print(f"created={manifest.get('created_at')} updated={manifest.get('updated_at')}")
if done:
    avg = sum(done) / len(done)
    print(f"avg episode wall={avg:.1f}s  observed={[round(d) for d in done]}")
    print(f"projected 40 sequences serial = {avg * 40 / 3600:.1f} hours")
else:
    print("no completed episode yet -- cannot project")
