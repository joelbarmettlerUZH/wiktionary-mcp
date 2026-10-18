"""Thin async client for the de.wiktionary.org MediaWiki API."""

from __future__ import annotations

import time
from dataclasses import dataclass
from html.parser import HTMLParser

import httpx

from wiktionary_de_mcp import __version__

API_URL = "https://de.wiktionary.org/w/api.php"
PAGE_URL = "https://de.wiktionary.org/wiki/"
# Wikimedia asks API clients to send an identifying User-Agent.
USER_AGENT = (
    f"wiktionary-de-mcp/{__version__} "
    "(+https://pypi.org/project/wiktionary-de-mcp/) httpx"
)
_CACHE_TTL = 15 * 60
_CACHE_MAX = 256


@dataclass
class Page:
    title: str
    wikitext: str

    @property
    def url(self) -> str:
        return PAGE_URL + self.title.replace(" ", "_")


class WiktionaryClient:
    def __init__(self, http: httpx.AsyncClient | None = None) -> None:
        self._http = http or httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT}, timeout=20.0, follow_redirects=True
        )
        self._cache: dict[tuple, tuple[float, object]] = {}

    async def _get(self, **params: object) -> dict:
        key = tuple(sorted(params.items()))
        hit = self._cache.get(key)
        if hit and time.monotonic() - hit[0] < _CACHE_TTL:
            return hit[1]  # type: ignore[return-value]
        resp = await self._http.get(
            API_URL, params={"format": "json", "formatversion": "2", **params}
        )
        resp.raise_for_status()
        data = resp.json()
        if len(self._cache) >= _CACHE_MAX:
            self._cache.pop(next(iter(self._cache)))
        self._cache[key] = (time.monotonic(), data)
        return data

    async def existing_titles(self, titles: list[str]) -> list[str]:
        """Return which of `titles` exist (following redirects), in the given order."""
        data = await self._get(action="query", titles="|".join(titles), redirects=1)
        query = data.get("query", {})
        # Map requested title -> resolved title through normalization and redirects.
        resolve = {}
        for step in ("normalized", "redirects"):
            for item in query.get(step, []):
                resolve[item["from"]] = item["to"]
        present = {p["title"] for p in query.get("pages", []) if not p.get("missing")}
        out: list[str] = []
        for t in titles:
            r = t
            while r in resolve and resolve[r] != r:
                r = resolve[r]
            if r in present and r not in out:
                out.append(r)
        return out

    async def get_wikitext(self, title: str) -> Page | None:
        data = await self._get(action="parse", page=title, prop="wikitext", redirects=1)
        if "error" in data:
            return None
        parse = data["parse"]
        return Page(title=parse["title"], wikitext=parse["wikitext"])

    async def get_html(self, title: str) -> tuple[str, str] | None:
        data = await self._get(
            action="parse", page=title, prop="text", redirects=1, disableeditsection=1
        )
        if "error" in data:
            return None
        return data["parse"]["title"], data["parse"]["text"]

    async def search(self, query: str, limit: int = 10) -> list[dict]:
        data = await self._get(
            action="query",
            list="search",
            srsearch=query,
            srlimit=limit,
            srnamespace=0,
            srprop="snippet",
            srinfo="suggestion",
        )
        q = data.get("query", {})
        hits = q.get("search", [])
        suggestion = q.get("searchinfo", {}).get("suggestion")
        if suggestion:
            hits = [{"title": suggestion, "suggestion": True}, *hits]
        return hits

    async def prefix_search(self, prefix: str, limit: int = 10) -> list[str]:
        data = await self._get(
            action="query", list="prefixsearch", pssearch=prefix, pslimit=limit, psnamespace=0
        )
        return [p["title"] for p in data.get("query", {}).get("prefixsearch", [])]


class _TableText(HTMLParser):
    """Render the HTML tables of a Flexion page as pipe-separated text rows."""

    _SKIP = {"style", "script", "sup"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: list[str] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._skip = 0
        self._heading: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in self._SKIP:
            self._skip += 1
        elif tag == "tr":
            self._row = []
        elif tag in ("td", "th"):
            self._cell = []
        elif tag == "br" and self._cell is not None:
            self._cell.append(" / ")
        elif tag in ("h2", "h3", "h4", "caption"):
            self._heading = []

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP:
            self._skip = max(0, self._skip - 1)
        elif tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            cells = [c for c in self._row if c]
            if cells:
                self.lines.append(" | ".join(cells))
            self._row = None
        elif tag == "table":
            self.lines.append("")
        elif tag in ("h2", "h3", "h4", "caption") and self._heading is not None:
            text = " ".join("".join(self._heading).split())
            if text:
                self.lines.append(f"### {text}")
            self._heading = None

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        if self._cell is not None:
            self._cell.append(data)
        elif self._heading is not None:
            self._heading.append(data)


def html_tables_to_text(html_text: str) -> str:
    parser = _TableText()
    parser.feed(html_text)
    text = "\n".join(parser.lines)
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return text.strip()
