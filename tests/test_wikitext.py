from wiktionary_de_mcp.client import html_tables_to_text
from wiktionary_de_mcp.wikitext import (
    clean,
    extract_section,
    normalize_language,
    parse_page,
    split_template,
)

HAUS = """{{Siehe auch|[[haus]]}}
{{Wort der Woche|46|2006}}

== Haus ({{Sprache|Deutsch}}) ==
=== {{Wortart|Substantiv|Deutsch}}, {{n}} ===

{{Deutsch Substantiv Übersicht
|Genus=n
|Nominativ Singular=Haus
|Nominativ Plural=Häuser
|Dativ Singular=Haus
|Dativ Singular*=Hause
|Bild 1=Foo.jpg|mini|1|ein ''Haus'' im [[modern]]en [[Baustil]]
}}

{{Worttrennung}}
:Haus, {{Pl.}} Häu·ser

{{Aussprache}}
:{{IPA}} {{Lautschrift|haʊ̯s}}
:{{Hörbeispiele}} {{Audio|De-Haus.ogg}}

{{Bedeutungen}}
:[1] zu einem bestimmten Zweck erbautes [[Gebäude]]
:[4] {{K|ugs.}} Gesamtheit der Bewohner<ref name="x">{{Ref-Duden}}</ref>

{{Herkunft}}
:althochdeutsch ''{{Ü|goh|hūs}}''

==== {{Übersetzungen}} ====
{{Ü-Tabelle|Ü-links=
*{{en}}: [1] {{Ü|en|house}}
}}

== house ({{Sprache|Englisch}}) ==
=== {{Wortart|Substantiv|Englisch}} ===
{{Bedeutungen}}
:[1] [[Haus]]
"""


def test_clean_links_templates_refs():
    assert clean("[[Gebäude]]") == "Gebäude"
    assert clean("[[gehen|ging]]") == "ging"
    assert clean("{{K|ugs.|scherzhaft}} Mensch") == "(ugs., scherzhaft): Mensch"
    assert clean("x<ref>{{Ref-Duden}}</ref> y") == "x y"
    assert clean("''kursiv''") == "kursiv"
    assert clean("{{Pl.}} Häu·ser") == "Pl. Häu·ser"


def test_split_template_respects_nesting():
    name, pos, named = split_template("K|[[a|b]]|{{x|y}}|ft=z")
    assert name == "K"
    assert pos == ["[[a|b]]", "{{x|y}}"]
    assert named == {"ft": "z"}


def test_parse_page_structure():
    entries = parse_page(HAUS)
    assert [(e.title, e.language) for e in entries] == [("Haus", "Deutsch"), ("house", "Englisch")]

    noun = entries[0].parts[0]
    assert noun.heading == "Substantiv, n"
    assert noun.forms["Nominativ Plural"] == "Häuser"
    assert noun.forms["Dativ Singular*"] == "Hause"
    assert not any(k.startswith("Bild") for k in noun.forms)
    assert noun.sections["Worttrennung"] == ["Haus, Pl. Häu·ser"]
    assert noun.sections["Aussprache"] == ["IPA: haʊ̯s"]
    assert noun.sections["Bedeutungen"] == [
        "[1] zu einem bestimmten Zweck erbautes Gebäude",
        "[4] (ugs.): Gesamtheit der Bewohner",
    ]
    assert noun.sections["Herkunft"] == ["althochdeutsch hūs"]
    # Translations section must be cut off.
    assert "Übersetzungen" not in noun.sections
    assert all("house" not in line for lines in noun.sections.values() for line in lines)


def test_html_tables_to_text():
    html = (
        "<style>.x{}</style><h3>Präsens</h3><table>"
        "<tr><th>Person</th><th>Indikativ</th></tr>"
        "<tr><td>1. Person Singular</td><td>ich gehe</td></tr></table>"
    )
    assert html_tables_to_text(html) == (
        "### Präsens\nPerson | Indikativ\n1. Person Singular | ich gehe"
    )


def test_normalize_language():
    assert normalize_language("en") == "Englisch"
    assert normalize_language("English") == "Englisch"
    assert normalize_language("französisch") == "Französisch"
    assert normalize_language("all") == "*"
    assert normalize_language("Plattdeutsch") == "Plattdeutsch"


def test_extract_section():
    translations = extract_section(HAUS, "Übersetzungen")
    assert translations.startswith("==== {{Übersetzungen}} ====")
    assert "house" in translations
    # A level-4 section stops at the next level-2 heading.
    assert "Englisch}}) ==" not in translations

    assert extract_section(HAUS, "Herkunft") == "{{Herkunft}}\n:althochdeutsch ''{{Ü|goh|hūs}}''"
    assert extract_section(HAUS, "Englisch").startswith("== house")
    assert extract_section(HAUS, "nonexistent") is None
