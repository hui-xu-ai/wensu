#!/usr/bin/env python
"""One command that answers "is this tree safe to release?".

Run before tagging. Every step is something that has actually gone wrong here, so
none of them is ceremony:

- versions      four artefacts, one number; a release that bumps only some of them
                leaves users unable to tell whether their pieces belong together
- changelog     a version with no entry is a release nobody can look up later
- tests/lint    the ordinary gates
- plans         kernel and host each validate plans from their own copy of the
                rules; drift only surfaces after an extension reload and spent quota
- artifacts     a wheel that omits channels or schemas breaks only after install

Usage:  python scripts/release-check.py [--skip-slow]
Exit code 0 means every gate passed.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(cmd: list[str], *, cwd: Path = ROOT) -> tuple[bool, str]:
    # encoding must be explicit: on Windows text=True decodes with the ANSI codepage,
    # and the first Chinese character in ruff or pytest output kills the reader thread.
    result = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output = ((result.stdout or "") + (result.stderr or "")).strip()
    return result.returncode == 0, output


def _python() -> str:
    candidate = ROOT / ".venv" / "Scripts" / "python.exe"
    if candidate.exists():
        return str(candidate)
    return sys.executable


def check_versions() -> tuple[bool, str]:
    ok, output = _run([_python(), str(ROOT / "scripts" / "check-versions.py")])
    last = output.splitlines()[-1] if output else ""
    return ok, last


def check_changelog() -> tuple[bool, str]:
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    version = re.search(
        r'^version = "([^"]+)"',
        (ROOT / "pyproject.toml").read_text(encoding="utf-8"),
        re.M,
    )
    if version is None:
        return False, "cannot read version from pyproject.toml"
    wanted = version.group(1)
    if f"## [{wanted}]" not in text:
        return False, f"CHANGELOG has no '## [{wanted}]' entry"
    return True, f"entry present for {wanted}"


def check_tests() -> tuple[bool, str]:
    ok, output = _run([_python(), "-m", "pytest", "-q", "-p", "no:cacheprovider"])
    tail = [line for line in output.splitlines() if "passed" in line or "failed" in line]
    return ok, tail[-1] if tail else output.splitlines()[-1]


def check_lint() -> tuple[bool, str]:
    ruff = ROOT / ".venv" / "Scripts" / "ruff.exe"
    # --no-cache: a cache directory inside the repo is both untidy and, on Windows,
    # occasionally unwritable mid-run.
    ok, output = _run([str(ruff), "check", "--no-cache", "src", "tests", "scripts"])
    return ok, output.splitlines()[-1] if output else ""


def check_format() -> tuple[bool, str]:
    """`ruff format --check`, not only `ruff check`.

    AGENTS.md requires formatting and the gate only ran the linter, so the tree could
    be lint-clean and still fail `ruff format --check` — which an independent review
    found it was, on fifteen files.
    """

    ruff = ROOT / ".venv" / "Scripts" / "ruff.exe"
    ok, output = _run(
        [str(ruff), "format", "--check", "--no-cache", "src", "tests", "scripts"]
    )
    return ok, output.splitlines()[-1] if output else ""


def check_assets() -> tuple[bool, str]:
    """Every file the extension manifest references is inside the wheel.

    A hand-kept force-include list dropped `content/capture.js` and nothing noticed
    until a clean install produced an extension the browser could not load. The
    script walks the manifest instead of trusting that list.

    Builds into a temporary directory rather than looking in `dist/`: the repo's own
    `dist/` is not always writable here, and a stale wheel left over from an earlier
    version would be the one checked.
    """

    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        ok, output = _run([str(Path("uv")), "build", "--out-dir", tmp])
        if not ok:
            return False, output.splitlines()[-1] if output else "build failed"
        ok, output = _run(
            [_python(), str(ROOT / "scripts" / "check-assets.py"), tmp]
        )
    return ok, output.splitlines()[-1] if output else ""


def check_types() -> tuple[bool, str]:
    import tempfile

    mypy = ROOT / ".venv" / "Scripts" / "mypy.exe"
    with tempfile.TemporaryDirectory() as cache:
        ok, output = _run([str(mypy), "--cache-dir", cache, "src"])
    return ok, output.splitlines()[-1] if output else ""


def check_plans() -> tuple[bool, str]:
    ok, output = _run([_python(), str(ROOT / "scripts" / "check-plan.py")])
    return ok, output.splitlines()[-1] if output else ""


def check_artifacts() -> tuple[bool, str]:
    """A wheel that forgets channels/ or schemas/ fails only after installation."""

    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        ok, output = _run([str(Path("uv")), "build", "--out-dir", tmp])
        if not ok:
            return False, output.splitlines()[-1] if output else "build failed"
        wheels = sorted(Path(tmp).glob("*.whl"))
        if not wheels:
            return False, "no wheel produced"
        names = zipfile.ZipFile(wheels[0]).namelist()
    required = ("scholar_search/channels/cnki/manifest.json",
                "scholar_search/channels/webofscience/manifest.json")
    missing = [name for name in required if name not in names]
    if missing:
        return False, f"wheel is missing {', '.join(missing)}"
    return True, f"{wheels[0].name}: {len(names)} files, both channels present"


CHECKS = [
    ("versions", "four artefacts share one number", check_versions),
    ("changelog", "the version being released is documented", check_changelog),
    ("tests", "offline suite", check_tests),
    ("lint", "ruff check", check_lint),
    ("format", "ruff format --check", check_format),
    ("types", "mypy", check_types),
    ("plans", "every channel plan passes kernel and host validation", check_plans),
    ("assets", "the wheel holds every file the extension loads", check_assets),
    ("artifacts", "wheel carries both channels", check_artifacts),
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-slow", action="store_true", help="skip tests and build")
    args = parser.parse_args()

    failures = 0
    width = max(len(name) for name, _, _ in CHECKS)
    for name, why, fn in CHECKS:
        if args.skip_slow and name in {"tests", "artifacts"}:
            print(f"  {name:<{width}}  SKIP  {why}")
            continue
        try:
            ok, detail = fn()
        except Exception as exc:  # a broken check is a failed check
            ok, detail = False, f"check raised: {exc}"
        mark = "PASS" if ok else "FAIL"
        print(f"  {name:<{width}}  {mark}  {detail}")
        if not ok:
            failures += 1

    print()
    if failures:
        print(f"{failures} gate(s) failed — do not tag.", file=sys.stderr)
        return 1
    print("all gates passed — safe to tag. Next: docs/publishing.md § 发布一个新版本")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
