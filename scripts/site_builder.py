"""Generate the static site (index.html + archive.html) from cached birds.

The site is two pages of plain HTML with embedded CSS — no JavaScript, no
build step. The most recent bird is the hero on ``index.html``; up to 12
previous birds appear as a grid below it. ``archive.html`` lists every
entry from history with full content and stable anchors.
"""

from __future__ import annotations

import html
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

INDEX_GRID_SIZE = 12

# Hardcoded for now; the i18n refactor (step 5+) will replace this with the
# active catalog's language. Used for forcing eBird's siteLanguage parameter
# and for deciding whether to label the Wikipedia link with a language hint.
_TARGET_LANGUAGE = "es"


@dataclass
class SiteEntry:
    species_code: str
    common_name: str
    scientific_name: str
    date: str  # ISO YYYY-MM-DD
    image_url: str | None
    photographer: str
    attribution: str
    description: str
    description_source: str
    bow_intro: str
    taxonomy: dict
    ml_search_url: str
    number: int = 0  # 1-indexed publication number, populated by generate.py
    wikipedia_url: str = ""       # canonical Wikipedia article URL
    wikipedia_language: str = ""  # "es" | "en" | "" — what we resolved to

    @property
    def anchor(self) -> str:
        return f"bird-{self.species_code}-{self.date}"

    @property
    def archive_url(self) -> str:
        return f"archive.html#{self.anchor}"

    @property
    def date_dotted(self) -> str:
        """ISO date as `YYYY · MM · DD` — language-neutral, used in plate-date."""
        return self.date.replace("-", " · ")


def _esc(value: str) -> str:
    return html.escape(value or "", quote=True)


_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght,SOFT@9..144,400;9..144,500;9..144,600;9..144,700&family=Source+Serif+4:opsz,wght@8..60,400;8..60,500;8..60,600&display=swap');

/* ─── palette ──────────────────────────────────────────────────────
   Field Journal at Dawn — warm parchment + deep teal sky + brushed bronze
   Light mode reads as opening a leather-bound observation log on a desk.
   Dark mode reads as the same log lit by a single lantern at night.       */
:root {
  --paper: #F4EEE0;
  --paper-warm: #ECE2CC;
  --paper-deep: #E1D4B6;
  --ink: #1E2A2E;
  --ink-soft: #5C6A6E;
  --ink-faint: #8A8A7C;
  --accent: #0E5F66;
  --accent-warm: #B36B2F;
  --rule: #C8BEA4;
  --rule-strong: #A89B7D;
  --shadow: 0 1px 0 rgba(255,255,255,0.5), 0 10px 28px -12px rgba(30, 42, 46, 0.22), 0 2px 6px -2px rgba(30, 42, 46, 0.08);
  --max: 920px;
  --max-wide: 1080px;
}

/* Dark mode: applied automatically when the OS prefers dark, UNLESS the
   user has manually toggled to light. Manual override (data-theme="dark")
   wins regardless of the OS setting. */
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --paper: #0F1518;
    --paper-warm: #161E22;
    --paper-deep: #1B252A;
    --ink: #E9E2D0;
    --ink-soft: #9AA4A4;
    --ink-faint: #5C6A6E;
    --accent: #5BB1B6;
    --accent-warm: #D9893A;
    --rule: #2A3338;
    --rule-strong: #3E4A50;
    --shadow: 0 0 0 1px rgba(255,255,255,0.04), 0 14px 36px -12px rgba(0,0,0,0.7), 0 2px 8px -2px rgba(0,0,0,0.5);
  }
}
:root[data-theme="dark"] {
  --paper: #0F1518;
  --paper-warm: #161E22;
  --paper-deep: #1B252A;
  --ink: #E9E2D0;
  --ink-soft: #9AA4A4;
  --ink-faint: #5C6A6E;
  --accent: #5BB1B6;
  --accent-warm: #D9893A;
  --rule: #2A3338;
  --rule-strong: #3E4A50;
  --shadow: 0 0 0 1px rgba(255,255,255,0.04), 0 14px 36px -12px rgba(0,0,0,0.7), 0 2px 8px -2px rgba(0,0,0,0.5);
}

* { box-sizing: border-box; }
html { scroll-behavior: smooth; -webkit-text-size-adjust: 100%; }

body {
  margin: 0;
  background: var(--paper);
  color: var(--ink);
  font-family: 'Source Serif 4', 'Source Serif Pro', Georgia, serif;
  font-feature-settings: 'kern', 'liga', 'onum';
  font-variant-numeric: oldstyle-nums proportional-nums;
  font-optical-sizing: auto;
  font-size: 18px;
  line-height: 1.65;
  /* faint paper grain + a halo at the top of the page */
  background-image:
    radial-gradient(ellipse 1100px 520px at 50% -8%, rgba(179,107,47,0.05), transparent 60%),
    url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' stitchTiles='stitch'/%3E%3CfeColorMatrix values='0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0.06 0'/%3E%3C/filter%3E%3Crect width='200' height='200' filter='url(%23n)'/%3E%3C/svg%3E");
  background-attachment: fixed, fixed;
}

@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) body {
    background-image:
      radial-gradient(ellipse 1100px 520px at 50% -8%, rgba(91,177,182,0.07), transparent 60%),
      url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' stitchTiles='stitch'/%3E%3CfeColorMatrix values='0 0 0 0 1 0 0 0 0 1 0 0 0 0 1 0 0 0 0.04 0'/%3E%3C/filter%3E%3Crect width='200' height='200' filter='url(%23n)'/%3E%3C/svg%3E");
  }
}
:root[data-theme="dark"] body {
  background-image:
    radial-gradient(ellipse 1100px 520px at 50% -8%, rgba(91,177,182,0.07), transparent 60%),
    url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' stitchTiles='stitch'/%3E%3CfeColorMatrix values='0 0 0 0 1 0 0 0 0 1 0 0 0 0 1 0 0 0 0.04 0'/%3E%3C/filter%3E%3Crect width='200' height='200' filter='url(%23n)'/%3E%3C/svg%3E");
}

/* ─── links ────────────────────────────────────────────────────── */
a {
  color: var(--ink);
  text-decoration: underline;
  text-decoration-color: var(--rule-strong);
  text-decoration-thickness: 1px;
  text-underline-offset: 3px;
  transition: text-decoration-color .25s ease, color .25s ease;
}
a:hover { text-decoration-color: var(--accent-warm); color: var(--accent); }
a:focus-visible, button:focus-visible {
  outline: 2px solid var(--accent-warm);
  outline-offset: 3px;
  border-radius: 1px;
}

.skip-link {
  position: absolute; left: -1000px; top: 0;
  background: var(--ink); color: var(--paper);
  padding: .55rem 1.1rem;
  z-index: 100;
  font-family: 'Fraunces', Georgia, serif;
  font-variation-settings: 'opsz' 9;
  font-size: .76rem;
  text-transform: uppercase;
  letter-spacing: .14em;
}
.skip-link:focus { left: 1rem; top: 1rem; }

/* ─── masthead ─────────────────────────────────────────────────── */
header.site {
  border-bottom: 1px solid var(--rule);
  background: linear-gradient(to bottom, transparent, var(--paper-warm));
}
header.site .inner {
  max-width: var(--max-wide);
  margin: 0 auto;
  padding: 1.6rem 2rem 1.25rem;
  display: grid;
  grid-template-columns: 1fr auto;
  align-items: end;
  gap: 1rem;
}
header.site .brand { display: flex; flex-direction: column; gap: .15rem; }
header.site .eyebrow {
  font-family: 'Fraunces', Georgia, serif;
  font-variation-settings: 'opsz' 9;
  font-size: .68rem;
  text-transform: uppercase;
  letter-spacing: .22em;
  color: var(--ink-soft);
}
header.site h1 {
  margin: 0;
  font-family: 'Fraunces', Georgia, serif;
  font-variation-settings: 'SOFT' 100, 'opsz' 48;
  font-weight: 600;
  font-size: 1.75rem;
  line-height: 1;
  letter-spacing: -0.012em;
}
header.site h1 a { color: var(--ink); text-decoration: none; }
header.site nav {
  display: flex;
  gap: 1.75rem;
  font-family: 'Fraunces', Georgia, serif;
  font-variation-settings: 'opsz' 9;
  font-size: .72rem;
  text-transform: uppercase;
  letter-spacing: .18em;
  align-items: end;
}
header.site nav a {
  color: var(--ink-soft);
  text-decoration: none;
  padding-bottom: .12rem;
  border-bottom: 1px solid transparent;
  transition: color .25s ease, border-color .25s ease;
}
header.site nav a:hover,
header.site nav a[aria-current="page"] {
  color: var(--ink);
  border-bottom-color: var(--accent-warm);
}

.theme-toggle {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  margin-left: .25rem;
  padding: 0;
  background: transparent;
  border: 1px solid var(--rule);
  border-radius: 50%;
  color: var(--ink-soft);
  cursor: pointer;
  transition: color .25s ease, border-color .25s ease, transform .35s ease;
}
.theme-toggle:hover {
  color: var(--accent-warm);
  border-color: var(--accent-warm);
  transform: rotate(-12deg);
}
.theme-toggle svg { width: 16px; height: 16px; }
/* Show moon by default (light mode showing "switch to dark"), sun in dark mode */
.theme-toggle .icon-sun { display: none; }
.theme-toggle .icon-moon { display: block; }
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) .theme-toggle .icon-sun { display: block; }
  :root:not([data-theme="light"]) .theme-toggle .icon-moon { display: none; }
}
:root[data-theme="dark"] .theme-toggle .icon-sun { display: block; }
:root[data-theme="dark"] .theme-toggle .icon-moon { display: none; }

/* ─── main column ──────────────────────────────────────────────── */
main {
  max-width: var(--max);
  margin: 0 auto;
  padding: 3rem 2rem 4rem;
}

/* ─── plate (used by hero AND archive entries) ─────────────────── */
.plate {
  position: relative;
  margin-bottom: 4.5rem;
}
.plate + .plate { margin-top: 4.5rem; }

.plate-head {
  display: grid;
  grid-template-columns: 1fr auto;
  align-items: baseline;
  gap: 1rem;
  font-family: 'Fraunces', Georgia, serif;
  font-feature-settings: 'lnum', 'tnum';
}
.plate-number {
  font-variation-settings: 'opsz' 14;
  font-size: 1rem;
  font-weight: 500;
  color: var(--ink-soft);
}
.plate-number .glyph {
  font-style: italic;
  font-weight: 400;
  color: var(--accent-warm);
  margin-right: .12rem;
}
.plate-date {
  font-variation-settings: 'opsz' 9;
  font-size: .72rem;
  text-transform: uppercase;
  letter-spacing: .16em;
  color: var(--ink-soft);
}

.plate-rule {
  display: flex;
  align-items: center;
  gap: .8rem;
  margin: .85rem 0 1.5rem;
  color: var(--ink-faint);
}
.plate-rule::before {
  content: '';
  flex: 1;
  height: 1px;
  background: linear-gradient(to right, transparent, var(--rule-strong) 60%);
}
.plate-rule::after {
  content: '';
  flex: 1;
  height: 1px;
  background: linear-gradient(to left, transparent, var(--rule-strong) 60%);
}
.plate-rule .ornament {
  font-family: 'Fraunces', serif;
  font-variation-settings: 'opsz' 14;
  font-size: 1.05rem;
  color: var(--accent-warm);
  line-height: 1;
}

.plate-image {
  position: relative;
  overflow: hidden;
  background: var(--paper-warm);
  aspect-ratio: 3 / 2;
  box-shadow: inset 0 0 0 1px var(--rule), var(--shadow);
}
.plate-image img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
  transition: transform 1.4s cubic-bezier(.2,.6,.2,1), filter .6s ease;
}
.plate:hover .plate-image img { transform: scale(1.02); }
.plate-image .no-image {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: var(--ink-soft);
  font-style: italic;
  font-size: .9rem;
  text-align: center;
  padding: 2rem;
  background: repeating-linear-gradient(135deg, transparent 0 9px, rgba(30,42,46,0.04) 9px 10px);
}
.plate-credit {
  margin: .75rem 0 0;
  font-size: .78rem;
  font-style: italic;
  color: var(--ink-soft);
  text-align: right;
}

.plate-body { margin-top: 2.4rem; }

.specimen-tag {
  display: inline-flex;
  align-items: center;
  gap: .55rem;
  font-family: 'Fraunces', Georgia, serif;
  font-variation-settings: 'opsz' 9;
  font-size: .68rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: .2em;
  color: var(--accent-warm);
  margin: 0 0 .9rem;
}
.specimen-tag::before {
  content: '';
  width: 1.6rem;
  height: 1px;
  background: var(--accent-warm);
}

.plate-title {
  font-family: 'Fraunces', Georgia, serif;
  font-variation-settings: 'SOFT' 30, 'opsz' 96;
  font-weight: 600;
  font-size: clamp(2.1rem, 4.6vw, 3.4rem);
  line-height: 1.02;
  letter-spacing: -0.018em;
  margin: 0 0 .35rem;
  color: var(--ink);
  text-wrap: balance;
}
.plate-subtitle {
  font-family: 'Source Serif 4', Georgia, serif;
  font-style: italic;
  font-weight: 400;
  font-size: 1.15rem;
  color: var(--ink-soft);
  margin: 0 0 1.75rem;
}

.plate-description {
  font-size: 1.04rem;
  line-height: 1.72;
  color: var(--ink);
  margin: 0 0 1rem;
  text-wrap: pretty;
}
.plate-description.empty {
  font-family: 'Fraunces', Georgia, serif;
  font-variation-settings: 'opsz' 14;
  font-size: 1.5rem;
  font-weight: 400;
  color: var(--ink-faint);
  text-align: center;
  margin: 1rem 0;
  letter-spacing: .3em;
}

.source-note {
  margin: .35rem 0 1rem;
  font-size: .78rem;
  color: var(--ink-soft);
  font-style: italic;
}
.source-note a { color: var(--ink-soft); text-decoration-color: var(--rule-strong); }

.plate-foot {
  margin-top: 2rem;
  padding-top: 1.25rem;
  border-top: 1px solid var(--rule);
  display: flex;
  flex-wrap: wrap;
  gap: .25rem 1.6rem;
  font-family: 'Fraunces', Georgia, serif;
  font-variation-settings: 'opsz' 9;
  font-size: .7rem;
  text-transform: uppercase;
  letter-spacing: .16em;
}
.plate-foot a {
  color: var(--ink-soft);
  text-decoration: none;
  padding-bottom: .15rem;
  border-bottom: 1px solid var(--rule);
  transition: color .25s ease, border-color .25s ease;
}
.plate-foot a:hover {
  color: var(--accent);
  border-bottom-color: var(--accent-warm);
}

/* ─── hero-only ornament: V-soaring bird watermark ─────────────── */
.plate.hero { isolation: isolate; }
.plate.hero::before {
  content: "";
  position: absolute;
  top: -1.5rem;
  right: -.25rem;
  width: 96px;
  height: 56px;
  pointer-events: none;
  opacity: .14;
  z-index: -1;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 60'%3E%3Cpath d='M8 38 Q 30 8, 50 32 Q 70 8, 92 38' fill='none' stroke='%231E2A2E' stroke-width='3.5' stroke-linecap='round'/%3E%3C/svg%3E");
  background-size: contain;
  background-repeat: no-repeat;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) .plate.hero::before {
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 60'%3E%3Cpath d='M8 38 Q 30 8, 50 32 Q 70 8, 92 38' fill='none' stroke='%23E9E2D0' stroke-width='3.5' stroke-linecap='round'/%3E%3C/svg%3E");
    opacity: .18;
  }
}
:root[data-theme="dark"] .plate.hero::before {
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 60'%3E%3Cpath d='M8 38 Q 30 8, 50 32 Q 70 8, 92 38' fill='none' stroke='%23E9E2D0' stroke-width='3.5' stroke-linecap='round'/%3E%3C/svg%3E");
  opacity: .18;
}

/* ─── section divider ──────────────────────────────────────────── */
.section-divider {
  display: flex;
  align-items: baseline;
  gap: 1.25rem;
  margin: 4rem 0 2rem;
}
.section-divider .label {
  font-family: 'Fraunces', Georgia, serif;
  font-variation-settings: 'opsz' 9;
  font-size: .72rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: .2em;
  color: var(--ink-soft);
  white-space: nowrap;
}
.section-divider::after {
  content: '';
  flex: 1;
  height: 1px;
  background: linear-gradient(to right, var(--rule-strong), transparent);
}

/* ─── recent-birds grid (specimen tags) ────────────────────────── */
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(230px, 1fr));
  gap: 2.5rem 1.75rem;
}
.card a { display: contents; color: inherit; text-decoration: none; }
.card-thumb {
  aspect-ratio: 4 / 5;
  overflow: hidden;
  background: var(--paper-warm);
  position: relative;
  box-shadow: inset 0 0 0 1px var(--rule), 0 1px 0 rgba(255,255,255,0.4), 0 10px 24px -16px rgba(30,42,46,0.35);
}
.card-thumb img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
  filter: saturate(.95);
  transition: transform .9s cubic-bezier(.2,.6,.2,1), filter .4s ease;
}
.card a:hover .card-thumb img { transform: scale(1.05); filter: saturate(1.05); }
.card-thumb .empty {
  width: 100%;
  height: 100%;
  background: repeating-linear-gradient(135deg, transparent 0 8px, rgba(30,42,46,0.04) 8px 9px);
}
.card-meta {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-top: .85rem;
  font-family: 'Fraunces', Georgia, serif;
  font-variation-settings: 'opsz' 9;
  font-feature-settings: 'lnum', 'tnum';
  font-size: .68rem;
  text-transform: uppercase;
  letter-spacing: .14em;
  color: var(--ink-faint);
}
.card-meta .glyph { font-style: italic; color: var(--accent-warm); margin-right: .12rem; }
.card-name {
  font-family: 'Fraunces', Georgia, serif;
  font-variation-settings: 'SOFT' 50, 'opsz' 32;
  font-weight: 600;
  font-size: 1.18rem;
  line-height: 1.2;
  margin: .35rem 0 .15rem;
  color: var(--ink);
  text-wrap: balance;
}
.card-sci {
  font-family: 'Source Serif 4', Georgia, serif;
  font-style: italic;
  font-size: .9rem;
  color: var(--ink-soft);
  margin: 0;
}
.card-tag {
  font-family: 'Fraunces', Georgia, serif;
  font-variation-settings: 'opsz' 9;
  font-size: .62rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: .18em;
  color: var(--accent-warm);
  margin: .55rem 0 0;
}
.card a:hover .card-name { color: var(--accent); }

/* ─── subscribe (refined footnote, not a banner) ───────────────── */
.subscribe {
  margin: 4rem 0;
  padding: 1.5rem 1.75rem;
  border: 1px solid var(--rule);
  background: linear-gradient(180deg, var(--paper-warm), var(--paper));
  display: grid;
  grid-template-columns: auto 1fr auto;
  align-items: center;
  gap: 1.25rem;
  position: relative;
}
.subscribe::before {
  content: '';
  position: absolute;
  top: -1px; left: -1px; bottom: -1px;
  width: 4px;
  background: linear-gradient(to bottom, var(--accent-warm), var(--accent));
}
.subscribe .icon {
  width: 36px; height: 36px;
  display: grid; place-items: center;
  color: var(--accent);
}
.subscribe .icon svg { width: 22px; height: 22px; }
.subscribe .text p { margin: 0; }
.subscribe .text .title {
  font-family: 'Fraunces', Georgia, serif;
  font-variation-settings: 'SOFT' 30, 'opsz' 24;
  font-weight: 600;
  font-size: 1.08rem;
  color: var(--ink);
}
.subscribe .text .sub {
  font-size: .86rem;
  color: var(--ink-soft);
  margin-top: .15rem;
  font-style: italic;
}
.subscribe .button {
  font-family: 'Fraunces', Georgia, serif;
  font-variation-settings: 'opsz' 9;
  font-size: .72rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: .16em;
  color: var(--paper);
  background: var(--ink);
  padding: .75rem 1.2rem;
  text-decoration: none;
  white-space: nowrap;
  transition: background .25s ease;
}
.subscribe .button:hover { background: var(--accent); }
@media (max-width: 600px) {
  .subscribe { grid-template-columns: auto 1fr; gap: 1rem; }
  .subscribe .button { grid-column: 1 / -1; text-align: center; padding: .9rem; }
}

/* ─── archive intro ────────────────────────────────────────────── */
.archive-intro {
  margin: 1rem 0 4rem;
  text-align: center;
}
.archive-intro h1 {
  font-family: 'Fraunces', Georgia, serif;
  font-variation-settings: 'SOFT' 60, 'opsz' 96;
  font-weight: 600;
  font-size: clamp(2.5rem, 5vw, 3.8rem);
  margin: 0 0 .5rem;
  letter-spacing: -.02em;
  line-height: 1;
}
.archive-intro p { font-style: italic; color: var(--ink-soft); margin: 0; }

/* ─── footer ───────────────────────────────────────────────────── */
footer.site {
  margin-top: 5rem;
  padding: 2.5rem 2rem 3.5rem;
  border-top: 1px solid var(--rule);
  background: var(--paper-warm);
  text-align: center;
  font-size: .85rem;
  color: var(--ink-soft);
  font-style: italic;
}
footer.site p { margin: .4rem 0; }
footer.site a { color: var(--ink-soft); }

/* ─── responsive tightening ────────────────────────────────────── */
@media (max-width: 720px) {
  main { padding: 2.25rem 1.25rem 3rem; }
  header.site .inner { padding: 1.25rem 1.25rem 1rem; grid-template-columns: 1fr; gap: .75rem; }
  header.site nav { gap: 1.25rem; }
  .plate-head { grid-template-columns: 1fr; gap: .25rem; }
  .plate.hero::before { width: 72px; height: 42px; top: -1rem; right: -.25rem; }
}
@media (max-width: 480px) {
  body { font-size: 17px; }
  .plate-title { font-size: clamp(1.8rem, 7vw, 2.6rem); }
  .grid { grid-template-columns: repeat(auto-fill, minmax(155px, 1fr)); gap: 2rem 1rem; }
  .card-name { font-size: 1.05rem; }
}
""".strip()


_THEME_TOGGLE_BUTTON = """
<button class="theme-toggle" type="button" aria-label="Cambiar tema claro/oscuro" onclick="(function(b){var h=document.documentElement;var c=h.dataset.theme;if(!c){c=window.matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light';}var n=c==='dark'?'light':'dark';h.dataset.theme=n;try{localStorage.setItem('bird-theme',n);}catch(e){}})(this);">
  <svg class="icon-moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>
  <svg class="icon-sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/></svg>
</button>
""".strip()


def _render_header(active: str, feed_link: str) -> str:
    archive_class = ' aria-current="page"' if active == "archive" else ""
    home_class = ' aria-current="page"' if active == "home" else ""
    return f"""
<a class="skip-link" href="#main">Saltar al contenido</a>
<header class="site">
  <div class="inner">
    <div class="brand">
      <span class="eyebrow">Diario de campo · cada día</span>
      <h1><a href="index.html">Ave del Día</a></h1>
    </div>
    <nav aria-label="Principal">
      <a href="index.html"{home_class}>Hoy</a>
      <a href="archive.html"{archive_class}>Archivo</a>
      <a href="feed.xml">RSS</a>
      {_THEME_TOGGLE_BUTTON}
    </nav>
  </div>
</header>
""".strip()


def _render_subscribe(feed_url: str = "feed.xml") -> str:
    """Refined RSS footnote — not a marketing banner."""
    return f"""
<aside class="subscribe" aria-label="Suscríbete al RSS">
  <div class="icon" aria-hidden="true">
    <svg viewBox="0 0 24 24" fill="currentColor">
      <path d="M6.18 17.82a2.18 2.18 0 1 1-4.36 0 2.18 2.18 0 0 1 4.36 0zM2 6.44v3.1c7.03 0 12.73 5.7 12.73 12.73h3.1C17.83 13.39 10.61 6.17 2 6.44zM2 .5v3.1c10.04 0 18.18 8.14 18.18 18.18h3.1C23.28 9.97 13.45.5 2 .5z"/>
    </svg>
  </div>
  <div class="text">
    <p class="title">Recíbela cada mañana en tu lector RSS</p>
    <p class="sub">Una especie nueva al día.</p>
  </div>
  <a class="button" href="{_esc(feed_url)}">Suscribirse</a>
</aside>
""".strip()


def _render_footer(author: str = "") -> str:
    year = datetime.now(timezone.utc).year
    author_line = (
        f"Proyecto no comercial por {_esc(author)} © {year}. "
        '<a href="https://github.com/backmind/Bird-of-the-day">Código en GitHub</a>.'
        if author
        else 'Proyecto no comercial. <a href="https://github.com/backmind/Bird-of-the-day">Código en GitHub</a>.'
    )
    return f"""
<footer class="site">
  <p>Datos de <a href="https://ebird.org">eBird</a> y
    <a href="https://www.birds.cornell.edu/">Cornell Lab of Ornithology</a>.</p>
  <p>Fotos de <a href="https://www.macaulaylibrary.org/">Macaulay Library</a>,
    © de sus respectivos autores.</p>
  <p>{author_line}</p>
</footer>
""".strip()


def _description_credit(entry: SiteEntry) -> str:
    """Inline note crediting the description source (Wikipedia only for now)."""
    if entry.description_source == "wikipedia":
        title = entry.scientific_name.replace(" ", "_")
        return (
            f'<p class="source-note">Fuente: '
            f'<a href="https://es.wikipedia.org/wiki/{_esc(title)}">Wikipedia en español</a></p>'
        )
    return ""


def _specimen_tag(taxonomy: dict) -> str:
    """Inline 'family · order' tag rendered above the title.

    Both come from the eBird taxonomy and are scientific Latin names that
    don't need translation. The English ``familyComName`` is deliberately
    omitted (eBird doesn't translate it even with locale=es).
    """
    if not taxonomy:
        return ""
    parts = []
    if taxonomy.get("familySciName"):
        parts.append(_esc(taxonomy["familySciName"]))
    if taxonomy.get("order"):
        parts.append(_esc(taxonomy["order"]))
    if not parts:
        return ""
    return f'<p class="specimen-tag">{" · ".join(parts)}</p>'


def _render_plate(entry: SiteEntry, *, hero: bool = False) -> str:
    """Render a bird as a numbered field-journal plate.

    Used both for the index hero and every archive entry. Hero variant gets
    the soaring-bird watermark via CSS (``.plate.hero::before``) and
    eager-loaded image; archive variant gets lazy loading and an anchor id.
    """
    tag = "section" if hero else "article"
    classes = "plate hero" if hero else "plate"
    title_id = ' id="hero-title"' if hero else ""
    aria = ' aria-labelledby="hero-title"' if hero else ""
    anchor_attr = "" if hero else f' id="{_esc(entry.anchor)}"'
    loading = "eager" if hero else "lazy"

    if entry.image_url:
        image_block = (
            f'<div class="plate-image">'
            f'<img src="{_esc(entry.image_url)}" '
            f'alt="{_esc(entry.common_name)}" loading="{loading}" />'
            f'</div>'
            f'<p class="plate-credit">© {_esc(entry.attribution)}</p>'
        )
    else:
        image_block = (
            f'<div class="plate-image"><div class="no-image">'
            f'<a href="{_esc(entry.ml_search_url)}">Macaulay Library</a>'
            f'</div></div>'
        )

    if entry.description:
        desc_html = f'<p class="plate-description">{_esc(entry.description)}</p>'
        if entry.bow_intro:
            desc_html += (
                f'<p class="plate-description">{_esc(entry.bow_intro)}</p>'
            )
    else:
        # Universal em-dash placeholder, no language string
        desc_html = '<p class="plate-description empty">—</p>'

    number_html = (
        f'<span class="plate-number"><span class="glyph">№</span>&nbsp;{entry.number}</span>'
        if entry.number
        else "<span></span>"
    )

    # plate-foot links: eBird → Wikipedia (if found) → BoW → Macaulay.
    # eBird is forced to the configured language via siteLanguage so the
    # link always lands in the reader's locale (no language hint needed).
    # Wikipedia is added even when the description came from eBird; if it
    # had to fall back to English (because the target-language article
    # doesn't exist), the link gets a "(en)" hint inside its label.
    ebird_url = (
        f"https://ebird.org/species/{_esc(entry.species_code)}"
        f"?siteLanguage={_TARGET_LANGUAGE}"
    )
    foot_links = [f'<a href="{ebird_url}">eBird</a>']

    if entry.wikipedia_url:
        wiki_label = "Wikipedia"
        if entry.wikipedia_language and entry.wikipedia_language != _TARGET_LANGUAGE:
            wiki_label = f"Wikipedia ({entry.wikipedia_language})"
        foot_links.append(
            f'<a href="{_esc(entry.wikipedia_url)}">{wiki_label}</a>'
        )

    foot_links.append(
        f'<a href="https://birdsoftheworld.org/bow/species/{_esc(entry.species_code)}/cur/introduction">Birds of the World</a>'
    )
    foot_links.append(
        f'<a href="{_esc(entry.ml_search_url)}">Macaulay Library</a>'
    )

    return f"""
<{tag} class="{classes}"{anchor_attr}{aria}>
  <div class="plate-head">
    {number_html}
    <span class="plate-date">{_esc(entry.date_dotted)}</span>
  </div>
  <div class="plate-rule"><span class="ornament">❦</span></div>
  {image_block}
  <div class="plate-body">
    {_specimen_tag(entry.taxonomy)}
    <h2{title_id} class="plate-title">{_esc(entry.common_name)}</h2>
    <p class="plate-subtitle">{_esc(entry.scientific_name)}</p>
    {desc_html}
    <div class="plate-foot">
      {chr(10).join("      " + link for link in foot_links).strip()}
    </div>
  </div>
</{tag}>
""".strip()


def _render_card(entry: SiteEntry) -> str:
    if entry.image_url:
        thumb = (
            f'<div class="card-thumb">'
            f'<img src="{_esc(entry.image_url)}" '
            f'alt="{_esc(entry.common_name)}" loading="lazy" />'
            f'</div>'
        )
    else:
        thumb = '<div class="card-thumb"><div class="empty"></div></div>'

    number_html = (
        f'<span><span class="glyph">№</span>&nbsp;{entry.number}</span>'
        if entry.number
        else "<span></span>"
    )

    family_tag = ""
    if entry.taxonomy.get("familySciName"):
        family_tag = f'<p class="card-tag">{_esc(entry.taxonomy["familySciName"])}</p>'

    return f"""
<article class="card">
  <a href="{_esc(entry.archive_url)}">
    {thumb}
    <div class="card-meta">
      {number_html}
      <span>{_esc(entry.date_dotted)}</span>
    </div>
    <h3 class="card-name">{_esc(entry.common_name)}</h3>
    <p class="card-sci">{_esc(entry.scientific_name)}</p>
    {family_tag}
  </a>
</article>
""".strip()


_FAVICON_SVG = (
    "data:image/svg+xml,"
    "%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E"
    "%3Crect width='64' height='64' fill='%23F4EEE0'/%3E"
    "%3Cpath d='M6 38 Q 20 12, 32 32 Q 44 12, 58 38' fill='none' "
    "stroke='%230E5F66' stroke-width='4' stroke-linecap='round'/%3E"
    "%3C/svg%3E"
)


_THEME_BOOT_SCRIPT = (
    "<script>(function(){try{var s=localStorage.getItem('bird-theme');"
    "if(s==='light'||s==='dark')document.documentElement.dataset.theme=s;}"
    "catch(e){}})();</script>"
)


def _page(
    title: str, body: str, feed_link: str, active: str, author: str = ""
) -> str:
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_esc(title)}</title>
  <meta name="description" content="Cada día, una especie de ave. Con sesgo ibérico, pero sin fronteras.">
  <meta name="theme-color" content="#F4EEE0" media="(prefers-color-scheme: light)">
  <meta name="theme-color" content="#0F1518" media="(prefers-color-scheme: dark)">
  <link rel="icon" type="image/svg+xml" href="{_FAVICON_SVG}">
  <link rel="alternate" type="application/rss+xml" title="Ave del Día" href="feed.xml">
  {_THEME_BOOT_SCRIPT}
  <style>{_CSS}</style>
</head>
<body>
{_render_header(active, feed_link)}
<main id="main">
{body}
</main>
{_render_footer(author)}
</body>
</html>
"""


def build_index(
    entries: list[SiteEntry], feed_link: str, author: str = ""
) -> str:
    if not entries:
        body = (
            "<p>Aún no hay aves publicadas. Vuelve mañana.</p>\n"
            + _render_subscribe()
        )
        return _page("Ave del Día", body, feed_link, active="home", author=author)

    hero = entries[0]
    grid_entries = entries[1 : 1 + INDEX_GRID_SIZE]
    grid_html = ""
    if grid_entries:
        cards = "\n".join(_render_card(e) for e in grid_entries)
        grid_html = f"""
<div class="section-divider"><span class="label">Aves recientes</span></div>
<div class="grid">
{cards}
</div>
""".strip()

    body = "\n".join([_render_plate(hero, hero=True), _render_subscribe(), grid_html])
    return _page(
        f"{hero.common_name} — Ave del Día",
        body,
        feed_link,
        active="home",
        author=author,
    )


def build_archive(
    entries: list[SiteEntry], feed_link: str, author: str = ""
) -> str:
    if not entries:
        body = "<p>El archivo está vacío.</p>\n" + _render_subscribe()
        return _page(
            "Archivo — Ave del Día", body, feed_link, active="archive", author=author
        )
    body_parts = [
        '<div class="archive-intro">',
        "<h1>Archivo</h1>",
        "<p>Todas las aves publicadas hasta la fecha.</p>",
        "</div>",
        _render_subscribe(),
    ]
    body_parts.extend(_render_plate(e, hero=False) for e in entries)
    return _page(
        "Archivo — Ave del Día",
        "\n".join(body_parts),
        feed_link,
        active="archive",
        author=author,
    )


def write_site(
    entries: list[SiteEntry],
    output_dir: Path,
    feed_link: str = "",
    author: str = "",
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    index_html = build_index(entries, feed_link, author=author)
    archive_html = build_archive(entries, feed_link, author=author)
    (output_dir / "index.html").write_text(index_html, encoding="utf-8")
    (output_dir / "archive.html").write_text(archive_html, encoding="utf-8")
    logger.info("Site written: index.html, archive.html (%d entries)", len(entries))
