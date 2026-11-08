"""MCP server: four stable tools over the service facade."""

from __future__ import annotations

from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

from .core.contracts import SearchQuery
from .core.errors import RiskBlocked, ScholarSearchError
from .core.export import record_from_payload
from .core.service import ScholarService


def _page_payload(page: Any) -> dict[str, Any]:
    return {
        "records": [record.to_dict() for record in page.records],
        "total": page.total,
        "page": page.page,
        "page_count": page.page_count,
    }


def _payload(error: Exception) -> dict[str, Any]:
    if isinstance(error, RiskBlocked):
        return error.to_payload()
    return {"status": "error", "error": str(error), "kind": type(error).__name__}


def build_server(service: ScholarService) -> FastMCP:
    mcp = FastMCP("wensu")

    @mcp.tool()
    def search(
        query: str,
        channel: str = "cnki",
        sort: Literal["relevance", "date", "citation"] = "relevance",
        page: int = 1,
        year_from: int | None = None,
        year_to: int | None = None,
        source_types: list[str] | None = None,
        limit: int = 20,
        include_abstract: bool = False,
        sort_by: Literal["none", "citations", "year"] = "none",
        min_citations: int | None = None,
        sources_only: list[str] | None = None,
        min_impact_factor: float | None = None,
    ) -> dict[str, Any]:
        """Search a channel for bibliographic records. Read-only.

        Returns a shortlist by default: abstracts are omitted unless
        include_abstract is true, and sort_by / min_citations / sources_only
        filter locally without any browser action. Call detail(url) for the full
        record — after a search it is served from the cache, not the site.

        min_impact_factor is honoured by channels that ship journal metrics
        (currently webofscience); records whose journal has no metric are dropped.
        """
        try:
            return _page_payload(
                service.search(
                    SearchQuery(
                        text=query,
                        channel=channel,
                        sort=sort,
                        page=page,
                        year_from=year_from,
                        year_to=year_to,
                        source_types=tuple(source_types or ()),
                        limit=limit,
                        include_abstract=include_abstract,
                        sort_by=sort_by,
                        min_citations=min_citations,
                        sources_only=tuple(sources_only or ()),
                        min_impact_factor=min_impact_factor,
                    )
                )
            )
        except (RiskBlocked, ScholarSearchError) as error:
            return _payload(error)

    @mcp.tool()
    def detail(url: str, channel: str = "cnki") -> dict[str, Any]:
        """Fetch full metadata for one record by its detail URL."""
        try:
            return service.detail(url, channel=channel).to_dict()
        except (RiskBlocked, ScholarSearchError) as error:
            return _payload(error)

    @mcp.tool()
    def export(
        records: list[dict[str, Any]], format: Literal["ris", "endnote"] = "ris"
    ) -> dict[str, Any]:
        """Render records as RIS or EndNote text. No file is written."""
        try:
            typed = [record_from_payload(item) for item in records]
            return {"format": format, "text": service.export(typed, fmt=format)}
        except (RiskBlocked, ScholarSearchError, TypeError, ValueError) as error:
            return _payload(error if isinstance(error, Exception) else ValueError("bad record"))

    @mcp.tool()
    def status() -> dict[str, Any]:
        """Session state: channels, cooldown, quota, bridge readiness."""
        return service.status()

    return mcp
