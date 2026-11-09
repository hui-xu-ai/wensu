"""Command line entry point.

Exposes the same service the MCP server does, for on-demand use: no daemon, no
startup hook, one process per command.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from . import __version__
from .core import config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wensu",
        description="Read-only scholarly metadata retrieval (microkernel + channels).",
    )
    parser.add_argument("--version", action="version", version=f"wensu {__version__}")
    sub = parser.add_subparsers(dest="command")

    serve = sub.add_parser("serve", help="run the MCP server")
    serve.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)

    search = sub.add_parser("search", help="run one search and print the records")
    search.add_argument("query", help="keywords, or a Web of Science expression")
    search.add_argument("--channel", default="cnki")
    search.add_argument("--limit", type=int, default=20)
    search.add_argument("--page", type=int, default=1)
    search.add_argument("--sort", choices=["relevance", "date", "citation"], default="relevance")
    search.add_argument(
        "--site-sort",
        choices=["relevance", "date", "citation"],
        default=None,
        help="ask the site to re-sort (costs quota); same as --sort",
    )
    search.add_argument("--year-from", type=int, default=None)
    search.add_argument("--year-to", type=int, default=None)
    search.add_argument("--abstract", action="store_true", help="include abstracts")
    search.add_argument("--sort-by", choices=["none", "citations", "year"], default="none")
    search.add_argument(
        "--local-sort",
        choices=["none", "citations", "year"],
        default=None,
        help="re-order the fetched page (free); same as --sort-by",
    )
    search.add_argument(
        "--count-only",
        action="store_true",
        help="drop records and return only the count plus what explains it",
    )
    search.add_argument(
        "--field",
        action="append",
        dest="fields",
        metavar="NAME",
        default=None,
        help="keep only this record field; repeatable. `url` is always kept",
    )
    search.add_argument("--min-citations", type=int, default=None)
    search.add_argument("--sources-only", action="append", metavar="JOURNAL", default=None)
    search.add_argument("--min-impact-factor", type=float, default=None)
    search.add_argument("--format", choices=["json", "ris", "endnote"], default="json")

    detail = sub.add_parser("detail", help="print one record by its detail URL")
    detail.add_argument("url")
    detail.add_argument("--channel", default=None, help="inferred from the URL when omitted")
    detail.add_argument("--abstract", action="store_true", help="include the abstract")
    detail.add_argument(
        "--field",
        action="append",
        dest="fields",
        metavar="NAME",
        default=None,
        help="keep only this field; repeatable. `url` is always kept",
    )

    status_cmd = sub.add_parser("status", help="show session, quota and cooldown state")
    status_cmd.add_argument(
        "--brief",
        action="store_true",
        help="only what a health check needs (about 45 tokens instead of 500)",
    )

    reset = sub.add_parser("reset", help="clear the risk cooldown after manual verification")
    reset.add_argument("--confirm", action="store_true", help="required to actually clear")

    assets = sub.add_parser("assets", help="copy bundled browser assets to a directory")
    assets.add_argument("--target", required=True, help="destination directory")
    assets.add_argument("--force", action="store_true", help="replace existing asset directories")

    setup = sub.add_parser("setup", help="copy browser assets and register the native host")
    setup.add_argument(
        "--target", default=None, help="where to copy the assets (default: <home>/browser)"
    )
    setup.add_argument("--force", action="store_true", help="replace existing asset directories")
    setup.add_argument("--python", default=None, help="interpreter the native host should run")
    setup.add_argument("--no-host", action="store_true", help="only copy the assets")
    setup.add_argument(
        "--browser",
        choices=["edge", "chrome", "none"],
        default="edge",
        help="also create the dedicated profile wensu will start (default: edge; 'none' skips)",
    )
    setup.add_argument(
        "--executable", default=None, help="browser executable, if not auto-detected"
    )
    setup.add_argument(
        "--skills-dir",
        default=None,
        help="also install the bundled skills here (e.g. D:\\DSH\\.dsh\\skills)",
    )
    setup.add_argument("--extension-id", default=None, help="extension id, recorded for status")

    export_cmd = sub.add_parser("export", help="render records from a JSON file")
    export_cmd.add_argument("records", help="path to a JSON file holding an array of records")
    export_cmd.add_argument(
        "--format", choices=["ris", "endnote", "markdown", "csv"], default="ris"
    )
    export_cmd.add_argument("--out", default=None, help="write here instead of stdout")
    export_cmd.add_argument(
        "--abstract",
        action="store_true",
        help="keep abstracts (off by default: an AB field roughly quadruples an RIS entry)",
    )

    browser_cmd = sub.add_parser(
        "browser", help="start the dedicated browser profile that has the extension"
    )
    browser_sub = browser_cmd.add_subparsers(dest="browser_command", required=True)
    browser_sub.add_parser("start", help="launch the recorded profile")
    browser_sub.add_parser("show", help="print the recorded profile and whether it exists")
    adopt = browser_sub.add_parser(
        "adopt", help="record an existing profile instead of creating one"
    )
    adopt.add_argument("path", help="the existing --user-data-dir, e.g. E:\\LiteratureEdgeProfile")
    adopt.add_argument("--browser", choices=["edge", "chrome"], default="edge")
    adopt.add_argument("--executable", default=None, help="browser executable if not auto-detected")
    adopt.add_argument("--extension-id", default=None)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    # A zh-CN Windows console defaults to GBK, so `wensu search ... > out.json`
    # wrote GBK bytes into a file every consumer reads as UTF-8. Fix the stream,
    # not just the strings: ensure_ascii=False is what makes this matter.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        with contextlib.suppress(OSError, ValueError):
            reconfigure(encoding="utf-8")

    args = build_parser().parse_args(argv)

    if args.command is None:
        build_parser().print_help()
        return 0

    if args.command == "reset":
        if not args.confirm:
            print("refusing to clear the cooldown without --confirm", file=sys.stderr)
            return 2
        from .core.audit import AuditLog
        from .core.risk import RiskGuard

        RiskGuard().clear()
        # Lifting a safety cooldown is exactly the kind of action that needs a
        # trail: without a line here there is no way to tell who cleared it, when,
        # or in response to what.
        AuditLog().write("risk_cleared", cooldown_cleared=True)
        print("risk cooldown cleared", file=sys.stderr)
        return 0

    if args.command == "assets":
        from .assets import copy_assets

        try:
            copied = copy_assets(Path(args.target), force=args.force)
        except (OSError, FileExistsError, FileNotFoundError) as error:
            print(f"cannot copy assets: {error}", file=sys.stderr)
            return 1
        for path in copied:
            print(path)
        return 0

    config.ensure_home()

    if args.command == "setup":
        from .browser_setup import setup_browser

        try:
            code = setup_browser(
                Path(args.target) if args.target else None,
                force=args.force,
                python=args.python,
                register_host=not args.no_host,
                skills_dir=Path(args.skills_dir) if args.skills_dir else None,
            )
        except FileExistsError as error:
            # Already-installed assets are not a failure to re-run setup: the point
            # of running it again is usually the browser profile, not the files.
            print(f"wensu: {error}", file=sys.stderr)
            print("wensu: continuing with the browser profile (use --force to replace assets)",
                  file=sys.stderr)
            code = 0
        # The browser profile is what every later session depends on: without it the
        # tool has no idea which window the extension lives in, and a caller is left
        # guessing — which is how one ended up killing the user's browser.
        if code == 0 and args.browser != "none":
            from .core import browser as browser_cfg

            # Never overwrite a recorded profile. A user who ran `browser adopt`
            # chose that directory on purpose; replacing it with a fresh
            # `profiles/<name>` silently moves the tool away from the window they
            # were using. Only create one when nothing is recorded yet.
            existing = browser_cfg.load()
            if existing is not None and not args.force:
                print(f"browser profile: {existing.profile_dir} (already recorded, kept)")
                print("  use --force to replace it, or `wensu browser adopt <path>`")
                return code
            try:
                made = browser_cfg.create(
                    args.browser,
                    executable=args.executable,
                    extension_id=args.extension_id,
                )
            except FileNotFoundError as error:
                print(f"wensu: {error}", file=sys.stderr)
                return 1
            print(f"browser profile: {made.profile_dir}")
            print(f"recorded in    : {browser_cfg.config_path()}")
            print(
                "next           : wensu browser start  "
                "(then load the unpacked extension once if the toolbar icon is missing)"
            )
        return code

    if args.command == "export":
        from dataclasses import replace as dataclass_replace

        from .bootstrap import build_service
        from .core.export import record_from_payload

        try:
            payload = json.loads(Path(args.records).read_text(encoding="utf-8"))
            if isinstance(payload, dict) and "records" in payload:
                payload = payload["records"]
            typed = [record_from_payload(item) for item in payload]
            if not args.abstract:
                typed = [dataclass_replace(r, abstract=None) for r in typed]
            text = build_service().export(typed, fmt=args.format)
        except (OSError, ValueError, KeyError, TypeError) as error:
            print(f"wensu: {error}", file=sys.stderr)
            return 2
        if args.out:
            target = Path(args.out).expanduser()
            target.parent.mkdir(parents=True, exist_ok=True)
            # newline="": no CRLF translation, so the size matches the text.
            with target.open("w", encoding="utf-8", newline="") as handle:
                handle.write(text)
            print(
                json.dumps(
                    {
                        "written": True,
                        "path": str(target.resolve()),
                        "format": args.format,
                        "records": len(typed),
                        "bytes": target.stat().st_size,
                        "include_abstract": args.abstract,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            print(text)
        return 0

    if args.command == "browser":
        from .core import browser as browser_cfg

        if args.browser_command == "adopt":
            try:
                adopted = browser_cfg.adopt(
                    args.path,
                    browser=args.browser,
                    executable=args.executable,
                    extension_id=args.extension_id,
                )
            except (FileNotFoundError, ValueError) as error:
                print(f"wensu: {error}", file=sys.stderr)
                return 2
            print(f"adopted : {adopted.profile_dir}")
            print(f"recorded: {browser_cfg.config_path()}")
            print("next    : wensu browser start")
            return 0

        recorded = browser_cfg.load()
        if recorded is None:
            print(
                "wensu: no browser profile recorded yet; run `wensu setup --browser edge`",
                file=sys.stderr,
            )
            return 2

        if args.browser_command == "show":
            print(json.dumps(recorded.to_dict(), ensure_ascii=False, indent=2))
            print(f"profile exists : {Path(recorded.profile_dir).is_dir()}")
            print(f"extension found: {Path(recorded.extension_dir).is_dir()}")
            return 0

        try:
            process = browser_cfg.start(recorded)
        except RuntimeError as error:
            # A browser that died on launch is not a success, and saying "started"
            # would send the caller looking for a bridge that cannot appear.
            print(f"wensu: {error}", file=sys.stderr)
            return 1
        print(f"started {recorded.browser} (pid {process.pid}) with profile {recorded.profile_dir}")
        print("if the toolbar icon is missing, load the unpacked extension once:")
        print(f"  chrome://extensions -> Load unpacked -> {recorded.extension_dir}")
        return 0

    if args.command in {"search", "detail"}:
        from .bootstrap import build_service
        from .core.contracts import SearchQuery
        from .core.errors import RiskBlocked, ScholarSearchError

        service = build_service()
        try:
            if args.command == "detail":
                # Same inference, same projection and same quota reporting as the MCP
                # tool. This block used to hold its own copy and got the abstract
                # switch backwards.
                from .server import _detail_payload

                identifier = args.url.strip()
                before_q = service.status(brief=True).get("quota_remaining")
                if identifier.lower().startswith("10.") and "/" in identifier:
                    # A DOI is short and stable; a CNKI detail URL is hundreds of
                    # characters of encrypted signature and easy to truncate.
                    by_doi = service.detail_by_doi(identifier, channel=args.channel)
                    raw = by_doi.to_dict()
                else:
                    resolved = args.channel or service.channel_for_url(identifier)
                    if resolved is None:
                        print(
                            f"wensu: no channel claims the host of {identifier!r}",
                            file=sys.stderr,
                        )
                        return 2
                    raw = service.detail(identifier, channel=resolved).to_dict()
                after_q = service.status(brief=True).get("quota_remaining")
                print(
                    json.dumps(
                        _detail_payload(
                            raw,
                            include_abstract=getattr(args, "abstract", False),
                            fields=getattr(args, "fields", None),
                            quota_charged=(
                                max(0, before_q - after_q)
                                if isinstance(before_q, int) and isinstance(after_q, int)
                                else 0
                            ),
                            quota_remaining=after_q if isinstance(after_q, int) else None,
                        ),
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                return 0
            # Validate the projection before querying. `_page_payload` raises for an
            # unknown key, but it runs after the search, outside this try block — so a
            # typo produced a traceback and, on a cold query, a spent request.
            from .server import _check_fields

            _check_fields(args.fields)
            query = SearchQuery(
                text=args.query,
                channel=args.channel,
                sort=args.site_sort or args.sort,
                page=args.page,
                year_from=args.year_from,
                year_to=args.year_to,
                limit=args.limit,
                include_abstract=args.abstract,
                sort_by=args.local_sort or args.sort_by,
                min_citations=args.min_citations,
                sources_only=tuple(args.sources_only or ()),
                min_impact_factor=args.min_impact_factor,
            )
            before_quota = service.status(brief=True).get("quota_remaining")
            page = service.search(query)
            after_quota = service.status(brief=True).get("quota_remaining")
            spent = (
                max(0, before_quota - after_quota)
                if isinstance(before_quota, int) and isinstance(after_quota, int)
                else None
            )
            after = after_quota if isinstance(after_quota, int) else None
        except RiskBlocked as error:
            print(json.dumps(error.to_payload(), ensure_ascii=False), file=sys.stderr)
            return 3
        except ScholarSearchError as error:
            print(f"wensu: {error}", file=sys.stderr)
            return 1
        except ValueError as error:
            # SearchQuery raises plain ValueError for out-of-range arguments such
            # as --limit 100 or --page 9. Those are user mistakes, not bugs, and
            # deserve a one-line message rather than a traceback.
            print(f"wensu: {error}", file=sys.stderr)
            return 2

        if args.format == "json":
            # Built by the same function the MCP tool uses. Writing this payload twice
            # has now cost five fields — `dropped_year`, `filters`, `quota_charged`,
            # `quota_remaining`, `count_only` — because each fix went to whichever
            # surface the test happened to exercise.
            from .server import _page_payload

            print(
                json.dumps(
                    _page_payload(
                        page,
                        query,
                        args.fields,
                        quota_charged=spent,
                        quota_remaining=after,
                        count_only=getattr(args, "count_only", False),
                    ),
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            print(service.export(page.records, fmt=args.format))
        return 0

    if args.command == "status":
        from .bootstrap import build_service

        service = build_service()
        print(
            json.dumps(
                service.status(brief=getattr(args, "brief", False)),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.command == "serve":
        from .bootstrap import build_service
        from .transports import http as http_transport
        from .transports import stdio as stdio_transport

        service = build_service()
        if args.transport == "http":
            http_transport.serve(service, host=args.host, port=args.port)
        else:
            stdio_transport.serve(service)
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
