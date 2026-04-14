"""Tests for name_linker.process_description and extract_name_pairs."""

from scripts.name_linker import extract_name_pairs, process_description


def test_empty_text():
    assert process_description("", {}, {}, {}) == ""


def test_no_index_escapes_html():
    assert process_description("<b>bold</b>", {}, {}, {}) == "&lt;b&gt;bold&lt;/b&gt;"


def test_substitutes_english_name():
    eni = {"Masked Booby": "masboo"}
    c2l = {"masboo": "Piquero Enmascarado"}
    result = process_description(
        "The Masked Booby is a seabird.", eni, c2l, {}
    )
    assert "Piquero Enmascarado" in result
    assert "Masked Booby" not in result
    assert "ebird.org/species/masboo" in result


def test_links_to_published_entry():
    eni = {"Masked Booby": "masboo"}
    c2l = {"masboo": "Piquero Enmascarado"}
    anchors = {"masboo": "archive.html#bird-masboo-2026-04-13"}
    result = process_description(
        "The Masked Booby is a seabird.", eni, c2l, anchors
    )
    assert '<a href="archive.html#bird-masboo-2026-04-13">' in result
    assert "Piquero Enmascarado" in result
    assert "(eBird)" not in result


def test_no_match_returns_escaped():
    eni = {"Masked Booby": "masboo"}
    result = process_description(
        "A plain description with no species.", eni, {}, {}
    )
    assert result == "A plain description with no species."


def test_html_in_description_escaped():
    eni = {"Masked Booby": "masboo"}
    c2l = {"masboo": "Piquero"}
    result = process_description(
        "The <em>Masked Booby</em> nests here.", eni, c2l, {}
    )
    assert "&lt;em&gt;" in result
    assert "Piquero" in result


def test_localized_name_linked():
    """Localized names in the text get linked even without English match."""
    c2l = {"masboo": "Piquero Enmascarado"}
    anchors = {"masboo": "archive.html#bird-masboo-2026-04-13"}
    result = process_description(
        "El Piquero Enmascarado anida en islas.", {}, c2l, anchors
    )
    assert '<a href="archive.html#bird-masboo-2026-04-13">' in result
    assert "Piquero Enmascarado" in result


def test_localized_name_ebird_fallback():
    """Unpublished localized names fall back to eBird."""
    c2l = {"mircab": "Mirlo Capiblanco"}
    result = process_description(
        "El Mirlo Capiblanco habita en montañas.", {}, c2l, {}, "es"
    )
    assert "ebird.org/species/mircab?siteLanguage=es" in result
    assert "Mirlo Capiblanco" in result


def test_no_double_link():
    """English match and locale match for the same species don't collide."""
    eni = {"Masked Booby": "masboo"}
    c2l = {"masboo": "Piquero Enmascarado"}
    result = process_description(
        "The Masked Booby, or Piquero Enmascarado, is large.",
        eni, c2l, {}
    )
    # Both should be linked, not duplicated
    assert result.count("ebird.org/species/masboo") == 2


def test_extract_name_pairs():
    eni = {"Masked Booby": "masboo", "Ring Ouzel": "rinouz1"}
    c2l = {"masboo": "Piquero Enmascarado", "rinouz1": "Mirlo Capiblanco"}
    pairs = extract_name_pairs(
        "The Masked Booby and Ring Ouzel share an island.", eni, c2l
    )
    assert pairs == {
        "Masked Booby": "Piquero Enmascarado",
        "Ring Ouzel": "Mirlo Capiblanco",
    }


def test_extract_name_pairs_empty():
    pairs = extract_name_pairs("No birds here.", {}, {})
    assert pairs == {}
