"""Cuando Cornell no contesta, la foto sale de Wikimedia Commons.

Desde el 2026-09-22 la página de especie de eBird devuelve al runner la
portada genérica de eBird casi siempre, y la API de Macaulay lleva detrás
de una pasarela anti-bots desde el 2026-08-30. Tres de cuatro entradas
seguidas salieron sin foto tras agotar 50 re-tiradas. Commons no depende
de Cornell, y su imagen principal de cada artículo viene con autor y
licencia.
"""

from bs4 import BeautifulSoup

from scripts import content_scraper, image_fetcher
from scripts.image_fetcher import CDN_BASE


class _Resp:
    def __init__(self, payload=None, text=""):
        self._payload = payload
        self.text = text

    def raise_for_status(self):
        pass

    def json(self):
        if self._payload is None:
            raise ValueError("no JSON")
        return self._payload


class _WikiSession:
    """Contesta la API de MediaWiki; todo lo demás, con la portada genérica
    de eBird o con HTML en vez de JSON, como hace hoy Cornell."""

    def __init__(self, pageimage="Microeca_hemixantha.jpg", licence="CC BY-SA 4.0"):
        self.pageimage = pageimage
        self.licence = licence
        self.calls = []

    def get(self, url, params=None, timeout=None, **kwargs):
        self.calls.append((url, dict(params or {})))
        if "wikipedia.org/w/api.php" in url:
            if params.get("prop") == "pageimages":
                page = {"title": "Microeca hemixantha"}
                if self.pageimage:
                    page["pageimage"] = self.pageimage
                return _Resp({"query": {"pages": [page]}})
            meta = {"Artist": {"value": '<a href="//x">Ana <b>Pérez</b></a>'}}
            if self.licence:
                meta["LicenseShortName"] = {"value": self.licence}
            return _Resp({"query": {"pages": [{"imageinfo": [{
                "url": "https://upload.wikimedia.org/full.jpg",
                "thumburl": "https://upload.wikimedia.org/900px.jpg",
                "extmetadata": meta,
            }]}]}})
        if "ebird.org/species/" in url:
            return _Resp(text=_GENERIC_EBIRD)
        return _Resp(text="<html>challenge</html>")


_GENERIC_EBIRD = (
    '<html><head>'
    '<meta property="og:description" content="eBird transforms your bird '
    'sightings into science and conservation. Plan trips, find birds."/>'
    f'<meta property="og:image" content="{CDN_BASE}/123456/1200"/>'
    '<meta property="og:url" content="https://ebird.org/home"/>'
    '</head><body></body></html>'
)


def test_commons_answers_when_cornell_does_not():
    session = _WikiSession()
    result = image_fetcher.fetch_image(
        "gobfly2", session, scientific_name="Microeca hemixantha"
    )
    assert result.url == "https://upload.wikimedia.org/900px.jpg"
    assert result.photographer == "Ana Pérez"
    assert result.attribution == "Ana Pérez / Wikimedia Commons (CC BY-SA 4.0)"
    assert "gobfly2" in result.search_url


def test_the_generic_ebird_hero_is_not_this_bird():
    """La portada genérica trae un og:image con id. Usarlo publicaría la
    foto de otra ave: tiene que caer a la siguiente vía."""
    session = _WikiSession()
    assert image_fetcher._try_ebird_og_image("gobfly2", session) is None


def test_a_file_without_a_licence_is_not_published():
    session = _WikiSession(licence="")
    result = image_fetcher.fetch_image(
        "gobfly2", session, scientific_name="Microeca hemixantha"
    )
    assert result.url is None


def test_an_article_without_a_lead_image_leaves_the_gap():
    session = _WikiSession(pageimage=None)
    result = image_fetcher.fetch_image(
        "gobfly2", session, scientific_name="Microeca hemixantha"
    )
    assert result.url is None
    assert result.search_url


def test_no_scientific_name_skips_commons():
    session = _WikiSession()
    result = image_fetcher.fetch_image("gobfly2", session)
    assert result.url is None
    assert not any("wikipedia" in url for url, _ in session.calls)


def test_the_generic_ebird_description_is_not_cached_as_text():
    """El eslogan de eBird acabó en 140 cachés como fallback_text."""
    assert content_scraper._fetch_ebird_og_description(
        "gobfly2", _WikiSession(), locale="es"
    ) == ""


def _soup(head):
    return BeautifulSoup(f"<html><head>{head}</head></html>", "html.parser")


def test_species_page_detection():
    ok = '<meta property="og:url" content="https://ebird.org/species/eurrob1"/>'
    other = '<link rel="canonical" href="https://ebird.org/home"/>'
    assert image_fetcher.is_ebird_species_page(_soup(ok), "eurrob1")
    assert not image_fetcher.is_ebird_species_page(_soup(other), "eurrob1")
    # Una página que no dice nada de sí misma se acepta, como antes.
    assert image_fetcher.is_ebird_species_page(_soup(""), "eurrob1")
