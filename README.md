# birds.yassfuentes.es

[![Bird of the Day](https://github.com/backmind/birds.yassfuentes.es/actions/workflows/bird-of-the-day.yml/badge.svg)](https://github.com/backmind/birds.yassfuentes.es/actions/workflows/bird-of-the-day.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A running instance of [Bird of the Day](https://github.com/backmind/Bird-of-the-day),
publishing one bird a day at **<https://birds.yassfuentes.es/>**.

This repository is the site. The daily workflow selects a species, writes
the pages and the feeds, and commits them here; GitHub Pages serves what
it commits. If you want a site like this one, do not fork this: start
from [the template](https://github.com/backmind/Bird-of-the-day), which
is where the code and its documentation live.

## What this instance publishes

- In **Spanish**, since **2026-04-11**.
- Weighted towards home: 35% Madrid (`ES-MD`), 27% the rest of Spain
  (`ES`), 23% a random European country, 15% anywhere in the world.
- Species seen in the last **14 days**, drawn uniformly: this instance
  sets `rarity_bias` to 0 on purpose, because the count that bias reads
  is how many individuals were in a species' most recent reported
  sighting, which says more about which checklist arrived last than
  about how common the bird is.
- `feed.xml` carries the most recent **30** entries; `feed-full.xml`
  carries the whole history.

## When it runs

`.github/workflows/bird-of-the-day.yml`, twice a day, at **02:17 and
06:23 UTC**. The second tick retries what the first one could not fetch.

Both minutes are odd on purpose. GitHub queues scheduled runs and drops
the ones it cannot serve, and the top of the hour is where every cron in
the world piles up: this repository's old `02:00` schedule ran about an
hour late for eleven days and then drifted to between six and twelve
hours late. Treat the times as a hint, not a promise.

To publish out of band, run the workflow by hand from the Actions tab.

## What lives where

| Path | What it is |
|---|---|
| `data/config.json` | This instance's settings: pools, language, feed cap, author |
| `.github/workflows/bird-of-the-day.yml` | The daily publication |
| `history.json` | Every entry ever published. The single source of truth |
| `cache/`, `maps/` | Scrapes, photographs and composed maps, kept between runs |
| everything else at the root | Generated output. Do not edit by hand |

Secrets (`EBIRD_API_KEY`, `BOTD_LLM_API_KEY`) are repository secrets, not
files.

## The template's documentation

`docs/` is merged in from the template and describes the software rather
than this instance: [ARCHITECTURE](docs/ARCHITECTURE.md) for how a run
works, [CONFIGURATION](docs/CONFIGURATION.md) for every setting,
[DEPLOYMENT](docs/DEPLOYMENT.md) for the ways to host it. Where any of it
disagrees with `data/config.json` about a default, the config is what
actually runs here.

## Attribution

Data from [eBird](https://ebird.org) and the
[Cornell Lab of Ornithology](https://www.birds.cornell.edu/).
Photographs from the [Macaulay Library](https://www.macaulaylibrary.org/),
copyright their respective authors, hot-linked with visible attribution.
Distribution maps from [GBIF](https://www.gbif.org/). Non-commercial
project. No tracking, no cookies.

Code under the [MIT licence](LICENSE).
