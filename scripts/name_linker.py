"""Species name substitution and cross-linking in description text.

Scans a raw description for English bird species names (2+ words,
word-boundary matched, longest-first) and replaces them with their
localised equivalents. When the referenced species has been published,
the name is wrapped in a hyperlink to its archive entry.

Processing happens at render time (not cached) because the set of
published species changes daily — a link to a "future" bird appears
retroactively the day that bird is published and the site is rebuilt.
"""

from __future__ import annotations

import html
import re


def process_description(
    raw_text: str,
    english_name_index: dict[str, str],
    code_to_localized: dict[str, str],
    published_anchors: dict[str, str],
) -> str:
    """Substitute English bird names and hyperlink published species.

    Parameters
    ----------
    raw_text:
        The raw description string (not HTML-escaped).
    english_name_index:
        English ``comName`` → ``speciesCode`` mapping.  Only names
        with 2+ words are considered (single-word names like "Wren",
        "Robin", "Martin" are too ambiguous).
    code_to_localized:
        ``speciesCode`` → localised ``comName`` mapping.
    published_anchors:
        ``speciesCode`` → anchor URL for species that have been
        published.  Relative for the site, absolute for the RSS feed.

    Returns
    -------
    str
        HTML string.  Non-matched text is HTML-escaped; matched names
        are replaced with escaped localised names, optionally wrapped
        in ``<a href>`` tags.  The caller inserts the result as raw
        HTML — do NOT escape further.
    """
    if not raw_text or not english_name_index:
        return html.escape(raw_text or "")

    # 2+ word names only, longest first.
    candidates = [
        (name, code)
        for name, code in english_name_index.items()
        if " " in name
    ]
    candidates.sort(key=lambda x: len(x[0]), reverse=True)

    # Pre-filter: skip names whose words don't appear in the text.
    text_lower = raw_text.lower()

    matches: list[tuple[int, int, str]] = []  # (start, end, speciesCode)
    occupied: set[int] = set()

    for name, code in candidates:
        if not all(w in text_lower for w in name.lower().split()):
            continue
        pattern = re.compile(r"\b" + re.escape(name) + r"\b", re.IGNORECASE)
        for m in pattern.finditer(raw_text):
            start, end = m.start(), m.end()
            if not any(pos in occupied for pos in range(start, end)):
                matches.append((start, end, code))
                occupied.update(range(start, end))

    if not matches:
        return html.escape(raw_text)

    matches.sort(key=lambda x: x[0])

    parts: list[str] = []
    prev_end = 0
    for start, end, code in matches:
        parts.append(html.escape(raw_text[prev_end:start]))
        localized = code_to_localized.get(code, raw_text[start:end])
        escaped_name = html.escape(localized)
        if code in published_anchors:
            anchor = html.escape(published_anchors[code], quote=True)
            parts.append(f'<a href="{anchor}">{escaped_name}</a>')
        else:
            parts.append(escaped_name)
        prev_end = end
    parts.append(html.escape(raw_text[prev_end:]))

    return "".join(parts)
