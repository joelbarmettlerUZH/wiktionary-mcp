# wiktionary-de-mcp

[![PyPI version](https://img.shields.io/pypi/v/wiktionary-de-mcp)](https://pypi.org/project/wiktionary-de-mcp/)
[![Python versions](https://img.shields.io/pypi/pyversions/wiktionary-de-mcp)](https://pypi.org/project/wiktionary-de-mcp/)
[![CI](https://github.com/joelbarmettlerUZH/wiktionary-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/joelbarmettlerUZH/wiktionary-mcp/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue)](LICENSE)
[![MCP](https://img.shields.io/badge/MCP-server-8A2BE2)](https://modelcontextprotocol.io)

An [MCP](https://modelcontextprotocol.io) server that lets Claude (or any other MCP client)
look things up in the German Wiktionary, [de.wiktionary.org](https://de.wiktionary.org).
Instead of answering from memory, Claude checks the dictionary itself and cites the entry.

It's useful when you want a reliable answer to questions like:

- *„Gibt es das Wort ‚verschlimmbessern'?"*
- *"What's the gender and plural of ‚Band' in the sense of a music group?"*
- *"Is it ‚gewinkt' or ‚gewunken'?"*
- *"Conjugate ‚gehen' in Konjunktiv II."*
- *"Does ‚laufen' take ‚haben' or ‚sein' in the perfect tense?"*

No API key or account is needed.

## Tools

| Tool | What it does |
|---|---|
| `lookup_word` | Checks whether a word exists and returns its dictionary entry: part of speech, gender, inflected forms (plural and cases, comparative and superlative, principal verb forms, auxiliary verb), hyphenation, pronunciation (IPA), meanings, etymology, synonyms, antonyms and example sentences. Upper- and lower-case spellings are tried automatically (*Laufen* vs. *laufen*). If the word isn't in Wiktionary, the result says `NOT FOUND` and suggests similar entries. |
| `get_inflection_table` | The complete conjugation of a verb: every tense, mood and person, plus participles and the imperative. For nouns and adjectives it returns the declension or comparison forms. |
| `search_wiktionary` | Searches titles and full text, with "did you mean" suggestions. Handy for misspellings or for finding compounds that contain a word stem. |
| `get_raw_wikitext` | The raw source of a page, for anything the other tools leave out (translations, references). Returns 8,000 characters at a time and can be narrowed to one section. |

Entries are written in German, as on Wiktionary. The German Wiktionary also documents
words from other languages, explained in German. Use `lookup_word` with
`language: "en"` (or `"Englisch"`, `"French"`, `"*"` for all) to get those.

## Setup

You need [uv](https://docs.astral.sh/uv/getting-started/installation/) installed. uv
downloads and runs the server for you (via `uvx`), so there is nothing else to install.

### Claude Desktop

Open **Settings → Developer → Edit Config**, or edit `claude_desktop_config.json`
directly:

- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

Add the server:

```json
{
  "mcpServers": {
    "wiktionary-de": {
      "command": "uvx",
      "args": ["wiktionary-de-mcp"]
    }
  }
}
```

Restart Claude Desktop, then ask it something about a German word.

If Claude Desktop reports that it can't start the server, it usually can't find `uvx`.
Desktop apps often don't see the `PATH` from your shell. Run `which uvx` (macOS) or
`where uvx` (Windows) and put the full path in `"command"`, for example
`"/Users/you/.local/bin/uvx"`.

### Claude Code

```sh
claude mcp add --scope user wiktionary-de -- uvx wiktionary-de-mcp
```

`--scope user` makes it available in every project. Leave it out to add it to the
current project only.

### Other MCP clients

Any client that supports stdio servers works. Configure the command `uvx` with the
argument `wiktionary-de-mcp`. If you prefer pip, install with `pip install wiktionary-de-mcp`
and use the command `wiktionary-de-mcp`.

### Updating

`uvx` caches the package. To get a newer release, run `uvx wiktionary-de-mcp@latest`
once, or pin a version in the config with `"args": ["wiktionary-de-mcp@0.2.0"]`.

## Good to know

- **Grammar is per word.** Wiktionary records the grammar of individual words: gender,
  plural, cases, conjugation, auxiliary verb. It doesn't explain general rules such as when
  to use the dative or where commas go. Claude answers those from its own knowledge.
- **Wiktionary isn't exhaustive.** Not finding a word doesn't prove it isn't German.
  Many valid compounds (*Donaudampfschifffahrt*) have no entry of their own.
- **Privacy.** The server sends only the words you look up to the public Wikimedia
  API at de.wiktionary.org. Nothing else leaves your machine. Responses are cached in
  memory for 15 minutes.

## Development

```sh
git clone https://github.com/joelbarmettlerUZH/wiktionary-mcp
cd wiktionary-mcp
uv sync
uv run pytest -m "not network"   # offline tests
uv run pytest                    # also runs live tests against de.wiktionary.org
npx @modelcontextprotocol/inspector uv run wiktionary-de-mcp   # try the tools interactively
```

To use your local checkout from Claude Desktop, use this server entry:

```json
"wiktionary-de": {
  "command": "uv",
  "args": ["run", "--directory", "/path/to/wiktionary-mcp", "wiktionary-de-mcp"]
}
```

The code is small: `server.py` defines the tools, `wikitext.py` turns Wiktionary's page
source into readable text, and `client.py` talks to the MediaWiki API.

### Releasing

Every push to `main` runs [`release.yml`](.github/workflows/release.yml). If the version in
`pyproject.toml` isn't on PyPI yet, the workflow tests, builds and publishes the package
with [Trusted Publishing](https://docs.pypi.org/trusted-publishers/) (no stored token). It
then creates a matching `vX.Y.Z` GitHub release. If that version is already on PyPI, it
does nothing. To release:

```sh
uv version --bump patch   # or minor / major; updates pyproject.toml and uv.lock
git commit -am "Release vX.Y.Z" && git push
```

## License

The code is licensed under the [Apache License 2.0](LICENSE). Dictionary content returned
by the tools comes from Wiktionary contributors and is licensed under
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).
