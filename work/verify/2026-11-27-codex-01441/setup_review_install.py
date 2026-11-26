"""Record migration baseline, then reuse the reviewed versioned installation migration."""
import hashlib
import json
import os
from pathlib import Path

home = Path(os.environ["LOCALAPPDATA"]) / "scholar-search"
evidence = home / "verification/2026-11-27-codex-0.14.41-p5"
evidence.mkdir(parents=True, exist_ok=True)
baseline = evidence / "installation-baseline.json"
assert not baseline.exists(), "Do not overwrite the pre-migration baseline"
states = []
for path in [home / "state/quota.json", home / "state/cooldown.json",
             home / "browser-state/state/quota.json", home / "browser-state/state/cooldown.json"]:
    row = {"path": str(path), "exists": path.is_file()}
    if path.is_file():
        payload = path.read_bytes()
        row["sha256"] = hashlib.sha256(payload).hexdigest()
        data = json.loads(payload.decode("utf-8-sig"))
        row["state"] = {k: data.get(k) for k in ["day", "used", "until", "cooldown_until"] if k in data}
    states.append(row)
baseline.write_text(json.dumps(states, ensure_ascii=False, indent=2), encoding="utf-8")

previous = Path(__file__).resolve().parents[1] / "2026-11-26-codex-01429/setup_review_install.py"
source = previous.read_text(encoding="utf-8")
assert source.count('VERSION = "0.14.29"') == 1
source = source.replace('VERSION = "0.14.29"', 'VERSION = "0.14.41"')
exec(compile(source, str(previous), "exec"), {"__name__": "__main__"})
