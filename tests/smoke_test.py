"""Check that a built distribution starts and serves its tools.

Run against an installed wheel/sdist, outside the project:
    uv run --isolated --no-project --with dist/*.whl tests/smoke_test.py
"""

import asyncio
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

EXPECTED = {"lookup_word", "get_inflection_table", "search_wiktionary", "get_raw_wikitext"}


async def main() -> None:
    params = StdioServerParameters(command=sys.executable, args=["-m", "wiktionary_de_mcp"])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            info = await session.initialize()
            names = {t.name for t in (await session.list_tools()).tools}
    assert names == EXPECTED, names
    print(f"OK: {info.server_info.name} {info.server_info.version}, tools: {sorted(names)}")


asyncio.run(main())
