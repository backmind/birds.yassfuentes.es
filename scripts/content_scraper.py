"""Scrape species description from public Spanish-friendly sources.

Source chain (first non-English match wins for the main description):

  1. eBird species page → ``og:description`` with ``?locale=es``.
     Confirmed via inspection that this carries the Merlin identification
     text, translated to Spanish for species that have a translation. The
     page has no ``__NEXT_DATA__`` block; ``og:description`` is the source.

  2. Spanish Wikipedia REST summary API. The eBird translation is missing
     for many non-Iberian species (e.g. Australian endemics), so we fall
     back to ``es.wikipedia.org/api/rest_v1/page/summary/{sciName}`` which
     follows taxonomic redirects automatically.

  3. Birds of the World introduction paragraph. BoW serves Spanish via
     ``Accept-Language: es`` for species that have an open-access intro,
     and is used as enrichment regardless of the main description source.

The page also requires cookies because of eBird's CAS gateway, so callers
should pass a ``Session`` shared with ``image_fetcher``.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from scripts.image_fetcher import new_session

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 15

# Hard cap on the description shown to the reader. Applied uniformly after
# the source chain picks a winner. BoW intros can run to 2000+ chars and
# would otherwise dominate the hero layout. 700 chars is ~5-6 lines at the
# default body font size.
MAX_DESCRIPTION_CHARS = 700


def _truncate_at_sentence_boundary(
    text: str, max_chars: int = MAX_DESCRIPTION_CHARS
) -> str:
    """Trim ``text`` to ``max_chars`` at the last sentence boundary.

    If a sentence-ending punctuation mark is found in the upper 60% of the
    cut, the trim happens there. Otherwise we hard-cut on the last word
    boundary and append a horizontal ellipsis. The result never exceeds
    ``max_chars`` characters.
    """
    if not text or len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    floor = int(max_chars * 0.6)
    best = -1
    for boundary in (". ", "! ", "? ", "… ", ".\n", "!\n", "?\n"):
        idx = cut.rfind(boundary)
        if idx > best:
            best = idx + len(boundary) - 1  # keep the punctuation, drop the space
    if best >= floor:
        return cut[: best + 1].strip()
    # No clean sentence boundary high enough — hard cut on last word.
    word_cut = cut.rsplit(" ", 1)[0].strip()
    return word_cut + "…"

# Stopwords used to detect whether a snippet is Spanish or English. They
# differ enough between languages that 5+ words of either side suffices.
_ES_STOPWORDS = {
    "de", "la", "el", "en", "con", "que", "una", "y", "es", "se", "del",
    "los", "las", "como", "más", "está", "su", "por", "para", "este",
    "esta", "son", "ave", "especie",
}
_EN_STOPWORDS = {
    "the", "of", "and", "in", "to", "is", "with", "for", "on", "this",
    "that", "at", "from", "by", "an", "are", "be", "found",
}


@dataclass
class SpeciesContent:
    description: str
    description_source: str  # "ebird" | "wikipedia" | ""
    bow_intro: str
    taxonomy: dict
    wikipedia_url: str = ""       # canonical URL of the Wikipedia article
    wikipedia_language: str = ""  # "es" | "en" | "" (the lang we resolved to)


def _is_spanish(text: str) -> bool:
    """Heuristic: more Spanish stopwords than English ones in the text."""
    if not text:
        return False
    words = text.lower().split()
    if not words:
        return False
    es = sum(1 for w in words if w.strip(".,;:¡!¿?()'\"") in _ES_STOPWORDS)
    en = sum(1 for w in words if w.strip(".,;:!?()'\"") in _EN_STOPWORDS)
    return es > en


def _fetch_ebird_og_description(
    species_code: str, session: requests.Session, locale: str = "es"
) -> str:
    """Return the Merlin ID text from eBird's og:description meta tag."""
    url = f"https://ebird.org/species/{species_code}"
    try:
        resp = session.get(url, params={"locale": locale}, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException:
        logger.warning(
            "Failed to fetch eBird species page for %s", species_code, exc_info=True
        )
        return ""

    soup = BeautifulSoup(resp.text, "html.parser")
    og = soup.find("meta", property="og:description")
    if og and og.get("content"):
        return og["content"].strip()
    return ""


def _fetch_wikipedia(
    scientific_name: str, language: str, session: requests.Session
) -> dict | None:
    """Look up a Wikipedia REST summary in the given language.

    Returns a ``{"extract": str, "url": str}`` dict on success, or ``None``
    if the article doesn't exist (404), is a disambiguation page, or the
    request fails. The REST summary endpoint follows taxonomic redirects
    automatically (e.g. ``Meliphaga fordiana`` → ``Microptilotis fordianus``).
    """
    if not scientific_name:
        return None
    title = scientific_name.replace(" ", "_")
    url = f"https://{language}.wikipedia.org/api/rest_v1/page/summary/{title}"
    try:
        resp = session.get(
            url,
            headers={"Accept": "application/json"},
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError):
        logger.debug(
            "Wikipedia %s lookup failed for %s", language, scientific_name, exc_info=True
        )
        return None

    if data.get("type") == "disambiguation":
        return None
    extract = (data.get("extract") or "").strip()
    canonical_url = (
        data.get("content_urls", {}).get("desktop", {}).get("page", "")
    )
    if not canonical_url:
        return None
    return {"extract": extract, "url": canonical_url}


def _fetch_wikipedia_es(scientific_name: str, session: requests.Session) -> str:
    """Backwards-compat wrapper used by ``seed_mock.py``'s deep probe.

    Returns just the extract string, mirroring the old API. New code should
    call :func:`_fetch_wikipedia` directly to get both extract and URL.
    """
    data = _fetch_wikipedia(scientific_name, "es", session)
    return data["extract"] if data else ""


# Phrases that mark BoW promo/login banners (we want the real intro instead).
_BOW_BANNER_PHRASES = (
    "subscriber",
    "suscriptor",
    "sign in",
    "inicie sesión",
    "iniciar sesión",
    "full content is available",
    "recurso científico de acceso",
    "global alliance of nature organizations",
)


def _fetch_bow_intro(species_code: str, session: requests.Session) -> str:
    """Return the public Spanish introduction text from Birds of the World."""
    url = f"https://birdsoftheworld.org/bow/species/{species_code}/cur/introduction"
    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException:
        logger.debug("Failed to fetch BoW page for %s", species_code, exc_info=True)
        return ""

    soup = BeautifulSoup(resp.text, "html.parser")
    collected: list[str] = []
    for p in soup.find_all("p"):
        # Real intro paragraphs are unstyled. Banners and promo blocks all
        # carry CSS classes.
        if p.get("class"):
            continue
        text = p.get_text(strip=True)
        if len(text) < 100:
            continue
        lowered = text.lower()
        if any(phrase in lowered for phrase in _BOW_BANNER_PHRASES):
            continue
        collected.append(text)
        if len(collected) >= 2:
            break

    intro = " ".join(collected)
    # If BoW served us English (e.g. when no es translation exists), drop it.
    if intro and not _is_spanish(intro):
        return ""
    return intro


def scrape_species_content(
    species_code: str,
    scientific_name: str = "",
    locale: str = "es",
    session: requests.Session | None = None,
) -> SpeciesContent:
    """Run the source chain and return the best Spanish content found.

    Also resolves the canonical Wikipedia URL — preferring the configured
    locale, falling back to English. The URL is captured even when the
    description ends up coming from eBird, so the rendered ``plate-foot``
    can always link to Wikipedia.
    """
    sess = session or new_session()

    description = ""
    description_source = ""

    ebird_text = _fetch_ebird_og_description(species_code, sess, locale=locale)

    # Probe Wikipedia in the configured locale once. We may use both the
    # extract (if eBird gave us nothing) and the URL (always).
    wiki_target = _fetch_wikipedia(scientific_name, locale, sess)

    if ebird_text and _is_spanish(ebird_text):
        description = ebird_text
        description_source = "ebird"
        logger.debug("eBird text is Spanish for %s", species_code)
    else:
        if ebird_text:
            logger.info(
                "eBird text not in target language for %s, trying Wikipedia", species_code
            )
        if wiki_target and wiki_target["extract"]:
            description = wiki_target["extract"]
            description_source = "wikipedia"
            logger.info("Using Wikipedia %s summary for %s", locale, species_code)
        else:
            logger.info(
                "No %s source available for %s; description will be empty",
                locale, species_code,
            )

    # Resolve the Wikipedia URL: prefer target language, fall back to English.
    wikipedia_url = ""
    wikipedia_language = ""
    if wiki_target:
        wikipedia_url = wiki_target["url"]
        wikipedia_language = locale
    elif locale != "en":
        wiki_en = _fetch_wikipedia(scientific_name, "en", sess)
        if wiki_en:
            wikipedia_url = wiki_en["url"]
            wikipedia_language = "en"
            logger.info("Wikipedia URL fallback → en for %s", species_code)

    bow_intro = _fetch_bow_intro(species_code, sess)

    # Apply the layout rail uniformly to every source.
    raw_desc_len = len(description)
    description = _truncate_at_sentence_boundary(description)
    raw_bow_len = len(bow_intro)
    bow_intro = _truncate_at_sentence_boundary(bow_intro)
    if description and raw_desc_len != len(description):
        logger.info(
            "description: source=%s truncated %d → %d chars",
            description_source, raw_desc_len, len(description),
        )
    if bow_intro and raw_bow_len != len(bow_intro):
        logger.info(
            "bow_intro: truncated %d → %d chars", raw_bow_len, len(bow_intro)
        )

    return SpeciesContent(
        description=description,
        description_source=description_source,
        bow_intro=bow_intro,
        taxonomy={},
        wikipedia_url=wikipedia_url,
        wikipedia_language=wikipedia_language,
    )


def _content_cache_path(species_code: str, cache_dir: str) -> Path:
    return Path(cache_dir) / f"{species_code}.json"


def load_cached_content(
    species_code: str, cache_dir: str = "cache"
) -> SpeciesContent | None:
    path = _content_cache_path(species_code, cache_dir)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.warning("Invalid content cache for %s, ignoring", species_code)
        return None
    return SpeciesContent(
        description=data.get("description", data.get("ebird_description", "")),
        description_source=data.get("description_source", ""),
        bow_intro=data.get("bow_intro", ""),
        taxonomy=data.get("taxonomy", {}),
        wikipedia_url=data.get("wikipedia_url", ""),
        wikipedia_language=data.get("wikipedia_language", ""),
    )


def save_cached_content(
    species_code: str, content: SpeciesContent, cache_dir: str = "cache"
) -> None:
    """Cache the scrape result. Saves whenever ANY field has content so that
    a species with no description but a Wikipedia URL still gets cached
    (avoiding redundant probes on subsequent runs)."""
    if (
        not content.description
        and not content.bow_intro
        and not content.wikipedia_url
    ):
        return
    path = _content_cache_path(species_code, cache_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(asdict(content), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
