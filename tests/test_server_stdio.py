"""End-to-end: launch the server over stdio and call its tools like Claude Desktop would."""

import sys

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

pytestmark = pytest.mark.network

PARAMS = StdioServerParameters(command=sys.executable, args=["-m", "wiktionary_de_mcp"])


async def _call(tool: str, args: dict) -> str:
    async with stdio_client(PARAMS) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool, args)
            return result.content[0].text


async def test_lists_tools():
    async with stdio_client(PARAMS) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            names = {t.name for t in (await session.list_tools()).tools}
    assert names == {"lookup_word", "get_inflection_table", "search_wiktionary", "get_raw_wikitext"}


async def test_lookup_existing_word():
    text = await _call("lookup_word", {"word": "Haus"})
    assert "Nominativ Plural: Häuser" in text
    assert "Genus: n" in text


async def test_lookup_missing_word():
    text = await _call("lookup_word", {"word": "Hausxyzq"})
    assert text.startswith("NOT FOUND")


async def test_conjugation():
    text = await _call("get_inflection_table", {"word": "gehen"})
    assert "ich ging" in text
