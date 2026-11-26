"""Reuse the reviewed migration for 0.14.34; no product implementation edits."""
from pathlib import Path
import os

previous = Path(__file__).resolve().parents[1] / "2026-11-26-codex-01429/setup_review_install.py"
source = previous.read_text(encoding="utf-8")
assert source.count('VERSION = "0.14.29"') == 1
source = source.replace('VERSION = "0.14.29"', 'VERSION = "0.14.34"')
exec(compile(source, str(previous), "exec"), {"__name__": "__main__"})

# Installing a local tarball caused pnpm to add an exception for the previous registry version.
# Restore only that exact addition, after checking against our pre-install backup.
root = Path(os.environ["LOCALAPPDATA"]) / "scholar-search/installations/0.14.34"
backups = list((root / "bundle-profile-backup").glob("*/pnpm-workspace.yaml"))
assert len(backups) == 1
policy = Path("D:/DSH/.dsh/profiles/desktop/pnpm-workspace.yaml")
before = backups[0].read_text(encoding="utf-8")
current = policy.read_text(encoding="utf-8")
assert current.replace(" || 0.14.33'", "'", 1) == before
policy.write_text(before, encoding="utf-8", newline="")
print("restored only pnpm-added release-age exception")
