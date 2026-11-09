"""Browser-side assets shipped inside the distribution.

The wheel and sdist carry the native host sources, the extension and the JSON
schemas so a user who only installed the package can still complete the
documented setup. ``wensu assets --target DIR`` copies them out.
"""

from __future__ import annotations

import shutil
from importlib.resources import files
from pathlib import Path

ASSET_DIRS = ("native-host", "extension", "schemas")


def skills_root() -> Path | None:
    """Where the SKILL.md files live, or None when this install has none.

    Kept separate from the browser assets: those are copied into the tool's own
    runtime directory, while skills belong wherever the agent looks for them.
    """

    packaged = Path(str(files("scholar_search"))) / "assets" / "skills"
    if packaged.is_dir():
        return packaged
    checkout = Path(__file__).resolve().parent.parent.parent / "skills"
    if checkout.is_dir():
        return checkout
    return None


def install_skills(target: Path, *, force: bool = False) -> list[Path]:
    """Copy the bundled skills into a skill directory.

    Each skill is its own directory containing `SKILL.md`, which is the layout the
    harness expects. An existing directory is left alone unless `force` is set: a
    user who edited a skill should not lose that because a later `setup` ran.
    """

    root = skills_root()
    if root is None:
        return []
    target.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []
    for skill in sorted(root.iterdir()):
        if not skill.is_dir() or not (skill / "SKILL.md").is_file():
            continue
        destination = target / skill.name
        if destination.exists():
            if not force:
                continue
            shutil.rmtree(destination)
        shutil.copytree(skill, destination)
        copied.append(destination)
    return copied


def assets_root() -> Path:
    """Where the browser assets live: the wheel's package data, or the repo."""

    packaged = Path(str(files("scholar_search"))) / "assets"
    if packaged.is_dir():
        return packaged
    # Source checkout: the assets sit at the repository root.
    checkout = Path(__file__).resolve().parent.parent.parent
    if (checkout / "native-host").is_dir() and (checkout / "extension").is_dir():
        return checkout
    return packaged


def copy_assets(target: Path, *, force: bool = False) -> list[Path]:
    """Copy the bundled browser assets into ``target`` and return the paths."""

    root = assets_root()
    if not root.is_dir():
        raise FileNotFoundError(
            "this installation has no bundled assets; use a release wheel or the source tree"
        )
    target.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []
    for name in ASSET_DIRS:
        source = root / name
        if not source.is_dir():
            continue
        destination = target / name
        if destination.exists():
            if not force:
                raise FileExistsError(f"{destination} already exists; pass --force to replace it")
            shutil.rmtree(destination)
        shutil.copytree(source, destination)
        copied.append(destination)
    return copied
