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

from scripts import (
    content_scraper,
    ebird_client,
    feed_builder,
    i18n,
    image_fetcher,
    site_builder,
)

BASE_DIR = Path(__file__).resolve().parent.parent

# Mutable state lives under STATE_DIR. When BOTD_STATE_DIR is unset (local
# development, GitHub Actions) it equals BASE_DIR and behavior is identical
# to the pre-Docker layout. When set (typically in the container, where it
# points at the mounted volume) the cache and generated files are written
# under that directory while CONFIG_PATH and ENV_PATH stay anchored to the
# code in /app.
STATE_DIR = Path(os.environ.get("BOTD_STATE_DIR", str(BASE_DIR)))

# Code-anchored (read-only, baked in container image)
CONFIG_PATH = BASE_DIR / "data" / "config.json"
ENV_PATH = BASE_DIR / ".env"

# State-anchored (written at runtime, lives on the volume in Docker)
CACHE_DIR = STATE_DIR / "cache"
FEED_PATH = STATE_DIR / "feed.xml"
HISTORY_PATH = STATE_DIR / "history.json"


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


# Names that can be supplied via a *_FILE env var pointing at a file whose
# contents are the actual secret. Standard Docker / Kubernetes secrets
# convention (mirrors how postgres, mariadb, nginx and other "official"
# images handle secrets).
_SECRET_FILE_KEYS: tuple[str, ...] = ("EBIRD_API_KEY",)


def _load_secret_files() -> None:
    """Inject secrets from `*_FILE` env vars into the matching env var.

    For each key in :data:`_SECRET_FILE_KEYS`, if ``{KEY}_FILE`` is set
    and ``KEY`` itself is not, read the file at the path and use its
    stripped contents as the value of ``KEY``. Existing env vars always
    win, so a user can still override with ``-e KEY=...`` directly.
    """
    for key in _SECRET_FILE_KEYS:
        file_var = f"{key}_FILE"
        path = os.environ.get(file_var)
        if path and key not in os.environ:
            try:
                os.environ[key] = Path(path).read_text(encoding="utf-8").strip()
            except OSError as e:
                logger.warning(
                    "%s set but couldn't read %s: %s", file_var, path, e
                )


# Scalar config keys that may be overridden by environment variables. The
# table maps an env var name to (config key, caster). Env vars override the
# JSON file value when present, so users can ship the default
# ``data/config.json`` baked in the container and tweak individual knobs
# with ``-e BOTD_LANGUAGE=fr`` etc. Complex nested structures (like
# ``pools``) are intentionally not env-var-able — mount a custom file
# instead.
_ENV_OVERRIDES: dict[str, tuple[str, type]] = {
    "BOTD_LANGUAGE": ("language", str),
    "BOTD_EBIRD_LOCALE": ("ebird_locale", str),
    "BOTD_DESCRIPTION_POLICY": ("description_policy", str),
    "BOTD_MAX_SKIP_RETRIES": ("max_skip_retries", int),
    "BOTD_DEDUP_WINDOW": ("dedup_window", int),
    "BOTD_MAX_FEED_ENTRIES": ("max_feed_entries", int),
    "BOTD_BACK_DAYS": ("back_days", int),
    "BOTD_FEED_LINK": ("feed_link", str),
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def load_config() -> dict:
    """Load and normalize the project config.

    Migrations applied for back-compat with pre-i18n configs:

    - If ``language`` is missing, derive it from the legacy ``ebird_locale``
      field (or default to ``es``) and log a warning.
    - If the configured ``language`` doesn't have a catalog file, fall back
      to ``i18n.DEFAULT_FALLBACK`` (English) and warn.
    - Strip ``_*_help`` documentation keys so they don't pollute downstream.
    """
    raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

    # Drop documentation-only keys (start with underscore by convention)
    config = {k: v for k, v in raw.items() if not k.startswith("_")}

    if "language" not in config:
        legacy = config.get("ebird_locale") or "es"
        derived = legacy.split("_")[0].split("-")[0] if isinstance(legacy, str) else "es"
        logger.warning(
            "config.json missing 'language'; derived %s from legacy ebird_locale=%s",
            derived, legacy,
        )
        config["language"] = derived

    # Apply BOTD_* env-var overrides for scalar config keys. This lets a
    # container user tweak individual knobs without mounting a custom
    # config.json. Complex nested structures (pools) are not overridable;
    # mount a custom file instead.
    for env_name, (key, caster) in _ENV_OVERRIDES.items():
        raw_value = os.environ.get(env_name)
        if raw_value is None or raw_value == "":
            continue
        try:
            config[key] = caster(raw_value)
            logger.info("config override from env: %s = %r", key, config[key])
        except (ValueError, TypeError) as e:
            logger.warning(
                "ignoring %s=%r (cast to %s failed: %s)",
                env_name, raw_value, caster.__name__, e,
            )

    known = i18n.discover_languages()
    if known and config["language"] not in known:
        logger.warning(
            "config language %r has no catalog file; falling back to %s",
            config["language"], i18n.DEFAULT_FALLBACK,
        )
        config["language"] = i18n.DEFAULT_FALLBACK

    return config


def load_history() -> dict:
    if not HISTORY_PATH.exists():
        return {"entries": []}
    return json.loads(HISTORY_PATH.read_text(encoding="utf-8"))


def save_history(history: dict) -> None:
    HISTORY_PATH.write_text(
        json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _build_site_entries(
    history: dict, description_policy: str = "foreign_fallback"
) -> list[site_builder.SiteEntry]:
    """Reconstruct rich SiteEntry objects from history + per-species caches.

    Iterates history in reverse so the most recent bird is first in the list.
    Missing caches degrade gracefully to empty fields. The
    ``description_policy`` argument controls how empty descriptions are
    handled: ``foreign_fallback`` substitutes the rejected foreign text,
    ``strict`` (and ``skip`` from this rendering perspective) leaves them
    empty so the layout shows the em-dash placeholder.
    """
    entries: list[site_builder.SiteEntry] = []
    cache_dir = str(CACHE_DIR)
    raw_entries = history.get("entries", [])
    total = len(raw_entries)
    for i, raw in enumerate(reversed(raw_entries)):
        code = raw.get("speciesCode")
        if not code:
            continue
        publication_number = total - i

        image = image_fetcher.load_cached_image(code, cache_dir)
        if image is None:
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

        # Apply description policy at render time so a config change is
        # picked up on the next site build without re-scraping.
        effective_description = content.description
        effective_source = content.description_source
        if (
            not effective_description
            and description_policy == "foreign_fallback"
            and content.fallback_text
        ):
            effective_description = content.fallback_text
            effective_source = "ebird-foreign"

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
                description=effective_description,
                description_source=effective_source,
                bow_intro=content.bow_intro,
                taxonomy=taxonomy,
                ml_search_url=image.search_url,
                number=publication_number,
                wikipedia_url=content.wikipedia_url,
                wikipedia_language=content.wikipedia_language,
                fallback_language=content.fallback_language,
                gbif_taxon_key=content.gbif_taxon_key,
                distribution_map_url=content.distribution_map_url,
            )
        )
    return entries


def main() -> None:
    _load_dotenv(ENV_PATH)
    _load_secret_files()
    config = load_config()
    history = load_history()
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d")

    # Build the i18n catalog for the configured language. The catalog is
    # constructed once and passed explicitly to every builder.
    catalog = i18n.Catalog.load(config["language"])

    # Resolve the eBird locale: optional override in config wins over the
    # catalog default. The legacy code path read config["ebird_locale"]
    # directly, so we mutate it in-memory to keep ebird_client.select_species
    # untouched until Step 7+.
    ebird_locale = config.get("ebird_locale") or catalog.ebird_locale
    config["ebird_locale"] = ebird_locale

    # Idempotency: skip if today's entry is already in history.
    last = history["entries"][-1] if history["entries"] else None
    if last and last.get("date") == date_str:
        logger.info("Already generated for %s, skipping", date_str)
        return

    dedup_window = config.get("dedup_window", config.get("max_history", 50))
    history_codes = [e["speciesCode"] for e in history["entries"][-dedup_window:]]

    description_policy = config.get("description_policy", "foreign_fallback")
    max_skip = int(config.get("max_skip_retries", 50))

    try:
        # Shared HTTP session: cookies persist across image_fetcher and
        # content_scraper, which both hit eBird's CAS-gated species page.
        session = image_fetcher.new_session(
            accept_language=catalog.accept_language_header
        )

        # Selection loop. For strict / foreign_fallback the first pick wins.
        # For skip we re-roll up to max_skip times until we find a species
        # with text in the configured language; on exhaustion we publish the
        # last attempt with strict-style rendering.
        tried_codes: list[str] = []
        last_attempt: tuple | None = None

        for attempt in range(max_skip + 1):
            logger.info("Selecting bird of the day for %s", date_str)
            species = ebird_client.select_species(
                config,
                history_codes + tried_codes,
                date_str,
                cache_dir=CACHE_DIR,
            )
            species_code = species["speciesCode"]
            common_name = species["comName"]
            scientific_name = species["sciName"]
            logger.info(
                "Selected: %s (%s) [%s]",
                common_name, scientific_name, species_code,
            )

            # Image — try cache first, then live lookup
            image = image_fetcher.load_cached_image(species_code, str(CACHE_DIR))
            if image is None:
                logger.info("Fetching image for %s", species_code)
                image = image_fetcher.fetch_image(
                    species_code, session=session, locale=ebird_locale
                )
                image_fetcher.save_cached_image(species_code, image, str(CACHE_DIR))
            else:
                logger.info("Using cached image for %s", species_code)

            # Content — cache first, then scrape
            content = content_scraper.load_cached_content(species_code, str(CACHE_DIR))
            if content is None:
                logger.info("Scraping content for %s", species_code)
                content = content_scraper.scrape_species_content(
                    species_code,
                    scientific_name=scientific_name,
                    catalog=catalog,
                    session=session,
                )
                content_scraper.save_cached_content(species_code, content, str(CACHE_DIR))
            else:
                logger.info("Using cached content for %s", species_code)

            last_attempt = (species, species_code, common_name, scientific_name, image, content)

            # Skip mode: only accept species with text in target language.
            if description_policy != "skip":
                break
            if content.description:
                break
            logger.info(
                "skip retry #%d: %s has no %s description, rerolling",
                attempt + 1, species_code, catalog.language,
            )
            tried_codes.append(species_code)
        else:
            logger.warning(
                "skip exhausted %d retries; publishing last attempt with empty description",
                max_skip,
            )

        assert last_attempt is not None
        species, species_code, common_name, scientific_name, image, content = last_attempt

        if image.url:
            logger.info("Image: asset %s by %s", image.asset_id, image.photographer or "?")
        else:
            logger.info("No image available, will link to ML Search")

        # Apply description_policy to derive what actually gets rendered.
        # `effective_description` is what the builders show; `effective_source`
        # tells them whether to render the foreign-language disclaimer.
        effective_description = content.description
        effective_source = content.description_source
        if not effective_description and description_policy == "foreign_fallback" and content.fallback_text:
            effective_description = content.fallback_text
            effective_source = "ebird-foreign"
            logger.info(
                "foreign_fallback: using rejected %s text for %s",
                content.fallback_language, species_code,
            )

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
            description=effective_description,
            description_source=effective_source,
            bow_intro=content.bow_intro,
            taxonomy=taxonomy,
            catalog=catalog,
            wikipedia_url=content.wikipedia_url,
            wikipedia_language=content.wikipedia_language,
            fallback_language=content.fallback_language,
            distribution_map_url=content.distribution_map_url,
            gbif_taxon_key=content.gbif_taxon_key,
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
        feed_xml = feed_builder.build_feed(all_entries, config, catalog)
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

        # 7. Generate the static site (output goes under STATE_DIR so the
        # container's volume captures it; identical to BASE_DIR locally).
        site_entries = _build_site_entries(history, description_policy=description_policy)
        site_builder.write_site(
            site_entries,
            STATE_DIR,
            catalog=catalog,
            feed_link=config.get("feed_link", ""),
        )

        logger.info("Done. Today's bird: %s (%s)", common_name, scientific_name)

    except Exception:
        logger.exception("Failed to generate bird of the day")
        sys.exit(1)


if __name__ == "__main__":
    main()
