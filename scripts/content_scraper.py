"""Scrape species description and taxonomy from Cornell sources."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 10
USER_AGENT = "ave-del-dia-rss/1.0 (https://github.com/backmind/Bird-of-the-day)"


@dataclass
class SpeciesContent:
    ebird_description: str
    bow_intro: str
    taxonomy: dict


def _scrape_ebird_species_page(
    species_code: str, locale: str = "es"
) -> tuple[str, dict]:
    """Scrape description text and taxonomy from the eBird species page."""
    url = f"https://ebird.org/species/{species_code}"
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": USER_AGENT, "Accept-Language": locale},
            params={"locale": locale},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
    except Exception:
        logger.warning("Failed to fetch eBird species page for %s", species_code, exc_info=True)
        return ("", {})

    soup = BeautifulSoup(resp.text, "html.parser")
    description = ""
    taxonomy = {}

    # Try og:description meta tag first (usually the Merlin ID text)
    og_desc = soup.find("meta", property="og:description")
    if og_desc and og_desc.get("content"):
        description = og_desc["content"].strip()

    # Try __NEXT_DATA__ JSON for richer data
    next_data = soup.find("script", id="__NEXT_DATA__")
    if next_data and next_data.string:
        try:
            data = json.loads(next_data.string)
            props = data.get("props", {}).get("pageProps", {})

            # Try to extract description from page props
            species_data = props.get("species", {})
            if not description:
                for key in ("shortDescription", "description", "idSummary"):
                    if species_data.get(key):
                        description = species_data[key].strip()
                        break

            # Extract taxonomy info
            if species_data:
                taxonomy = {
                    k: species_data[k]
                    for k in ("order", "familySciName", "familyComName", "sciName", "comName")
                    if k in species_data
                }
        except (json.JSONDecodeError, AttributeError):
            logger.debug("Failed to parse __NEXT_DATA__ for %s", species_code)

    return (description, taxonomy)


def _scrape_bow_intro(species_code: str) -> str:
    """Scrape the introduction paragraph from Birds of the World (pre-paywall)."""
    url = f"https://birdsoftheworld.org/bow/species/{species_code}/cur/introduction"
    try:
        resp = requests.get(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept-Language": "es",
            },
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
    except Exception:
        logger.debug("Failed to fetch BoW page for %s", species_code, exc_info=True)
        return ""

    soup = BeautifulSoup(resp.text, "html.parser")

    # Look for the introduction paragraph in main content area
    for selector in ("article p", ".main-content p", "#content p", "p"):
        paragraphs = soup.select(selector)
        for p in paragraphs:
            text = p.get_text(strip=True)
            # Skip very short paragraphs (nav elements, labels)
            if len(text) > 100:
                return text

    return ""


def scrape_species_content(
    species_code: str, locale: str = "es"
) -> SpeciesContent:
    """Fetch all available content for a species."""
    description, taxonomy = _scrape_ebird_species_page(species_code, locale)
    bow_intro = _scrape_bow_intro(species_code)

    return SpeciesContent(
        ebird_description=description,
        bow_intro=bow_intro,
        taxonomy=taxonomy,
    )


def load_cached_content(
    species_code: str, cache_dir: str = "cache"
) -> SpeciesContent | None:
    path = Path(cache_dir) / f"{species_code}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return SpeciesContent(
            ebird_description=data.get("ebird_description", ""),
            bow_intro=data.get("bow_intro", ""),
            taxonomy=data.get("taxonomy", {}),
        )
    except (json.JSONDecodeError, KeyError):
        logger.warning("Invalid cache file for %s, ignoring", species_code)
        return None


def save_cached_content(
    species_code: str, content: SpeciesContent, cache_dir: str = "cache"
) -> None:
    path = Path(cache_dir) / f"{species_code}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = asdict(content)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
