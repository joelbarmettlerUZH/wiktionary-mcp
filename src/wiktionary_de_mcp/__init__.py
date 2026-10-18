"""MCP server for the German Wiktionary (de.wiktionary.org)."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("wiktionary-de-mcp")
except PackageNotFoundError:  # running from a source checkout without install
    __version__ = "0.0.0"
