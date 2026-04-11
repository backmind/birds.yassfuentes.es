"""eBird API v2 client and species selection logic."""

from __future__ import annotations

import hashlib
import logging
import os
import random
import sys

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://api.ebird.org/v2"
REQUEST_TIMEOUT = 15

_taxonomy_cache: list[dict] | None = None


def get_api_key() -> str:
    key = os.environ.get("EBIRD_API_KEY", "")
    if not key:
        logger.error("EBIRD_API_KEY environment variable is not set")
        sys.exit(1)
    return key


def _headers() -> dict[str, str]:
    return {"x-ebirdapitoken": get_api_key()}


def get_recent_observations(
    region: str, back: int = 14, locale: str = "es"
) -> list[dict]:
    url = f"{BASE_URL}/data/obs/{region}/recent"
    params = {
        "back": back,
        "cat": "species",
        "hotspot": "false",
        "includeProvisional": "false",
        "maxResults": 200,
        "locale": locale,
    }
    try:
        resp = requests.get(url, headers=_headers(), params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.HTTPError as e:
        logger.warning("HTTP %s from %s", e.response.status_code, url)
        return []
    except (requests.exceptions.RequestException, ValueError) as e:
        logger.warning("Error fetching %s: %s", url, e)
        return []


def get_full_taxonomy(locale: str = "es") -> list[dict]:
    global _taxonomy_cache
    if _taxonomy_cache is not None:
        return _taxonomy_cache

    url = f"{BASE_URL}/ref/taxonomy/ebird"
    params = {"fmt": "json", "locale": locale, "cat": "species"}
    resp = requests.get(url, headers=_headers(), params=params, timeout=60)
    resp.raise_for_status()
    _taxonomy_cache = resp.json()
    return _taxonomy_cache


def _date_seed(date_str: str, salt: str = "") -> int:
    return int(hashlib.sha256((date_str + salt).encode()).hexdigest(), 16)


def _pick_pool(pools: list[dict], date_str: str) -> dict:
    """Deterministically select a pool based on the date."""
    seed = _date_seed(date_str)
    rng = random.Random(seed)
    weights = [p["weight"] for p in pools]
    return rng.choices(pools, weights=weights, k=1)[0]


def _get_region_for_pool(pool: dict, date_str: str) -> str | None:
    pool_type = pool["type"]
    if pool_type == "regional":
        return pool["region"]
    if pool_type == "europe_random":
        seed = _date_seed(date_str, salt=pool["id"])
        rng = random.Random(seed)
        return rng.choice(pool["countries"])
    return None  # global_taxonomy


def _select_from_observations(
    observations: list[dict],
    history_codes: list[str],
    date_str: str,
    pool_id: str,
) -> dict | None:
    """Select a species from observation data, biased toward rarer species."""
    # Aggregate counts per species
    species_map: dict[str, dict] = {}
    for obs in observations:
        code = obs.get("speciesCode")
        if not code or code in history_codes:
            continue
        if code not in species_map:
            species_map[code] = {
                "speciesCode": code,
                "comName": obs.get("comName", code),
                "sciName": obs.get("sciName", ""),
                "total_count": 0,
            }
        species_map[code]["total_count"] += max(obs.get("howMany") or 1, 1)

    if not species_map:
        return None

    candidates = list(species_map.values())
    # Rarity weighting: inverse of total count
    scores = [1.0 / c["total_count"] for c in candidates]
    seed = _date_seed(date_str, salt=pool_id)
    rng = random.Random(seed)
    selected = rng.choices(candidates, weights=scores, k=1)[0]
    return {
        "speciesCode": selected["speciesCode"],
        "comName": selected["comName"],
        "sciName": selected["sciName"],
    }


def _select_from_taxonomy(
    taxonomy: list[dict], history_codes: list[str], date_str: str
) -> dict | None:
    """Select a random species from the full taxonomy."""
    filtered = [sp for sp in taxonomy if sp.get("speciesCode") not in history_codes]
    if not filtered:
        filtered = taxonomy  # extreme edge case: all 17k seen recently

    seed = _date_seed(date_str, salt="global")
    rng = random.Random(seed)
    sp = rng.choice(filtered)
    return {
        "speciesCode": sp["speciesCode"],
        "comName": sp.get("comName", sp["speciesCode"]),
        "sciName": sp.get("sciName", ""),
    }


def select_species(
    config: dict, history_codes: list[str], date_str: str
) -> dict:
    """Select the bird of the day.

    Picks a weighted pool, fetches candidates, deduplicates against history,
    and selects with rarity bias. Falls back through other pools on failure.
    """
    pools = config["pools"]
    back = config.get("back_days", 14)
    locale = config.get("ebird_locale", "es")

    # Deterministic pool selection
    chosen_pool = _pick_pool(pools, date_str)
    logger.info("Selected pool: %s", chosen_pool["id"])

    # Build ordered attempt list: chosen pool first, then the rest as fallbacks
    attempt_order = [chosen_pool] + [p for p in pools if p["id"] != chosen_pool["id"]]

    for pool in attempt_order:
        pool_type = pool["type"]

        if pool_type in ("regional", "europe_random"):
            region = _get_region_for_pool(pool, date_str)
            logger.info("Fetching observations for region %s (pool: %s)", region, pool["id"])
            observations = get_recent_observations(region, back=back, locale=locale)
            if not observations:
                logger.warning("No observations for %s, trying next pool", region)
                continue
            result = _select_from_observations(observations, history_codes, date_str, pool["id"])
            if result:
                logger.info("Selected %s from pool %s", result["comName"], pool["id"])
                return result
            logger.warning("All species in %s already in history, trying next pool", pool["id"])

        elif pool_type == "global_taxonomy":
            logger.info("Using global taxonomy pool")
            try:
                taxonomy = get_full_taxonomy(locale=locale)
            except Exception:
                logger.exception("Failed to fetch taxonomy")
                continue
            result = _select_from_taxonomy(taxonomy, history_codes, date_str)
            if result:
                logger.info("Selected %s from global taxonomy", result["comName"])
                return result

    # Last resort: any species from taxonomy (should never reach here)
    logger.warning("All pools exhausted, falling back to unrestricted taxonomy pick")
    taxonomy = get_full_taxonomy(locale=locale)
    seed = _date_seed(date_str, salt="lastresort")
    rng = random.Random(seed)
    sp = rng.choice(taxonomy)
    return {
        "speciesCode": sp["speciesCode"],
        "comName": sp.get("comName", sp["speciesCode"]),
        "sciName": sp.get("sciName", ""),
    }
