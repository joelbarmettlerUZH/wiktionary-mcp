"""Parse and clean de.wiktionary.org wikitext into readable structures.

A de.wiktionary page looks like this:

    == Haus ({{Sprache|Deutsch}}) ==
    === {{Wortart|Substantiv|Deutsch}}, {{n}} ===
    {{Deutsch Substantiv Übersicht
    |Genus=n
    |Nominativ Plural=Häuser
    ...}}
    {{Worttrennung}}
    :Haus, {{Pl.}} Häu·ser
    {{Bedeutungen}}
    :[1] zu einem bestimmten Zweck erbautes [[Gebäude]]
    ...
    ==== {{Übersetzungen}} ====

So: level-2 heading per language, level-3 heading per part of speech, an
optional "Übersicht" template holding the grammatical forms, then sections
introduced by a bare `{{Name}}` line.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field

# Templates that render to nothing useful in plain text.
_DROP_TEMPLATES = {
    "Hörbeispiele",
    "Audio",
    "Wort der Woche",
    "Siehe auch",
    "Ähnlichkeiten",
    "Wikipedia",
    "Wikisource",
    "Commons",
    "Beispiele fehlen",
    "Bedeutungen fehlen",
    "Herkunft fehlt",
    "QS Herkunft",
    "QS Bedeutungen",
    "Referenzen",
    "Quellen",
    "Internetquelle",
    "Literatur",
    "Per-Quelle",
    "Ü-Tabelle",
    "Bild",
}
_DROP_PREFIXES = ("Ref-", "Lit-", "QS ", "Ü-", "Wikipedia")

# Gender / number markers.
_SIMPLE = {"m": "m", "f": "f", "n": "n", "u": "u", "IPA": "IPA:", "Reime": "Reime:"}

# Section headers whose content we never want (audio, sources, …).
SKIP_SECTIONS = {"Hörbeispiele", "Referenzen", "Quellen", "Übersetzungen", "Ähnlichkeiten"}

# Part-of-speech headings of pages that only document an inflected form
# ("haus" = imperative of "hausen") rather than a dictionary entry.
INFLECTED_FORM_HEADINGS = ("Konjugierte Form", "Deklinierte Form", "Komparativ", "Superlativ")

# de.wiktionary names languages in German. Map English names and ISO codes
# that a model is likely to pass onto those names.
_LANGUAGE_ALIASES = {
    "Deutsch": ("de", "deu", "ger", "german"),
    "Englisch": ("en", "eng", "english"),
    "Französisch": ("fr", "fra", "fre", "french"),
    "Spanisch": ("es", "spa", "spanish"),
    "Italienisch": ("it", "ita", "italian"),
    "Portugiesisch": ("pt", "por", "portuguese"),
    "Niederländisch": ("nl", "nld", "dut", "dutch"),
    "Latein": ("la", "lat", "latin"),
    "Altgriechisch": ("grc", "ancient greek"),
    "Neugriechisch": ("el", "ell", "greek", "modern greek"),
    "Schwedisch": ("sv", "swe", "swedish"),
    "Dänisch": ("da", "dan", "danish"),
    "Norwegisch": ("no", "nor", "nb", "norwegian"),
    "Isländisch": ("is", "isl", "icelandic"),
    "Finnisch": ("fi", "fin", "finnish"),
    "Polnisch": ("pl", "pol", "polish"),
    "Tschechisch": ("cs", "ces", "cze", "czech"),
    "Russisch": ("ru", "rus", "russian"),
    "Ukrainisch": ("uk", "ukr", "ukrainian"),
    "Türkisch": ("tr", "tur", "turkish"),
    "Ungarisch": ("hu", "hun", "hungarian"),
    "Rumänisch": ("ro", "ron", "rum", "romanian"),
    "Kroatisch": ("hr", "hrv", "croatian"),
    "Serbisch": ("sr", "srp", "serbian"),
    "Japanisch": ("ja", "jpn", "japanese"),
    "Chinesisch": ("zh", "zho", "chi", "chinese"),
    "Koreanisch": ("ko", "kor", "korean"),
    "Arabisch": ("ar", "ara", "arabic"),
    "Hebräisch": ("he", "heb", "hebrew"),
    "Esperanto": ("eo", "epo"),
}
_LANGUAGE_LOOKUP = {alias: name for name, aliases in _LANGUAGE_ALIASES.items() for alias in aliases}


def normalize_language(language: str) -> str:
    """Map 'en' / 'English' / 'englisch' to Wiktionary's 'Englisch'; '*'/'all' to '*'."""
    key = language.strip().lower()
    if key in ("*", "all", "alle", "any"):
        return "*"
    if key in _LANGUAGE_LOOKUP:
        return _LANGUAGE_LOOKUP[key]
    for name in _LANGUAGE_ALIASES:
        if name.lower() == key:
            return name
    # Unknown: assume it's already a German language name as used on Wiktionary.
    return language.strip()


@dataclass
class PartOfSpeech:
    heading: str  # e.g. "Substantiv, n"
    forms: dict[str, str] = field(default_factory=dict)  # from the Übersicht template
    overview_template: str | None = None  # e.g. "Deutsch Substantiv Übersicht"
    sections: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class LanguageEntry:
    title: str  # lemma as written in the heading
    language: str
    parts: list[PartOfSpeech] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Template handling
# --------------------------------------------------------------------------- #


def _find_template_end(text: str, start: int) -> int:
    """Given text[start:start+2] == '{{', return the index just past the matching '}}'."""
    depth = 0
    i = start
    n = len(text)
    while i < n - 1:
        pair = text[i : i + 2]
        if pair == "{{":
            depth += 1
            i += 2
        elif pair == "}}":
            depth -= 1
            i += 2
            if depth == 0:
                return i
        else:
            i += 1
    return n


def split_template(inner: str) -> tuple[str, list[str], dict[str, str]]:
    """Split the inside of a `{{...}}` into name, positional and named args.

    Pipes inside nested templates or links are not treated as separators.
    """
    parts: list[str] = []
    depth_t = depth_l = 0
    buf: list[str] = []
    i = 0
    while i < len(inner):
        pair = inner[i : i + 2]
        if pair == "{{":
            depth_t += 1
            buf.append(pair)
            i += 2
            continue
        if pair == "}}":
            depth_t -= 1
            buf.append(pair)
            i += 2
            continue
        if pair == "[[":
            depth_l += 1
            buf.append(pair)
            i += 2
            continue
        if pair == "]]":
            depth_l -= 1
            buf.append(pair)
            i += 2
            continue
        ch = inner[i]
        if ch == "|" and depth_t == 0 and depth_l == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
        i += 1
    parts.append("".join(buf))

    name = parts[0].strip()
    positional: list[str] = []
    named: dict[str, str] = {}
    for p in parts[1:]:
        key, sep, value = p.partition("=")
        # A '=' inside a nested template/link doesn't make it a named arg.
        if sep and "{{" not in key and "[[" not in key:
            named[key.strip()] = value.strip()
        else:
            positional.append(p.strip())
    return name, positional, named


def _render_template(name: str, positional: list[str], named: dict[str, str]) -> str:
    if name in _DROP_TEMPLATES or name.startswith(_DROP_PREFIXES):
        return ""
    if name in _SIMPLE:
        return _SIMPLE[name]
    if name == "K":
        # Context labels: {{K|ugs.|scherzhaft}} -> "(ugs., scherzhaft)"
        labels = [clean(p) for p in positional if p]
        return f"({', '.join(labels)}):" if labels else ""
    if name in ("Lautschrift", "Reim"):
        return clean(positional[0]) if positional else ""
    if name == "Ü" or name == "Üt":
        # {{Ü|goh|hūs}} -> hūs
        return clean(positional[1]) if len(positional) > 1 else ""
    if name == "Sprache":
        return positional[0] if positional else ""
    if name == "Wortart":
        return positional[0] if positional else ""
    if name == "L":
        return clean(positional[1] if len(positional) > 1 else positional[0]) if positional else ""
    if name in ("Polytonisch", "lang", "Lit"):
        return clean(positional[-1]) if positional else ""
    if not positional and not named:
        # Abbreviation templates like {{Pl.}}, {{Prät.}}, {{ugs.}}, {{goh.}}.
        if name.endswith(".") or len(name) <= 4:
            return name
        return ""
    # Unknown template with arguments: best effort, keep the first argument.
    return clean(positional[0]) if positional else ""


def _expand_templates(text: str) -> str:
    out: list[str] = []
    i = 0
    while True:
        j = text.find("{{", i)
        if j == -1:
            out.append(text[i:])
            break
        out.append(text[i:j])
        end = _find_template_end(text, j)
        inner = text[j + 2 : end - 2]
        name, positional, named = split_template(inner)
        out.append(_render_template(name, positional, named))
        i = end
    return "".join(out)


# --------------------------------------------------------------------------- #
# Cleaning
# --------------------------------------------------------------------------- #

_REF_RE = re.compile(r"<ref[^>/]*/>|<ref[^>]*>.*?</ref>", re.DOTALL | re.IGNORECASE)
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_TAG_RE = re.compile(r"</?(?:sup|sub|small|span|div|br|nowiki|u|s|i|b)\b[^>]*>", re.IGNORECASE)
_LINK_RE = re.compile(r"\[\[([^\[\]|]*)(?:\|([^\[\]]*))?\]\]")
_EXTLINK_RE = re.compile(r"\[(?:https?:)?//[^\s\]]+\s*([^\]]*)\]")
_BOLD_ITALIC_RE = re.compile(r"'{2,5}")


def _render_link(m: re.Match[str]) -> str:
    target, label = m.group(1), m.group(2)
    if target.startswith(("Datei:", "File:", "Bild:", "Kategorie:", "Category:")):
        return ""
    if label is not None:
        return label
    # Drop interwiki / namespace prefixes such as "w:" for display.
    return target.split(":", 1)[1] if target.startswith(("w:", ":")) else target


def clean(text: str) -> str:
    """Turn a fragment of wikitext into readable plain text."""
    text = _COMMENT_RE.sub("", text)
    text = _REF_RE.sub("", text)
    text = _expand_templates(text)
    # Links may nest one level (e.g. images with linked captions); run twice.
    for _ in range(2):
        text = _LINK_RE.sub(_render_link, text)
    text = _EXTLINK_RE.sub(r"\1", text)
    text = _TAG_RE.sub("", text)
    text = _BOLD_ITALIC_RE.sub("", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\(\s*\):", "", text)
    return text.strip()


# --------------------------------------------------------------------------- #
# Page structure
# --------------------------------------------------------------------------- #

_H2_RE = re.compile(r"^==\s*([^=].*?)\s*==\s*$", re.MULTILINE)
_H3_RE = re.compile(r"^===\s*([^=].*?)\s*===\s*$", re.MULTILINE)
_H4PLUS_RE = re.compile(r"^====+\s*(.*?)\s*====+\s*$", re.MULTILINE)
_SECTION_LINE_RE = re.compile(r"^\{\{([^{}|]+)\}\}\s*$")
_LANG_RE = re.compile(r"\{\{Sprache\|([^}]+)\}\}")


def _split_by(regex: re.Pattern[str], text: str) -> list[tuple[str, str]]:
    matches = list(regex.finditer(text))
    out = []
    for k, m in enumerate(matches):
        end = matches[k + 1].start() if k + 1 < len(matches) else len(text)
        out.append((m.group(1), text[m.end() : end]))
    return out


def _parse_part(heading: str, body: str) -> PartOfSpeech:
    # Everything from the first level-4 heading on (usually "Übersetzungen")
    # is translations; cut it off.
    h4 = _H4PLUS_RE.search(body)
    if h4:
        body = body[: h4.start()]

    pos = PartOfSpeech(heading=clean(heading))

    # The "Übersicht" (overview) template holds the inflected forms.
    m = re.search(r"\{\{\s*([^{}|]*Übersicht[^{}|]*)\s*\|", body)
    if m:
        start = m.start()
        end = _find_template_end(body, start)
        name, _, named = split_template(body[start + 2 : end - 2])
        pos.overview_template = name
        pos.forms = {
            k: clean(v)
            for k, v in named.items()
            if v and not k.startswith(("Bild", "Grafik", "Klang"))
        }
        body = body[:start] + body[end:]

    current: str | None = None
    for raw_line in body.splitlines():
        line = raw_line.rstrip()
        sec = _SECTION_LINE_RE.match(line.strip())
        if sec:
            current = sec.group(1).strip()
            pos.sections.setdefault(current, [])
            continue
        if current is None or current in SKIP_SECTIONS or not line.strip():
            continue
        # Lines are usually ":[1] text" or "*text"; keep the [n] numbering.
        stripped = line.lstrip(":*# ")
        if current == "Aussprache" and "Hörbeispiele" in line:
            continue
        cleaned = clean(stripped)
        if cleaned:
            pos.sections[current].append(cleaned)

    pos.sections = {k: v for k, v in pos.sections.items() if v and k not in SKIP_SECTIONS}
    return pos


_ANY_HEADING_RE = re.compile(r"^(=+)\s*(.*?)\s*=+\s*$")


def extract_section(wikitext: str, needle: str) -> str | None:
    """Return the raw wikitext under the first heading or `{{Section}}` marker containing `needle`.

    A heading's section runs until the next heading of the same or a higher level;
    a `{{Section}}` marker's section runs until the next marker or heading.
    """
    needle = needle.strip().lower()
    lines = wikitext.splitlines(keepends=True)
    for i, line in enumerate(lines):
        stripped = line.strip()
        heading = _ANY_HEADING_RE.match(stripped)
        marker = _SECTION_LINE_RE.match(stripped)
        if not (heading or marker) or needle not in stripped.lower():
            continue
        level = len(heading.group(1)) if heading else None
        end = len(lines)
        for j in range(i + 1, len(lines)):
            nxt = lines[j].strip()
            h = _ANY_HEADING_RE.match(nxt)
            if h and (level is None or len(h.group(1)) <= level):
                end = j
                break
            if level is None and _SECTION_LINE_RE.match(nxt):
                end = j
                break
        return "".join(lines[i:end]).strip()
    return None


def parse_page(wikitext: str) -> list[LanguageEntry]:
    entries: list[LanguageEntry] = []
    for heading, body in _split_by(_H2_RE, wikitext):
        lang_m = _LANG_RE.search(heading)
        language = lang_m.group(1).strip() if lang_m else "?"
        title = clean(heading.split("(")[0]) or heading
        entry = LanguageEntry(title=title, language=language)
        for pos_heading, pos_body in _split_by(_H3_RE, body):
            entry.parts.append(_parse_part(pos_heading, pos_body))
        entries.append(entry)
    return entries
