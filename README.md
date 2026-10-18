# wiktionary-de-mcp

[![PyPI](https://img.shields.io/pypi/v/wiktionary-de-mcp)](https://pypi.org/project/wiktionary-de-mcp/)
[![CI](https://github.com/joelbarmettlerUZH/wiktionary-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/joelbarmettlerUZH/wiktionary-mcp/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue)](LICENSE)

An [MCP](https://modelcontextprotocol.io) server for the German Wiktionary
([de.wiktionary.org](https://de.wiktionary.org)). Ask Claude things like:

- *„Gibt es das Wort ‚verschlimmbessern'?"*
- *"What's the plural and gender of Haus?"*
- *"Conjugate 'gehen' in Präteritum Konjunktiv II."*
- *"Is it 'gewinkt' or 'gewunken'?"*

## Tools

| Tool | What it does |
|---|---|
| `lookup_word` | Checks whether a word exists. Returns part of speech, gender, inflected forms, hyphenation, IPA, meanings, etymology, synonyms and examples. Tries other capitalizations automatically. If nothing is found it suggests similar words. |
| `get_inflection_table` | Full conjugation table for a verb (from the `Flexion:` page), or the declension/comparison forms for a noun or adjective. |
| `search_wiktionary` | Prefix and full-text search, plus "did you mean" suggestions. |
| `get_raw_wikitext` | The page's raw source, as a fallback for anything the other tools leave out (translations, references). Returns 8,000 characters at a time, can be paged with `offset`, and can be narrowed to one `section`. |

No API key needed. Responses are cached in memory for 15 minutes.

## Install

Requires [uv](https://docs.astral.sh/uv/getting-started/installation/).

### Claude Desktop

Edit `claude_desktop_config.json`
(macOS: `~/Library/Application Support/Claude/`, Windows: `%APPDATA%\Claude\`):

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

Then restart Claude Desktop. If it can't find `uvx`, use the absolute path from
`which uvx` (for example `/Users/you/.local/bin/uvx`). GUI apps often don't inherit
your shell's `PATH`.

### Claude Code

```sh
claude mcp add --scope user wiktionary-de -- uvx wiktionary-de-mcp
```

## Development

```sh
uv sync
uv run pytest                 # unit tests + live end-to-end tests
uv run pytest -m "not network" # offline only
npx @modelcontextprotocol/inspector uv run wiktionary-de-mcp   # interactive tool tester

# Use a local checkout from Claude Desktop / Code:
#   "command": "uv", "args": ["run", "--directory", "/path/to/wiktionary-mcp", "wiktionary-de-mcp"]
```

### Releasing

Every push to `main` runs [`release.yml`](.github/workflows/release.yml). If the version in
`pyproject.toml` isn't on PyPI yet, it runs the tests, builds, publishes to PyPI with
[Trusted Publishing](https://docs.pypi.org/trusted-publishers/) (no stored token), and
creates a `vX.Y.Z` GitHub release. Otherwise it does nothing. To release:

```sh
uv version --bump patch   # or minor / major; updates pyproject.toml and uv.lock
git commit -am "Release vX.Y.Z" && git push
```

## License

Code: Apache License 2.0. Dictionary content returned by the tools comes from Wiktionary, under
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).
