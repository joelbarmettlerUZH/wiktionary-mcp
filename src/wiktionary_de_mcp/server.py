"""MCP server exposing de.wiktionary.org lookups as tools."""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated

import httpx
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from wiktionary_de_mcp import __version__
from wiktionary_de_mcp.client import PAGE_URL, Page, WiktionaryClient, html_tables_to_text
from wiktionary_de_mcp.wikitext import (
    INFLECTED_FORM_HEADINGS,
    LanguageEntry,
    PartOfSpeech,
    extract_section,
    normalize_language,
    parse_page,
)

INSTRUCTIONS = """\
Look up words in the German Wiktionary (de.wiktionary.org).

- Use `lookup_word` to check whether a word exists and to get its part of speech,
  gender, inflected forms (plural, cases, comparison, principal verb forms),
  hyphenation, pronunciation, meanings, etymology, synonyms and examples.
- Use `get_inflection_table` for complete conjugation/declension tables
  (e.g. every tense and person of a verb).
- Use `search_wiktionary` when a word is not found, to find spellings or related entries.
- Wiktionary is case-sensitive ("Laufen" the noun vs. "laufen" the verb); `lookup_word`
  tries both capitalizations automatically.
- Wiktionary documents per-word grammar (gender, plural, cases, conjugation, auxiliary
  verb), not general grammar rules such as when to use the dative.
- The content is German-language and comes from Wiktionary (CC BY-SA 4.0); cite the page URL.
"""

READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=True, idempotent_hint=True)

mcp = MCPServer(
    "wiktionary-de",
    title="German Wiktionary",
    instructions=INSTRUCTIONS,
    version=__version__,
    website_url="https://de.wiktionary.org",
)
client = WiktionaryClient()

# Per-section line limits for the compact (non-full) view. None = unlimited.
_COMPACT_LIMITS = {
    "Bedeutungen": None,
    "Beispiele": 5,
    "Wortbildungen": 3,
    "Unterbegriffe": 3,
    "Oberbegriffe": 3,
    "Redewendungen": 5,
    "Sprichwörter": 3,
    "Charakteristische Wortkombinationen": 4,
}
_COMPACT_DEFAULT_LIMIT = 6
_COMPACT_LINE_CHARS = 400
_SOURCE = "Source: de.wiktionary.org, CC BY-SA 4.0"


def _upstream_error(exc: httpx.HTTPError) -> ToolError:
    return ToolError(f"Could not reach de.wiktionary.org ({type(exc).__name__}: {exc}). Try again later.")


def _case_variants(word: str) -> list[str]:
    variants = [word]
    if word:
        for v in (word[0].upper() + word[1:], word[0].lower() + word[1:], word.lower()):
            if v not in variants:
                variants.append(v)
    return variants


def _is_lemma(pos: PartOfSpeech) -> bool:
    return not pos.heading.startswith(INFLECTED_FORM_HEADINGS)


def _format_forms(forms: dict[str, str]) -> list[str]:
    # Wiktionary marks alternative forms with a trailing "*", e.g.
    # "Dativ Singular=Haus" and "Dativ Singular*=Hause". Merge them.
    merged: dict[str, list[str]] = {}
    for key, value in forms.items():
        base = key.rstrip("*").replace("_", " ").strip()
        merged.setdefault(base, [])
        if value not in merged[base]:
            merged[base].append(value)
    return [f"- {k}: {' / '.join(v)}" for k, v in merged.items()]


def _format_part(pos: PartOfSpeech, full: bool) -> list[str]:
    out = [f"### {pos.heading}"]
    if pos.forms:
        out.append("**Grammatik / Formen**" + (f" ({pos.overview_template})" if pos.overview_template else ""))
        out.extend(_format_forms(pos.forms))
    for name, lines in pos.sections.items():
        limit = None if full else _COMPACT_LIMITS.get(name, _COMPACT_DEFAULT_LIMIT)
        shown = lines if limit is None else lines[:limit]
        out.append(f"**{name}**")
        for line in shown:
            if not full and len(line) > _COMPACT_LINE_CHARS:
                line = line[:_COMPACT_LINE_CHARS].rstrip() + " …"
            out.append(f"  {line}")
        if len(shown) < len(lines):
            out.append(f"  … (+{len(lines) - len(shown)} more; use full=true)")
    return out


def _format_entry(entry: LanguageEntry, full: bool) -> list[str]:
    out = [f"## {entry.title} ({entry.language})"]
    for pos in entry.parts:
        out.extend(_format_part(pos, full))
        out.append("")
    return out


async def _fetch_pages(titles: list[str]) -> list[Page]:
    pages = await asyncio.gather(*(client.get_wikitext(t) for t in titles))
    return [p for p in pages if p is not None]


async def _not_found(word: str) -> str:
    prefix, hits = await asyncio.gather(client.prefix_search(word, limit=8), client.search(word, limit=8))
    suggestions: list[str] = []
    for t in [*prefix, *(h["title"] for h in hits)]:
        if t not in suggestions:
            suggestions.append(t)
    msg = f'NOT FOUND: There is no de.wiktionary.org entry for "{word}" (also tried other capitalizations).'
    if suggestions:
        msg += "\nSimilar entries: " + ", ".join(suggestions[:12])
    return msg


@mcp.tool(title="Look up a word", annotations=READ_ONLY)
async def lookup_word(
    word: Annotated[str, Field(description="The word to look up, e.g. 'Haus', 'laufen', 'schön'.")],
    language: Annotated[
        str,
        Field(
            description=(
                "Which language's entry to return. Accepts German names as used on Wiktionary "
                "('Deutsch', 'Englisch'), English names ('German', 'English') or ISO codes "
                "('de', 'en'). Use '*' for all languages."
            )
        ),
    ] = "Deutsch",
    full: Annotated[
        bool, Field(description="Return every line of every section instead of a compact summary.")
    ] = False,
) -> str:
    """Check whether a word exists in the German Wiktionary and return its dictionary entry.

    Returns part of speech, grammatical forms (gender, plural, cases, comparison,
    verb principal parts, auxiliary verb), hyphenation, IPA, meanings, etymology,
    synonyms, antonyms and example sentences, all in German. The German Wiktionary
    also has entries for words of other languages (explained in German); select
    them with `language`. If the word does not exist the result starts with
    "NOT FOUND" and lists similar entries.
    """
    word = word.strip()
    if not word:
        raise ToolError("Please provide a word.")
    language = normalize_language(language)
    try:
        titles = await client.existing_titles(_case_variants(word))
        if not titles:
            return await _not_found(word)
        pages = await _fetch_pages(titles[:3])
    except httpx.HTTPError as exc:
        raise _upstream_error(exc) from exc

    matched: list[tuple[Page, list[LanguageEntry]]] = []
    other_languages: set[str] = set()
    for page in pages:
        entries = parse_page(page.wikitext)
        wanted = [e for e in entries if language == "*" or e.language.lower() == language.lower()]
        other_languages.update(e.language for e in entries if e not in wanted)
        if wanted:
            matched.append((page, wanted))

    if not matched:
        langs = ", ".join(sorted(other_languages)) or "unknown"
        return (
            f'The page "{titles[0]}" exists on de.wiktionary.org, but has no "{language}" entry. '
            f"Languages present: {langs}. Call again with language set to one of these (or '*')."
        )

    # Dictionary entries (lemmas) before pages that only list an inflected form,
    # e.g. "Haus" before "haus" (imperative of "hausen").
    matched.sort(key=lambda m: not any(_is_lemma(p) for e in m[1] for p in e.parts))

    out: list[str] = []
    for page, wanted in matched:
        out.append(f"# {page.title}  —  {page.url}")
        for entry in wanted:
            out.extend(_format_entry(entry, full))
        if any(p.overview_template and "Verb" in p.overview_template for e in wanted for p in e.parts):
            out.append(f"(Full conjugation: call get_inflection_table with word='{page.title}'.)")
        out.append("")
    if other_languages and language != "*":
        out.append("Also has entries in: " + ", ".join(sorted(other_languages)))
    out.append(_SOURCE)
    return "\n".join(out).strip()


@mcp.tool(title="Get conjugation/declension table", annotations=READ_ONLY)
async def get_inflection_table(
    word: Annotated[
        str, Field(description="The lemma (dictionary form), e.g. 'laufen', 'gehen', 'Haus'.")
    ],
) -> str:
    """Return the complete inflection table for a German word.

    For verbs this is the full conjugation (all tenses, moods, persons, participles,
    imperative); for adjectives the full strong/weak/mixed declension of the positive,
    comparative and superlative. Both come from the page "Flexion:<word>". Nouns
    usually have no such page; for them this returns the case and number forms
    listed on the entry itself.
    """
    word = word.strip()
    if not word:
        raise ToolError("Please provide a word.")
    variants = _case_variants(word)
    try:
        flexion_pages = await asyncio.gather(*(client.get_html(f"Flexion:{v}") for v in variants))
        for result in flexion_pages:
            if result:
                title, html_text = result
                table = html_tables_to_text(html_text)
                if table:
                    url = PAGE_URL + title.replace(" ", "_")
                    return f"# {title}  —  {url}\n\n{table}\n\n{_SOURCE}"

        titles = await client.existing_titles(variants)
        if not titles:
            return await _not_found(word)
        pages = await _fetch_pages(titles[:3])
    except httpx.HTTPError as exc:
        raise _upstream_error(exc) from exc

    out: list[str] = []
    for page in pages:
        for entry in parse_page(page.wikitext):
            if entry.language != "Deutsch":
                continue
            for pos in entry.parts:
                if pos.forms:
                    out.append(f"## {entry.title} — {pos.heading}  ({page.url})")
                    out.extend(_format_forms(pos.forms))
                    out.append("")
    if not out:
        return f'No inflection data found for "{word}" on de.wiktionary.org.'
    return "\n".join(out).strip() + f"\n\n{_SOURCE}"


@mcp.tool(title="Search the German Wiktionary", annotations=READ_ONLY)
async def search_wiktionary(
    query: Annotated[
        str,
        Field(description="Search text. Matches titles and page content, e.g. a misspelled word or a word stem."),
    ],
    limit: Annotated[int, Field(ge=1, le=50, description="Maximum number of results.")] = 10,
) -> str:
    """Full-text and prefix search over de.wiktionary.org entries.

    Useful for finding the correct spelling of a word, compounds that contain a stem,
    or entries when lookup_word returns NOT FOUND.
    """
    try:
        prefix, hits = await asyncio.gather(
            client.prefix_search(query, limit=limit), client.search(query, limit=limit)
        )
    except httpx.HTTPError as exc:
        raise _upstream_error(exc) from exc

    lines: list[str] = []
    suggestion = next((h["title"] for h in hits if h.get("suggestion")), None)
    if suggestion:
        lines.append(f"Did you mean: {suggestion}")
    if prefix:
        lines.append("Titles starting with the query: " + ", ".join(prefix))
    content = [h for h in hits if not h.get("suggestion")]
    if content:
        lines.append("Full-text matches:")
        for h in content:
            snippet = h.get("snippet", "").replace('<span class="searchmatch">', "").replace("</span>", "")
            lines.append(f"- {h['title']}: {' '.join(snippet.split())[:160]}")
    return "\n".join(lines) if lines else f'No results for "{query}".'


@mcp.tool(title="Get raw wikitext", annotations=READ_ONLY)
async def get_raw_wikitext(
    title: Annotated[str, Field(description="Exact page title (case-sensitive), e.g. 'Haus' or 'Flexion:gehen'.")],
    section: Annotated[
        str | None,
        Field(
            description=(
                "Only return the part of the page under the first heading or section marker containing "
                "this text, e.g. 'Übersetzungen', 'Referenzen', 'Englisch'. Omit for the whole page."
            )
        ),
    ] = None,
    offset: Annotated[int, Field(ge=0, description="Character offset to start from, for paging through long pages.")] = 0,
    max_chars: Annotated[int, Field(ge=500, le=50_000, description="Maximum characters to return.")] = 8000,
) -> str:
    """Return the unprocessed wikitext source of a de.wiktionary.org page.

    Use only when lookup_word omits something you need (e.g. translations,
    references). Pages can be very long (100k+ characters), so prefer `section`
    and page through with `offset` when the result says it was truncated.
    """
    try:
        page = await client.get_wikitext(title)
    except httpx.HTTPError as exc:
        raise _upstream_error(exc) from exc
    if page is None:
        raise ToolError(f'No page titled "{title}" exists on de.wiktionary.org.')

    text = page.wikitext
    if section:
        extracted = extract_section(text, section)
        if extracted is None:
            raise ToolError(f'No heading or section matching "{section}" on page "{page.title}".')
        text = extracted

    chunk = text[offset : offset + max_chars]
    header = f"# {page.title}  —  {page.url}"
    if section:
        header += f"  (section: {section})"
    end = offset + len(chunk)
    if offset or end < len(text):
        header += f"\n[characters {offset}–{end} of {len(text)}"
        header += f"; call again with offset={end} for more]" if end < len(text) else "]"
    return f"{header}\n\n{chunk}"


def main() -> None:
    # httpx logs every request at INFO; keep stderr quiet in MCP host logs.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    mcp.run()


if __name__ == "__main__":
    main()
