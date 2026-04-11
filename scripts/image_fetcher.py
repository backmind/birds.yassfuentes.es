"""Multi-strategy image fetcher for bird species photos."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 10
USER_AGENT = "ave-del-dia-rss/1.0 (https://github.com/backmind/Bird-of-the-day)"
CDN_BASE = "https://cdn.download.ams.birds.cornell.edu/api/v1/asset"
ML_SEARCH_BASE = "https://search.macaulaylibrary.org"


@dataclass
class ImageResult:
    url: str | None
    asset_id: str | None
    attribution: str
    search_url: str


def _ml_search_url(species_code: str) -> str:
    return (
        f"{ML_SEARCH_BASE}/catalog"
        f"?taxonCode={species_code}&mediaType=photo&sort=rating_rank_desc"
    )


def _try_macaulay_api(species_code: str) -> ImageResult | None:
    """Strategy 1: Macaulay Library Search API."""
    url = (
        f"{ML_SEARCH_BASE}/api/v1/search"
        f"?taxonCode={species_code}&mediaType=photo&sort=rating_rank_desc&count=1"
    )
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()

        # Response may be a dict with "results" key or a direct list
        results = data if isinstance(data, list) else data.get("results", [])
        if not results:
            return None

        first = results[0]
        asset_id = str(first.get("assetId") or first.get("catalogId") or first.get("mlCatalogNumber", ""))
        if not asset_id:
            return None

        photographer = first.get("userDisplayName", "").strip()
        attribution = f"{photographer} / Macaulay Library" if photographer else "Macaulay Library"

        return ImageResult(
            url=f"{CDN_BASE}/{asset_id}/900/600",
            asset_id=asset_id,
            attribution=attribution,
            search_url=_ml_search_url(species_code),
        )
    except Exception:
        logger.debug("Macaulay API strategy failed for %s", species_code, exc_info=True)
        return None


def _try_ebird_og_image(species_code: str) -> ImageResult | None:
    """Strategy 2: Extract og:image from eBird species page."""
    url = f"https://ebird.org/species/{species_code}"
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        og = soup.find("meta", property="og:image")
        if not og or not og.get("content"):
            return None

        og_url = og["content"]
        match = re.search(r"/asset/(\d+)", og_url)
        if not match:
            # og:image exists but isn't a Macaulay CDN URL; use it as-is
            return ImageResult(
                url=og_url,
                asset_id=None,
                attribution="Macaulay Library / Cornell Lab of Ornithology",
                search_url=_ml_search_url(species_code),
            )

        asset_id = match.group(1)
        return ImageResult(
            url=f"{CDN_BASE}/{asset_id}/900/600",
            asset_id=asset_id,
            attribution="Macaulay Library / Cornell Lab of Ornithology",
            search_url=_ml_search_url(species_code),
        )
    except Exception:
        logger.debug("og:image strategy failed for %s", species_code, exc_info=True)
        return None


def _fallback(species_code: str) -> ImageResult:
    """Strategy 3: No image, just a link to Macaulay Library search."""
    return ImageResult(
        url=None,
        asset_id=None,
        attribution="Macaulay Library / Cornell Lab of Ornithology",
        search_url=_ml_search_url(species_code),
    )


def fetch_image(species_code: str) -> ImageResult:
    """Fetch the best available image for a species, with fallback chain."""
    for strategy in (_try_macaulay_api, _try_ebird_og_image):
        result = strategy(species_code)
        if result is not None:
            return result
    return _fallback(species_code)
