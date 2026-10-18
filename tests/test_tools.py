"""Tool behaviour against a mocked MediaWiki API, through an in-process MCP client."""

import httpx
import pytest
from mcp import Client

from wiktionary_de_mcp import server
from wiktionary_de_mcp.client import WiktionaryClient

PAGES = {
    "Haus": """== Haus ({{Sprache|Deutsch}}) ==
=== {{Wortart|Substantiv|Deutsch}}, {{n}} ===
{{Bedeutungen}}
:[1] [[Gebäude]]
==== {{Übersetzungen}} ====
"""
    + "*{{en}}: [1] {{Ü|en|house}}\n" * 2000,
    "haus": """== haus ({{Sprache|Deutsch}}) ==
=== {{Wortart|Konjugierte Form|Deutsch}} ===
{{Grammatische Merkmale}}
:2. Person Singular Imperativ Präsens Aktiv des Verbs [[hausen]]
""",
    "gift": """== gift ({{Sprache|Englisch}}) ==
=== {{Wortart|Substantiv|Englisch}} ===
{{Bedeutungen}}
:[1] [[Geschenk]]
""",
}


def _api(request: httpx.Request) -> httpx.Response:
    p = request.url.params
    if p["action"] == "query" and "titles" in p:
        pages = [
            {"title": t, "ns": 0} if t in PAGES else {"title": t, "ns": 0, "missing": True}
            for t in p["titles"].split("|")
        ]
        return httpx.Response(200, json={"query": {"pages": pages}})
    if p["action"] == "parse":
        title = p["page"]
        if title not in PAGES:
            return httpx.Response(200, json={"error": {"code": "missingtitle"}})
        return httpx.Response(200, json={"parse": {"title": title, "wikitext": PAGES[title]}})
    return httpx.Response(200, json={"query": {"prefixsearch": [], "search": []}})


def _down(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("connection refused", request=request)


@pytest.fixture
def api(monkeypatch):
    def use(handler):
        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        monkeypatch.setattr(server, "client", WiktionaryClient(http))

    return use


async def test_lemma_entries_come_before_inflected_forms(api):
    api(_api)
    async with Client(server.mcp) as c:
        text = (await c.call_tool("lookup_word", {"word": "haus"})).content[0].text
    assert text.index("# Haus") < text.index("# haus")


async def test_language_accepts_iso_codes_and_english_names(api):
    api(_api)
    async with Client(server.mcp) as c:
        for lang in ("en", "English", "englisch", "Englisch"):
            text = (await c.call_tool("lookup_word", {"word": "gift", "language": lang})).content[0].text
            assert "Geschenk" in text, lang


async def test_network_failure_is_reported_as_tool_error(api):
    api(_down)
    async with Client(server.mcp) as c:
        result = await c.call_tool("lookup_word", {"word": "Haus"})
    assert result.is_error
    assert "Could not reach de.wiktionary.org" in result.content[0].text


async def test_not_found_is_not_an_error(api):
    api(_api)
    async with Client(server.mcp) as c:
        result = await c.call_tool("lookup_word", {"word": "Xyzzy"})
    assert not result.is_error
    assert result.content[0].text.startswith("NOT FOUND")


async def test_raw_wikitext_is_truncated_and_pageable(api):
    api(_api)
    async with Client(server.mcp) as c:
        first = (await c.call_tool("get_raw_wikitext", {"title": "Haus", "max_chars": 1000})).content[0].text
        assert "call again with offset=1000" in first
        assert len(first) < 1300
        second = (
            await c.call_tool("get_raw_wikitext", {"title": "Haus", "max_chars": 1000, "offset": 1000})
        ).content[0].text
        assert "[characters 1000–2000 of" in second


async def test_raw_wikitext_section(api):
    api(_api)
    async with Client(server.mcp) as c:
        text = (await c.call_tool("get_raw_wikitext", {"title": "Haus", "section": "Bedeutungen"})).content[0].text
        assert "[[Gebäude]]" in text
        assert "Übersetzungen" not in text

        missing = await c.call_tool("get_raw_wikitext", {"title": "Haus", "section": "Nope"})
        assert missing.is_error
