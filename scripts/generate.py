#!/usr/bin/env python3
"""Bird of the Day — Daily RSS Feed Generator.

Main entry point that orchestrates species selection, image fetching,
content scraping, and RSS feed generation.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path

from scripts import content_scraper, ebird_client, feed_builder, image_fetcher

BASE_DIR = Path(__file__).resolve().parent.parent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def load_config() -> dict:
    path = BASE_DIR / "data" / "config.json"
    return json.loads(path.read_text(encoding="utf-8"))


def load_history() -> dict:
    path = BASE_DIR / "history.json"
    if not path.exists():
        return {"entries": []}
    return json.loads(path.read_text(encoding="utf-8"))


def save_history(history: dict) -> None:
    path = BASE_DIR / "history.json"
    path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    config = load_config()
    history = load_history()
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d")

    # Idempotency: skip if already generated today
    if history["entries"] and history["entries"][-1].get("date") == date_str:
        logger.info("Already generated for %s, skipping", date_str)
        return

    max_history = config.get("max_history", 50)
    history_codes = [
        e["speciesCode"] for e in history["entries"][-max_history:]
    ]

    try:
        # 1. Select species
        logger.info("Selecting bird of the day for %s", date_str)
        species = ebird_client.select_species(config, history_codes, date_str)
        species_code = species["speciesCode"]
        common_name = species["comName"]
        scientific_name = species["sciName"]
        logger.info("Selected: %s (%s) [%s]", common_name, scientific_name, species_code)

        # 2. Fetch image
        logger.info("Fetching image for %s", species_code)
        image = image_fetcher.fetch_image(species_code)
        if image.url:
            logger.info("Image found: asset %s", image.asset_id)
        else:
            logger.info("No image found, using fallback link")

        # 3. Get content (cached or fresh)
        cache_dir = str(BASE_DIR / "cache")
        content = content_scraper.load_cached_content(species_code, cache_dir)
        if content is None:
            logger.info("Scraping content for %s", species_code)
            content = content_scraper.scrape_species_content(
                species_code, locale=config.get("ebird_locale", "es")
            )
            content_scraper.save_cached_content(species_code, content, cache_dir)
        else:
            logger.info("Using cached content for %s", species_code)

        # Merge taxonomy from API response if scraper didn't find it
        taxonomy = content.taxonomy
        if not taxonomy:
            taxonomy = {
                k: species[k]
                for k in ("order", "familySciName", "familyComName", "sciName", "comName")
                if k in species
            }

        # 4. Build entry HTML
        entry_html = feed_builder.build_entry_html(
            species_code=species_code,
            common_name=common_name,
            scientific_name=scientific_name,
            image_url=image.url,
            image_attribution=image.attribution,
            ml_search_url=image.search_url,
            ebird_description=content.ebird_description,
            bow_intro=content.bow_intro,
            taxonomy=taxonomy,
        )

        # 5. Create feed entry
        pub_date = format_datetime(now)
        entry = feed_builder.FeedEntry(
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

        # 6. Load existing feed, prepend new entry, trim
        feed_path = str(BASE_DIR / "feed.xml")
        existing_entries = feed_builder.load_existing_feed(feed_path)
        max_entries = config.get("max_feed_entries", 60)
        all_entries = [entry] + existing_entries
        all_entries = all_entries[:max_entries]

        # 7. Build and write feed
        xml_string = feed_builder.build_feed(all_entries, config)
        feed_builder.write_feed(xml_string, feed_path)

        # 8. Update history
        history["entries"].append({
            "speciesCode": species_code,
            "comName": common_name,
            "sciName": scientific_name,
            "date": date_str,
            "imageUrl": image.url,
        })
        # Keep generous buffer (2x max_history)
        history["entries"] = history["entries"][-(max_history * 2):]
        save_history(history)

        logger.info("Done! Feed updated with: %s (%s)", common_name, scientific_name)

    except Exception:
        logger.exception("Failed to generate bird of the day")
        sys.exit(1)


if __name__ == "__main__":
    main()
