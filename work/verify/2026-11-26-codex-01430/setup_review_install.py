"""Reuse the reviewed local migration, with only its target version changed."""
from pathlib import Path

previous = Path(__file__).resolve().parents[1] / "2026-11-26-codex-01429/setup_review_install.py"
source = previous.read_text(encoding="utf-8")
assert source.count('VERSION = "0.14.29"') == 1
source = source.replace('VERSION = "0.14.29"', 'VERSION = "0.14.30"')
exec(compile(source, str(previous), "exec"), {"__name__": "__main__"})
