"""The tool schema must say what the service actually enforces.

An independent acceptance run found that `tools/list` advertised no bounds at all
while `SearchQuery.validate` rejected `page > 3` and `limit > 50`. A caller could
only learn the range by failing a call — and a schema file in the repository that
the server never reads cannot help, which is why this test talks to the real server
object instead of parsing `schemas/tools.json`.

These tests are about the contract a *client* sees. They do not re-check that
`validate` rejects bad values; that is covered by its own tests.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from scholar_search.core.contracts import MAX_LIMIT, MAX_PAGE, MIN_PAGE


def _schemas() -> dict[str, dict[str, Any]]:
    from scholar_search.bootstrap import build_service
    from scholar_search.server import build_server

    server = build_server(build_service())
    tools = asyncio.run(server.list_tools())
    return {tool.name: tool.inputSchema for tool in tools}


@pytest.fixture(scope="module")
def schemas() -> dict[str, dict[str, Any]]:
    return _schemas()


def test_the_five_tools_are_advertised(schemas: dict[str, dict[str, Any]]) -> None:
    assert set(schemas) == {"search", "detail", "detail_many", "export", "status"}


def test_page_and_limit_carry_their_bounds(schemas: dict[str, dict[str, Any]]) -> None:
    """The bounds a caller needs before it forms a call.

    Without them an agent guesses, and a rejected call costs a round trip. The
    numbers come from `contracts`, so a change there reaches the schema.
    """

    props = schemas["search"]["properties"]
    assert props["page"]["minimum"] == MIN_PAGE
    assert props["page"]["maximum"] == MAX_PAGE
    assert props["limit"]["minimum"] == 1
    assert props["limit"]["maximum"] == MAX_LIMIT


def test_enumerated_parameters_list_their_values(schemas: dict[str, dict[str, Any]]) -> None:
    """A closed vocabulary belongs in the schema, not in the docstring."""

    props = schemas["search"]["properties"]
    for key in ("sort", "sort_by", "site_sort", "local_sort"):
        schema = props[key]
        # Optional ones are anyOf[enum, null].
        branch = schema if "enum" in schema else schema.get("anyOf", [{}])[0]
        assert branch.get("enum"), f"{key} should enumerate its accepted values"


def test_export_formats_are_enumerated(schemas: dict[str, dict[str, Any]]) -> None:
    props = schemas["export"]["properties"]
    assert set(props["format"]["enum"]) == {"ris", "endnote", "markdown", "csv"}


def test_detail_reports_the_projectable_fields(schemas: dict[str, dict[str, Any]]) -> None:
    """`fields` is the lever for response size, so its meaning has to be visible.

    It is deliberately not an enum: the valid keys come from the Record definition
    and would make a long, brittle list that goes stale the moment a field is added.
    What must be visible is that `url` and the quota pair survive any projection —
    that is the promise a caller relies on when it projects.
    """

    for tool in ("search", "detail", "detail_many"):
        props = schemas[tool]["properties"]
        assert "fields" in props, f"{tool} should advertise `fields`"
        description = props["fields"].get("description", "")
        assert "url" in description or "always" in description, (
            f"{tool}.fields should say what survives projection"
        )
