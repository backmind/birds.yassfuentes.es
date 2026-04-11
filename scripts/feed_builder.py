"""RSS 2.0 feed builder with content:encoded support."""

from __future__ import annotations

import html
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

CONTENT_NS = "http://purl.org/rss/1.0/modules/content/"
ATOM_NS = "http://www.w3.org/2005/Atom"

ET.register_namespace("content", CONTENT_NS)
ET.register_namespace("atom", ATOM_NS)


@dataclass
class FeedEntry:
    species_code: str
    common_name: str
    scientific_name: str
    description_html: str
    image_url: str | None
    image_attribution: str
    ml_search_url: str
    pub_date: str
    guid: str


def build_entry_html(
    species_code: str,
    common_name: str,
    scientific_name: str,
    image_url: str | None,
    image_attribution: str,
    ml_search_url: str,
    ebird_description: str,
    bow_intro: str,
    taxonomy: dict,
) -> str:
    """Build rich HTML content for an RSS entry."""
    parts: list[str] = []

    # Header
    parts.append(f'<h2>{common_name} — <em>{scientific_name}</em></h2>')

    # Image or fallback link
    if image_url:
        parts.append(
            f'<img src="{image_url}" '
            f'alt="{common_name} © {image_attribution}" '
            f'style="max-width:100%; border-radius:8px;" />'
        )
        parts.append(f'<p><em>© {image_attribution}</em></p>')
    else:
        parts.append(
            f'<p><a href="{ml_search_url}">Ver fotos en Macaulay Library</a></p>'
        )

    # Taxonomy table
    order = taxonomy.get("order", "")
    family_sci = taxonomy.get("familySciName", "")
    family_com = taxonomy.get("familyComName", "")
    family_display = f"{family_sci} ({family_com})" if family_com else family_sci

    if order or family_display:
        parts.append("<table>")
        if order:
            parts.append(f"<tr><td><strong>Orden</strong></td><td>{order}</td></tr>")
        if family_display:
            parts.append(
                f"<tr><td><strong>Familia</strong></td><td>{family_display}</td></tr>"
            )
        parts.append(
            f"<tr><td><strong>Nombre científico</strong></td>"
            f"<td><em>{scientific_name}</em></td></tr>"
        )
        parts.append("</table>")

    # eBird description
    if ebird_description:
        parts.append(f"<p>{ebird_description}</p>")

    # Birds of the World intro
    if bow_intro:
        parts.append(f"<p>{bow_intro}</p>")
        parts.append(
            '<p><small>Fuente: <a href="https://birdsoftheworld.org/bow/species/'
            f'{species_code}/cur/introduction">Birds of the World</a>'
            " (Cornell Lab of Ornithology)</small></p>"
        )

    # Links section
    parts.append("<h3>Más información</h3>")
    parts.append("<ul>")
    parts.append(
        f'<li><a href="https://ebird.org/species/{species_code}">'
        "Ficha en eBird</a> — observaciones, mapas, fotos y sonidos</li>"
    )
    parts.append(
        f'<li><a href="https://birdsoftheworld.org/bow/species/{species_code}'
        '/cur/introduction">Birds of the World</a>'
        " — historia natural completa (Cornell Lab)</li>"
    )
    parts.append(
        f'<li><a href="{ml_search_url}">Galería en Macaulay Library</a></li>'
    )
    parts.append("</ul>")

    # Attribution footer
    parts.append(
        "<p><small>Datos de "
        '<a href="https://ebird.org">eBird</a> y '
        '<a href="https://www.birds.cornell.edu/">Cornell Lab of Ornithology</a>.'
        "</small></p>"
    )

    return "\n".join(parts)


def build_feed(entries: list[FeedEntry], config: dict) -> str:
    """Build an RSS 2.0 XML feed string."""
    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")

    # Channel metadata
    ET.SubElement(channel, "title").text = config.get("feed_title", "Ave del Día")
    feed_link = config.get("feed_link", "")
    ET.SubElement(channel, "link").text = feed_link
    ET.SubElement(channel, "description").text = config.get(
        "feed_description", "Una especie de ave nueva cada día."
    )
    ET.SubElement(channel, "language").text = "es"

    # Atom self-link
    if feed_link:
        atom_link = ET.SubElement(channel, f"{{{ATOM_NS}}}link")
        atom_link.set("href", f"{feed_link.rstrip('/')}/feed.xml")
        atom_link.set("rel", "self")
        atom_link.set("type", "application/rss+xml")

    # Copyright
    ET.SubElement(channel, "copyright").text = (
        "Datos: eBird/Cornell Lab of Ornithology (ebird.org). "
        "Fotos: Macaulay Library, © sus respectivos autores. "
        "Proyecto no comercial."
    )

    # Items
    for entry in entries:
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = (
            f"{entry.common_name} ({entry.scientific_name})"
        )
        ET.SubElement(item, "link").text = (
            f"https://ebird.org/species/{entry.species_code}"
        )
        guid = ET.SubElement(item, "guid")
        guid.text = entry.guid
        guid.set("isPermaLink", "false")
        ET.SubElement(item, "pubDate").text = entry.pub_date

        # content:encoded — will be wrapped in CDATA during post-processing
        content_elem = ET.SubElement(item, f"{{{CONTENT_NS}}}encoded")
        content_elem.text = entry.description_html

    # Serialize to string
    tree = ET.ElementTree(rss)
    ET.indent(tree, space="  ")
    xml_bytes = ET.tostring(rss, encoding="unicode", xml_declaration=False)
    xml_string = '<?xml version="1.0" encoding="UTF-8"?>\n' + xml_bytes

    # Post-process: wrap content:encoded in CDATA
    xml_string = _wrap_cdata(xml_string)

    return xml_string


def _wrap_cdata(xml_string: str) -> str:
    """Wrap content:encoded text in CDATA sections."""
    def replacer(match: re.Match) -> str:
        tag_open = match.group(1)
        content = match.group(2)
        tag_close = match.group(3)
        content = html.unescape(content)
        return f"{tag_open}<![CDATA[{content}]]>{tag_close}"

    return re.sub(
        r"(<content:encoded>)(.*?)(</content:encoded>)",
        replacer,
        xml_string,
        flags=re.DOTALL,
    )


def load_existing_feed(feed_path: str) -> list[FeedEntry]:
    """Parse an existing feed.xml and return its entries."""
    path = Path(feed_path)
    if not path.exists():
        return []

    try:
        content = path.read_text(encoding="utf-8")
        # Remove CDATA wrappers so ElementTree can parse
        content = re.sub(r"<!\[CDATA\[", "", content)
        content = re.sub(r"\]\]>", "", content)

        root = ET.fromstring(content)
        entries = []

        for item in root.findall(".//item"):
            title_elem = item.find("title")
            link_elem = item.find("link")
            guid_elem = item.find("guid")
            pub_date_elem = item.find("pubDate")
            content_elem = item.find(f"{{{CONTENT_NS}}}encoded")

            if guid_elem is None or guid_elem.text is None:
                continue

            # Extract species code from link
            species_code = ""
            if link_elem is not None and link_elem.text:
                parts = link_elem.text.rstrip("/").split("/")
                species_code = parts[-1] if parts else ""

            # Parse common_name and scientific_name from title
            common_name = ""
            scientific_name = ""
            if title_elem is not None and title_elem.text:
                title_match = re.match(r"^(.*?)\s*\(([^)]+)\)$", title_elem.text)
                if title_match:
                    common_name = title_match.group(1).strip()
                    scientific_name = title_match.group(2).strip()
                else:
                    common_name = title_elem.text.strip()

            entries.append(
                FeedEntry(
                    species_code=species_code,
                    common_name=common_name,
                    scientific_name=scientific_name,
                    description_html=content_elem.text if content_elem is not None and content_elem.text else "",
                    image_url=None,
                    image_attribution="",
                    ml_search_url="",
                    pub_date=pub_date_elem.text if pub_date_elem is not None and pub_date_elem.text else "",
                    guid=guid_elem.text,
                )
            )

        return entries
    except (ET.ParseError, Exception):
        logger.warning("Failed to parse existing feed at %s", feed_path, exc_info=True)
        return []


def write_feed(xml_string: str, feed_path: str = "feed.xml") -> None:
    path = Path(feed_path)
    path.write_text(xml_string, encoding="utf-8")
    logger.info("Feed written to %s", feed_path)
