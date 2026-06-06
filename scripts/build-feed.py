#!/usr/bin/env python3
"""
Build feed.xml from sitemap.xml.

For each URL in sitemap.xml that points to a local *.html article, parse:
  - <title>
  - <meta name="description">
  - <html lang>
  - <meta property="article:published_time"> (or fall back to git "added" date)
  - last git commit date for that file -> dateModified

Sort items by published date descending and write feed.xml at the repo root.

This script is idempotent: running it twice without HTML changes yields the
same feed.xml byte-for-byte. The Action only commits when feed.xml actually
changes.
"""
from __future__ import annotations
import html
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
SITE = "https://eaglhuang.github.io/AI-learning-notes"
SITEMAP = ROOT / "sitemap.xml"
FEED = ROOT / "feed.xml"

# Channel-level metadata (kept stable so re-runs don't churn the file)
CHANNEL_TITLE = "AI Learning Notes"
CHANNEL_LINK = f"{SITE}/"
CHANNEL_DESC = (
    "Engineering notes on multi-AI collaboration, agent governance, "
    "prompt engineering, and shipping production AI systems — by Eagl Huang."
)
CHANNEL_AUTHOR = "Eagl Huang"
CHANNEL_EMAIL = "noreply@eaglhuang.github.io"
CHANNEL_IMAGE = f"{SITE}/assets/og/atm_atomic_foundry_en.svg"

SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

# Pinned dates for articles that were authored before git was tracking them
# carefully. Add overrides here if needed; otherwise git "added" date is used.
PINNED_DATES: dict[str, str] = {
    # "filename.html": "YYYY-MM-DD",
}


def git_added_date(path: Path) -> datetime | None:
    """Return the date the file was first added to git (committer date)."""
    try:
        out = subprocess.check_output(
            ["git", "log", "--diff-filter=A", "--follow", "--format=%aI", "--", str(path.relative_to(ROOT))],
            cwd=ROOT, text=True, stderr=subprocess.DEVNULL,
        ).strip().splitlines()
        if out:
            return datetime.fromisoformat(out[-1])
    except (subprocess.CalledProcessError, ValueError):
        pass
    return None


def git_modified_date(path: Path) -> datetime | None:
    """Return the date of the most recent commit touching the file."""
    try:
        out = subprocess.check_output(
            ["git", "log", "-1", "--format=%aI", "--", str(path.relative_to(ROOT))],
            cwd=ROOT, text=True, stderr=subprocess.DEVNULL,
        ).strip()
        if out:
            return datetime.fromisoformat(out)
    except (subprocess.CalledProcessError, ValueError):
        pass
    return None


def extract_meta(html_path: Path) -> dict[str, str | None]:
    """Pull title, description, lang, and article:published_time from an HTML file."""
    try:
        content = html_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}

    def search(pattern: str, group: int = 1, flags: int = re.IGNORECASE | re.DOTALL) -> str | None:
        m = re.search(pattern, content, flags)
        return m.group(group).strip() if m else None

    # For meta tags, use a backreferenced quote so apostrophes in the
    # content (e.g. "Git's") don't truncate the capture.
    return {
        "title": search(r"<title>([^<]+)</title>"),
        "description": search(r'<meta\s+name=(["\'])description\1\s+content=(["\'])(.*?)\2', group=3),
        "lang": search(r'<html[^>]*\blang=(["\'])([^"\']+)\1', group=2),
        "published": search(r'<meta\s+property=(["\'])article:published_time\1\s+content=(["\'])(.*?)\2', group=3),
    }


def url_to_local_path(url: str) -> Path | None:
    """Map a sitemap URL to a local file. Skips directory URLs and the site root."""
    if not url.startswith(SITE):
        return None
    tail = url[len(SITE):].lstrip("/")
    # Skip the homepage and the article-list directory
    if tail in ("", "articles/"):
        return None
    # Only generate items for article HTML pages
    if not tail.endswith(".html"):
        return None
    path = ROOT / tail
    return path if path.exists() else None


def to_rfc822(dt: datetime) -> str:
    """Convert datetime to RFC 822 (RSS spec) format. Always +0800."""
    # Normalize to UTC+8 to keep all items in the same timezone for stability
    tz_tw = timezone.utc.utcoffset(dt) if dt.tzinfo is None else dt.utcoffset()
    # Use UTC+8 throughout for visual consistency
    dt_local = dt.astimezone(timezone(offset=__import__("datetime").timedelta(hours=8)))
    # %a and %b are locale-sensitive — force C locale via explicit table
    weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    wd = weekdays[dt_local.weekday()]
    mo = months[dt_local.month - 1]
    return f"{wd}, {dt_local.day:02d} {mo} {dt_local.year} {dt_local.hour:02d}:{dt_local.minute:02d}:{dt_local.second:02d} +0800"


def categorize(meta: dict[str, str | None], filename: str) -> list[str]:
    """Derive 1-3 category tags from filename + description keywords."""
    name = filename.lower()
    desc = (meta.get("description") or "").lower()
    cats: list[str] = []

    if "atm_atomic_foundry" in name or "atomic foundry" in desc or "5d cid" in desc:
        cats += ["AI Engineering", "Multi-Agent", "Governance"]
    elif "cid_parallel" in name or "conflict advisor" in desc:
        cats += ["Multi-Agent", "AI Engineering"]
    elif "atom_map" in name:
        cats += ["Legacy Refactor", "AI Engineering"]
    elif "harness" in name:
        cats += ["Harness Engineering"]
    elif "rag_etl" in name:
        cats += ["RAG", "ETL"]
    elif "multi_agent_dispatch" in name or "agent_collaboration" in name:
        cats += ["Multi-Agent"]
    elif "agent_mode_prompt" in name or "ai_personality_prompt" in name:
        cats += ["Prompt Engineering"]
    elif "codex_subagents" in name:
        cats += ["Codex", "Multi-Agent"]
    else:
        cats += ["AI Engineering"]
    return cats[:3]


def collect_items() -> list[dict]:
    if not SITEMAP.exists():
        print(f"sitemap not found: {SITEMAP}", file=sys.stderr)
        sys.exit(1)

    tree = ET.parse(SITEMAP)
    items: list[dict] = []
    for url_el in tree.getroot().findall("sm:url", SITEMAP_NS):
        loc_el = url_el.find("sm:loc", SITEMAP_NS)
        if loc_el is None or not loc_el.text:
            continue
        url = loc_el.text.strip()
        local = url_to_local_path(url)
        if local is None:
            continue
        meta = extract_meta(local)
        if not meta.get("title"):
            continue

        # Resolve dates
        filename = local.name
        if filename in PINNED_DATES:
            published = datetime.fromisoformat(PINNED_DATES[filename] + "T09:00:00+08:00")
        elif meta.get("published"):
            try:
                published = datetime.fromisoformat(meta["published"])
                if published.tzinfo is None:
                    published = published.replace(tzinfo=timezone(offset=__import__("datetime").timedelta(hours=8)))
            except ValueError:
                published = git_added_date(local) or datetime.now(timezone.utc)
        else:
            published = git_added_date(local) or datetime.now(timezone.utc)

        modified = git_modified_date(local) or published

        items.append({
            "url": url,
            "title": html.unescape(meta["title"]),
            "description": html.unescape(meta.get("description") or ""),
            "lang": meta.get("lang") or "en",
            "published": published,
            "modified": modified,
            "categories": categorize(meta, filename),
        })

    # Sort newest first
    items.sort(key=lambda x: x["published"], reverse=True)
    return items


def render_feed(items: list[dict]) -> str:
    parts: list[str] = []
    parts.append('<?xml version="1.0" encoding="UTF-8"?>')
    parts.append('<rss version="2.0"')
    parts.append('     xmlns:atom="http://www.w3.org/2005/Atom"')
    parts.append('     xmlns:dc="http://purl.org/dc/elements/1.1/"')
    parts.append('     xmlns:content="http://purl.org/rss/1.0/modules/content/">')
    parts.append("  <channel>")
    parts.append(f"    <title>{xml_escape(CHANNEL_TITLE)}</title>")
    parts.append(f"    <link>{CHANNEL_LINK}</link>")
    parts.append(f'    <atom:link href="{SITE}/feed.xml" rel="self" type="application/rss+xml" />')
    parts.append(f"    <description>{xml_escape(CHANNEL_DESC)}</description>")
    parts.append("    <language>en</language>")
    parts.append(f"    <copyright>Copyright (c) {CHANNEL_AUTHOR}</copyright>")
    parts.append(f"    <managingEditor>{CHANNEL_EMAIL} ({CHANNEL_AUTHOR})</managingEditor>")
    parts.append(f"    <webMaster>{CHANNEL_EMAIL} ({CHANNEL_AUTHOR})</webMaster>")
    latest = items[0]["modified"] if items else datetime.now(timezone.utc)
    parts.append(f"    <lastBuildDate>{to_rfc822(latest)}</lastBuildDate>")
    parts.append(f"    <pubDate>{to_rfc822(latest)}</pubDate>")
    parts.append("    <ttl>1440</ttl>")
    parts.append("    <image>")
    parts.append(f"      <url>{CHANNEL_IMAGE}</url>")
    parts.append(f"      <title>{xml_escape(CHANNEL_TITLE)}</title>")
    parts.append(f"      <link>{CHANNEL_LINK}</link>")
    parts.append("    </image>")

    for it in items:
        parts.append("")
        parts.append("    <item>")
        parts.append(f"      <title>{xml_escape(it['title'])}</title>")
        parts.append(f"      <link>{it['url']}</link>")
        parts.append(f'      <guid isPermaLink="true">{it["url"]}</guid>')
        parts.append(f"      <pubDate>{to_rfc822(it['published'])}</pubDate>")
        parts.append(f"      <dc:creator>{xml_escape(CHANNEL_AUTHOR)}</dc:creator>")
        parts.append(f"      <dc:language>{xml_escape(it['lang'])}</dc:language>")
        if it["description"]:
            parts.append(f"      <description><![CDATA[{it['description']}]]></description>")
        for cat in it["categories"]:
            parts.append(f"      <category>{xml_escape(cat)}</category>")
        parts.append("    </item>")

    parts.append("  </channel>")
    parts.append("</rss>")
    return "\n".join(parts) + "\n"


def xml_escape(s: str) -> str:
    return (s.replace("&", "&amp;")
             .replace("<", "&lt;")
             .replace(">", "&gt;"))


def main() -> int:
    items = collect_items()
    if not items:
        print("No items collected from sitemap; refusing to overwrite feed.xml", file=sys.stderr)
        return 1
    feed = render_feed(items)
    existing = FEED.read_text(encoding="utf-8") if FEED.exists() else ""
    if existing == feed:
        print(f"feed.xml is up to date ({len(items)} items)")
        return 0
    FEED.write_text(feed, encoding="utf-8", newline="\n")
    print(f"feed.xml updated ({len(items)} items)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
