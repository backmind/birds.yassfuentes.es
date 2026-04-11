# Bird of the Day

A daily bird species RSS feed and minimal static site, self-hostable as a
microservice. Each day a new species is selected from a configurable
weighted pool of regions, scraped from public Cornell Lab sources, and
published to a GitHub Pages site plus an RSS endpoint.

The default deployment leans Iberian (Madrid + Spain heavy, then Europe,
then global) but every region weight is configurable. The default language
is Spanish; English, French and Portuguese are bundled and contributors
can add more by dropping a single JSON file.

Zero AI-generated content, zero hosting cost (free tier of GitHub Actions
and GitHub Pages), zero tracking, zero cookies.

## Endpoints

GitHub Pages serves three static routes from the repository root:

| Route | What it is |
|---|---|
| `/` (`index.html`) | Hero of the day's bird + a grid of the most recent twelve |
| `/archive.html` | Every published bird in reverse chronological order, with permanent anchors (`#bird-{code}-{date}`) |
| `/feed.xml` | RSS 2.0 feed with rich `content:encoded` HTML |

Everything is server-rendered HTML — no JavaScript framework, no build
step. The single small piece of vanilla JS is an inline theme switcher
that persists light/dark preference in `localStorage`.

## How it works

```
GitHub Actions (cron daily 07:00 UTC)
  │
  ├─ 1. Pool weighted by date (e.g. 35% Madrid, 27% Spain,
  │     23% one random European country, 15% global taxonomy)
  ├─ 2. Species selection biased toward rarer observations,
  │     deduplicated against the last 50 publications
  ├─ 3. Photo + photographer from Macaulay Library Search API
  │     (with fallback to og:image on the eBird species page)
  ├─ 4. Description chain in the configured language:
  │     eBird Merlin → Wikipedia → policy-driven fallback
  ├─ 5. Wikipedia URL captured (target language → English fallback)
  │     so the footer link is always present
  ├─ 6. feed.xml + index.html + archive.html written
  └─ 7. git commit + git push → GitHub Pages republishes
```

The selection is **deterministic by date**: two runs on the same day pick
exactly the same species. The script bails early if today's entry is
already in `history.json`, so the daily cron and ad-hoc reruns don't
duplicate work.

## Stack

- Python 3.12+, managed with [`uv`](https://github.com/astral-sh/uv)
- Three runtime dependencies: `requests`, `beautifulsoup4`, `langid`
- No database. State lives in three files in the repo: `feed.xml`,
  `history.json`, `cache/`

## Local installation

```bash
git clone https://github.com/backmind/Bird-of-the-day.git
cd Bird-of-the-day
uv sync
```

`uv sync` creates the venv at `.venv/` and installs the dependencies from
`pyproject.toml`.

## Configuration

### Environment variables

| Variable | Required | Where to get it |
|---|---|---|
| `EBIRD_API_KEY` | yes | Free at <https://ebird.org/api/keygen> |

For local use copy `.env.example` to `.env` and fill the key:

```bash
cp .env.example .env
# edit .env
```

`.env` is gitignored and `generate.py` loads it automatically (no
`python-dotenv` required).

In GitHub Actions the key is injected from `Settings → Secrets and
variables → Actions → New repository secret` with the same name.

### `data/config.json`

Every behavior knob lives here. Annotated example:

```json
{
  "language": "es",
  "_language_help": "One of es | en | fr | pt (or any other catalog you add).",

  "ebird_locale": null,
  "_ebird_locale_help": "Optional override for the eBird API locale (e.g. 'pt_BR'). If null, derived from `language`.",

  "description_policy": "foreign_fallback",
  "_description_policy_help": "How to render descriptions when no source produces text in the configured language. One of: strict | foreign_fallback | skip.",
  "max_skip_retries": 50,

  "pools": [
    {"id": "madrid", "region": "ES-MD", "weight": 0.35, "type": "regional"},
    {"id": "spain",  "region": "ES",    "weight": 0.27, "type": "regional"},
    {"id": "europe", "weight": 0.23, "type": "europe_random",
     "countries": ["PT", "FR", "IT", "DE", "GB", "GR", "SE", "NO", "PL"]},
    {"id": "global", "weight": 0.15, "type": "global_taxonomy"}
  ],
  "dedup_window": 50,
  "max_feed_entries": 60,
  "back_days": 14,

  "feed_link": "https://YOUR-USERNAME.github.io/Bird-of-the-day/",
  "author": "Your Name"
}
```

Keys starting with `_` are documentation-only and ignored at load time.

### Description policy

What happens when none of the sources (eBird Merlin, target-language
Wikipedia) returns text in your configured language:

| Policy | Behavior |
|---|---|
| `foreign_fallback` (default) | Show the original (typically English) text with a translated disclaimer (*"Description in English (no Spanish translation available)"*). |
| `strict` | Show an em-dash placeholder. Never display foreign text. |
| `skip` | Re-roll species selection up to `max_skip_retries` times. On exhaustion, falls back to `strict`. |

Even with `strict`, the footer always carries a Wikipedia link — falling
back to English Wikipedia (and labeled `Wikipedia (en)`) if the target
language has no article.

## Running

### Locally

```bash
uv run python -m scripts.generate
```

This:

1. Loads `.env` if present.
2. Loads the i18n catalog for the configured language.
3. Bails early if today's entry is already in `history.json`.
4. Selects the species, fetches image and content (writing to `cache/`).
5. Writes `feed.xml`, `index.html`, `archive.html`.
6. Updates `history.json`.

To force a regeneration of today's entry, empty the history:

```bash
echo '{"entries": []}' > history.json
uv run python -m scripts.generate
```

### Via GitHub Actions

`.github/workflows/ave-del-dia.yml` runs:

- Automatically every day at **07:00 UTC** (09:00 CEST in Madrid).
- Manually from the **Actions → Ave del Día → Run workflow** tab.

The workflow `git add`s `feed.xml`, `history.json`, `index.html`,
`archive.html` and `cache/`, then commits with a message of the form
`🐦 Ave del día: 2026-04-11` and pushes to the default branch.

## Self-hosting

1. Fork the repo.
2. **Settings → Secrets and variables → Actions** → add `EBIRD_API_KEY`.
3. **Settings → Pages → Build and deployment** → source: `Deploy from a
   branch`, branch: `main`, folder: `/ (root)`. Save.
4. Edit `data/config.json`:
   - Set `feed_link` to your `https://<user>.github.io/<repo>/` URL.
   - Set `author` to your name.
   - Pick a `language` (or add one — see below).
   - Adjust `pools` if you want different regional weights.
5. Either wait for the cron or trigger **Actions → Ave del Día → Run
   workflow** manually for the first publication.

### Pool matrix examples

The default leans Iberian. Some alternative presets you can paste into
`data/config.json`:

**Western US flavor:**

```json
"pools": [
  {"id": "california", "region": "US-CA", "weight": 0.35, "type": "regional"},
  {"id": "us_west",    "region": "US",    "weight": 0.27, "type": "regional"},
  {"id": "americas",   "weight": 0.23, "type": "europe_random",
   "countries": ["MX", "CA", "CR", "BR", "AR", "CO", "EC", "PE", "CL"]},
  {"id": "global",     "weight": 0.15, "type": "global_taxonomy"}
]
```

**Pan-European balance (no national bias):**

```json
"pools": [
  {"id": "europe", "weight": 0.85, "type": "europe_random",
   "countries": ["ES", "PT", "FR", "IT", "DE", "GB", "GR", "SE", "NO", "PL", "NL", "BE", "AT", "CH", "DK", "FI"]},
  {"id": "global", "weight": 0.15, "type": "global_taxonomy"}
]
```

The `type` field accepts `regional` (single region code) or
`europe_random` (list of countries, one picked per day) or
`global_taxonomy` (any species in the eBird taxonomy).

### Adding a new language

1. Copy `data/i18n/en.json` to `data/i18n/{lang}.json` (use the ISO 639-1
   code, e.g. `de`, `it`, `ca`).
2. Translate every value. Missing keys fall back to English at render
   time, so partial translations are safe.
3. Add the language name in your file, plus the names of every other
   supported language as seen from your language. For example, in `de.json`:
   ```json
   "language_name.es": "Spanisch",
   "language_name.en": "Englisch",
   "language_name.fr": "Französisch",
   "language_name.pt": "Portugiesisch",
   "language_name.de": "Deutsch"
   ```
4. Set `language: "{lang}"` in your `data/config.json`.
5. **Clear `cache/*.json`** (but keep `cache/taxonomy.json`) so existing
   per-species caches don't render in the previous language.
6. Run `uv run python -m scripts.generate` and verify.
7. Open a PR.

`langid` (the language detector) supports 97 languages out of the box;
the only constraint on which target languages are valid is that there's a
`data/i18n/{lang}.json` file.

## Repository layout

```
Bird-of-the-day/
├── .github/workflows/ave-del-dia.yml    # daily cron + commit
├── scripts/
│   ├── generate.py        # orchestrator (entry point)
│   ├── ebird_client.py    # eBird API + species selection + taxonomy cache
│   ├── image_fetcher.py   # Macaulay Library API + og:image fallback
│   ├── content_scraper.py # eBird og:description + Wikipedia + BoW
│   ├── feed_builder.py    # RSS 2.0 generation
│   ├── site_builder.py    # index.html + archive.html generation
│   ├── i18n.py            # Catalog loader + langid wrapper
│   └── seed_mock.py       # developer-only: populate the site for visual review
├── data/
│   ├── config.json        # behavior knobs
│   └── i18n/{es,en,fr,pt}.json  # translation catalogs
├── cache/                 # taxonomy + per-species content/image caches
├── feed.xml               # generated: RSS 2.0
├── index.html             # generated: hero + grid
├── archive.html           # generated: every published bird
├── history.json           # generated: full publication history
├── pyproject.toml         # dependencies and uv metadata
├── uv.lock                # lock file
├── .env.example           # environment variable template
├── LICENSE                # MIT
└── README.md
```

## Attribution and legal notes

- **eBird API**: non-commercial use is permitted under the
  [eBird API Terms of Use](https://ebird.org/api/keygen). The project
  makes at most one selection call per day.
- **Macaulay Library**: photographs are © their authors. The project
  hot-links the public Cornell CDN for non-commercial display with
  visible photographer attribution, mirroring the embed flow Cornell
  itself offers.
- **Merlin / eBird and Birds of the World text**: © Cornell Lab of
  Ornithology. The feed reproduces short fragments with clear
  attribution and links back to the source, with no commercial purpose.
- **Wikipedia**: REST summary content is CC BY-SA 3.0; we link to the
  canonical article and don't redistribute beyond the short summary.
- **Generated data** (feed, site): MIT, free to reuse with attribution.

## Privacy

This site stores your theme preference (light/dark) in `localStorage` so
it persists between visits. That's the only client-side state, it never
leaves the browser, and it falls under the "strictly necessary functional
preferences" exemption of the EU ePrivacy Directive — no consent banner
or cookie notice is required. There are no cookies, no analytics, no
trackers, and no third-party requests beyond Google Fonts (for typography)
and the Macaulay Library CDN (for photos).

## License

[MIT](LICENSE). Third-party content (photos, Cornell text excerpts,
Wikipedia summaries) keeps its respective licenses and attributions.
