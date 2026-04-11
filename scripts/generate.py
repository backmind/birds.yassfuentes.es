#!/usr/bin/env python3
"""Bird of the Day — Daily RSS Feed + Static Site generator.

Orchestrates species selection, image lookup, content scraping, RSS feed
construction, and the static index.html / archive.html pages. Idempotent
within a single UTC day: if today's bird is already in history, the script
exits without making changes.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path

from scripts import content_scraper, ebird_client, feed_builder, image_fetcher, site_builder

BASE_DIR = Path(__file__).resolve().parent.parent
CACHE_DIR = BASE_DIR / "cache"
FEED_PATH = BASE_DIR / "feed.xml"
HISTORY_PATH = BASE_DIR / "history.json"
CONFIG_PATH = BASE_DIR / "data" / "config.json"
ENV_PATH = BASE_DIR / ".env"


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader so local runs don't need an extra dependency.

    Existing environment variables always win, so CI (where the secret comes
    from the runner environment) is unaffected.
    """
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def load_history() -> dict:
    if not HISTORY_PATH.exists():
        return {"entries": []}
    return json.loads(HISTORY_PATH.read_text(encoding="utf-8"))


def save_history(history: dict) -> None:
    HISTORY_PATH.write_text(
        json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _build_site_entries(history: dict) -> list[site_builder.SiteEntry]:
    """Reconstruct rich SiteEntry objects from history + per-species caches.

    Iterates history in reverse so the most recent bird is first in the list.
    Missing caches degrade gracefully to empty fields.
    """
    entries: list[site_builder.SiteEntry] = []
    cache_dir = str(CACHE_DIR)
    raw_entries = history.get("entries", [])
    total = len(raw_entries)
    # We want oldest = №1, newest = №total. history is stored oldest-first,
    # so iterating reversed gives newest-first; the publication number for
    # entry at reversed-index `i` is `total - i`.
    for i, raw in enumerate(reversed(raw_entries)):
        code = raw.get("speciesCode")
        if not code:
            continue
        publication_number = total - i

        image = image_fetcher.load_cached_image(code, cache_dir)
        if image is None:
            # History has imageUrl as fallback for older entries
            image = image_fetcher.ImageResult(
                url=raw.get("imageUrl"),
                asset_id=None,
                photographer=raw.get("photographer", ""),
                attribution=raw.get("attribution", "Macaulay Library / Cornell Lab of Ornithology"),
                search_url=f"https://search.macaulaylibrary.org/catalog?taxonCode={code}&mediaType=photo&sort=rating_rank_desc",
            )

        content = content_scraper.load_cached_content(code, cache_dir)
        if content is None:
            content = content_scraper.SpeciesContent(
                description="", description_source="", bow_intro="", taxonomy={}
            )

        # Taxonomy may live in either the cache or the global taxonomy index
        taxonomy = content.taxonomy or ebird_client.lookup_taxonomy(code) or {}

        entries.append(
            site_builder.SiteEntry(
                species_code=code,
                common_name=raw.get("comName", code),
                scientific_name=raw.get("sciName", ""),
                date=raw.get("date", ""),
                image_url=image.url,
                photographer=image.photographer,
                attribution=image.attribution,
                description=content.description,
                description_source=content.description_source,
                bow_intro=content.bow_intro,
                taxonomy=taxonomy,
                ml_search_url=image.search_url,
                number=publication_number,
                wikipedia_url=content.wikipedia_url,
                wikipedia_language=content.wikipedia_language,
            )
        )
    return entries


def main() -> None:
    _load_dotenv(ENV_PATH)
    config = load_config()
    history = load_history()
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d")

    # Idempotency: skip if today's entry is already in history.
    last = history["entries"][-1] if history["entries"] else None
    if last and last.get("date") == date_str:
        logger.info("Already generated for %s, skipping", date_str)
        return

    dedup_window = config.get("dedup_window", config.get("max_history", 50))
    history_codes = [e["speciesCode"] for e in history["entries"][-dedup_window:]]

    try:
        # 1. Select species (preloads taxonomy cache as a side effect)
        logger.info("Selecting bird of the day for %s", date_str)
        species = ebird_client.select_species(
            config, history_codes, date_str, cache_dir=CACHE_DIR
        )
        species_code = species["speciesCode"]
        common_name = species["comName"]
        scientific_name = species["sciName"]
        logger.info("Selected: %s (%s) [%s]", common_name, scientific_name, species_code)

        # Shared HTTP session: cookies persist across image_fetcher and
        # content_scraper, which both hit eBird's CAS-gated species page.
        session = image_fetcher.new_session()

        # 2. Image — try cache first, then live lookup
        image = image_fetcher.load_cached_image(species_code, str(CACHE_DIR))
        if image is None:
            logger.info("Fetching image for %s", species_code)
            image = image_fetcher.fetch_image(species_code, session=session)
            image_fetcher.save_cached_image(species_code, image, str(CACHE_DIR))
        else:
            logger.info("Using cached image for %s", species_code)

        if image.url:
            logger.info("Image: asset %s by %s", image.asset_id, image.photographer or "?")
        else:
            logger.info("No image available, will link to ML Search")

        # 3. Content — cache first, then scrape
        content = content_scraper.load_cached_content(species_code, str(CACHE_DIR))
        if content is None:
            logger.info("Scraping content for %s", species_code)
            content = content_scraper.scrape_species_content(
                species_code,
                scientific_name=scientific_name,
                locale=config.get("ebird_locale", "es"),
                session=session,
            )
            content_scraper.save_cached_content(species_code, content, str(CACHE_DIR))
        else:
            logger.info("Using cached content for %s", species_code)

        # Taxonomy: prefer the API-side index over the (usually empty) scraped one
        taxonomy = ebird_client.lookup_taxonomy(species_code) or content.taxonomy or {
            k: species[k]
            for k in ("order", "familySciName", "familyComName", "sciName", "comName")
            if species.get(k)
        }

        # 4. Build the feed entry HTML
        entry_html = feed_builder.build_entry_html(
            species_code=species_code,
            common_name=common_name,
            scientific_name=scientific_name,
            image_url=image.url,
            image_attribution=image.attribution,
            ml_search_url=image.search_url,
            description=content.description,
            description_source=content.description_source,
            bow_intro=content.bow_intro,
            taxonomy=taxonomy,
        )

        # 5. Prepend to existing feed and trim
        pub_date = format_datetime(now)
        new_entry = feed_builder.FeedEntry(
            species_code=species_code,
            common_name=common_name,
            scientific_name=scientific_name,
            description_html=entry_html,
            image_url=image.url,
            image_attribution=image.attribution,
            ml_search_url=image.search_url,
            pub_date=pub_date,
            guid=f"bird-of-the-day-{species_code}-{date_str}",
        )
        existing = feed_builder.load_existing_feed(str(FEED_PATH))
        max_entries = config.get("max_feed_entries", 60)
        all_entries = ([new_entry] + existing)[:max_entries]
        feed_xml = feed_builder.build_feed(all_entries, config)
        feed_builder.write_feed(feed_xml, str(FEED_PATH))

        # 6. Update history (in memory + on disk). History is kept indefinitely
        # so the archive page can show every bird ever published.
        history["entries"].append(
            {
                "speciesCode": species_code,
                "comName": common_name,
                "sciName": scientific_name,
                "date": date_str,
                "imageUrl": image.url,
                "photographer": image.photographer,
                "attribution": image.attribution,
            }
        )
        save_history(history)

        # 7. Generate the static site
        site_entries = _build_site_entries(history)
        site_builder.write_site(
            site_entries,
            BASE_DIR,
            feed_link=config.get("feed_link", ""),
            author=config.get("author", ""),
        )

        logger.info("Done. Today's bird: %s (%s)", common_name, scientific_name)

    except Exception:
        logger.exception("Failed to generate bird of the day")
        sys.exit(1)


if __name__ == "__main__":
    main()
