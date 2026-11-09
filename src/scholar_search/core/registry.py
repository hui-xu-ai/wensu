"""Channel discovery and version selection.

The registry never imports a channel until it is selected. Loading a channel
that fails its contract is a configuration error, not a silent fallback.
"""

from __future__ import annotations

import importlib
import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING

from packaging.version import Version

from .. import __version__
from .contracts import Channel, ChannelManifest
from .errors import ChannelError, ChannelNotFound

if TYPE_CHECKING:
    from collections.abc import Iterator

CORE_VERSION = Version(__version__)
_PACKAGE_ROOT = __package__.rsplit(".", 1)[0]


@dataclass(frozen=True, slots=True)
class ChannelSpec:
    name: str
    site_version: str
    manifest: ChannelManifest
    package: str


def _version_key(text: str) -> tuple[int, ...]:
    """Turn "2026.10" into a sortable tuple. Non-numeric parts sort last."""

    parts: list[int] = []
    for chunk in text.replace("-", ".").split("."):
        try:
            parts.append(int(chunk))
        except ValueError:
            parts.append(-1)
    return tuple(parts)


def _load_manifest(path: Path) -> ChannelManifest:
    raw = json.loads(path.read_text(encoding="utf-8"))
    manifest = ChannelManifest(
        channel=raw["channel"],
        site_version=raw["site_version"],
        schema_version=int(raw["schema_version"]),
        min_core=str(raw["min_core"]),
        domains=tuple(raw["domains"]),
        verbs=tuple(raw["verbs"]),
        capabilities=tuple(raw["capabilities"]),
        detail_url_prefixes=tuple(raw.get("detail_url_prefixes", ())),
        field_support=dict(raw.get("field_support", {})),
    )
    manifest.validate()
    return manifest


class ChannelRegistry:
    """Filesystem-backed registry of channel plugins."""

    def __init__(self, root: Path | None = None) -> None:
        self._root = root or Path(__file__).resolve().parent.parent / "channels"
        # Filled on first discover(). Every action used to re-scan the channels tree
        # twice, which is pure filesystem work on a hot path.
        self._known: list[ChannelSpec] | None = None

    @property
    def root(self) -> Path:
        return self._root

    def discover(self) -> list[ChannelSpec]:
        if self._known is not None:
            return list(self._known)

        specs: list[ChannelSpec] = []
        for manifest_path in sorted(self._root.glob("*/manifest.json")):
            channel_dir = manifest_path.parent
            try:
                manifest = _load_manifest(manifest_path)
            except (OSError, ValueError, KeyError) as exc:
                raise ChannelError(f"invalid manifest at {manifest_path}: {exc}") from exc

            versions = sorted(
                (p.name for p in channel_dir.iterdir() if p.is_dir() and p.name.startswith("v")),
                key=_version_key,
            )
            if not versions:
                raise ChannelError(f"channel {manifest.channel!r} has no version directory")

            for version in versions:
                site_version = version[1:].replace("_", ".")
                # The directory name is the single source of truth for the site
                # version: `site_version` inside manifest.json is overwritten here on
                # purpose, so a stale field cannot disagree with the directory.
                specs.append(
                    ChannelSpec(
                        name=manifest.channel,
                        site_version=site_version,
                        manifest=replace(manifest, site_version=site_version),
                        package=(f"{_PACKAGE_ROOT}.channels.{channel_dir.name}.{version}"),
                    )
                )
        self._known = list(specs)
        return specs

    def select(self, name: str, site_version: str | None = None) -> ChannelSpec:
        candidates = [spec for spec in self.discover() if spec.name == name]
        if not candidates:
            raise ChannelNotFound(f"channel {name!r} is not installed")

        usable = [spec for spec in candidates if CORE_VERSION >= Version(spec.manifest.min_core)]
        if not usable:
            raise ChannelError(
                f"channel {name!r} requires core >= {candidates[0].manifest.min_core}"
            )

        if site_version is not None:
            for spec in usable:
                if spec.site_version == site_version:
                    return spec
            raise ChannelNotFound(f"channel {name!r} has no site version {site_version!r}")

        return max(usable, key=lambda spec: _version_key(spec.site_version))

    def load(self, name: str, site_version: str | None = None) -> Channel:
        spec = self.select(name, site_version)
        module = importlib.import_module(spec.package)
        factory = getattr(module, "get_channel", None)
        if factory is None:
            raise ChannelError(f"{spec.package} does not export get_channel()")
        channel: Channel = factory()
        if channel.manifest.channel != name:
            raise ChannelError(f"channel {spec.package} reports name {channel.manifest.channel!r}")
        return channel

    def __iter__(self) -> Iterator[ChannelSpec]:
        return iter(self.discover())
