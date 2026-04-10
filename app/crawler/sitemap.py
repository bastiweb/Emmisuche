from __future__ import annotations

import logging
import re
from collections import deque
from urllib.parse import urlparse, urlunparse
from xml.etree import ElementTree

from app.models import SitemapUrlEntry


SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}


def _clean_url(url: str) -> str:
    raw = url.strip()
    parsed = urlparse(raw)
    scheme = (parsed.scheme or "https").lower()
    netloc = parsed.netloc.lower()
    path = parsed.path or "/"
    path = re.sub(r"/{2,}", "/", path)
    if path != "/":
        path = path.rstrip("/")
    return urlunparse((scheme, netloc, path, "", "", ""))


def _is_same_domain(url: str, allowed_domain: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return host == allowed_domain or host.endswith(f".{allowed_domain}")


def _is_allowed_scheme(url: str, allow_non_https: bool) -> bool:
    scheme = (urlparse(url).scheme or "").lower()
    if scheme == "https":
        return True
    return allow_non_https and scheme in {"http"}


def _is_relevant_sitemap(
    sitemap_url: str, include_sitemap_keywords: list[str]
) -> bool:
    if not include_sitemap_keywords:
        return True
    lowered = sitemap_url.lower()
    return any(keyword.lower() in lowered for keyword in include_sitemap_keywords)


def _is_relevant_page_url(url: str, include_url_keywords: list[str]) -> bool:
    if not include_url_keywords:
        return True
    lowered = url.lower()
    return any(keyword.lower() in lowered for keyword in include_url_keywords)


def parse_sitemap_xml(
    xml_content: str, sitemap_url: str
) -> tuple[list[str], list[SitemapUrlEntry]]:
    root = ElementTree.fromstring(xml_content.encode("utf-8"))
    tag = root.tag.lower()

    nested_sitemaps: list[str] = []
    urls: list[SitemapUrlEntry] = []

    if tag.endswith("sitemapindex"):
        for sitemap in root.findall("sm:sitemap", SITEMAP_NS):
            loc = sitemap.findtext("sm:loc", default="", namespaces=SITEMAP_NS).strip()
            if not loc:
                continue
            nested_sitemaps.append(_clean_url(loc))
        return nested_sitemaps, urls

    if tag.endswith("urlset"):
        for item in root.findall("sm:url", SITEMAP_NS):
            loc = item.findtext("sm:loc", default="", namespaces=SITEMAP_NS).strip()
            if not loc:
                continue
            lastmod = item.findtext(
                "sm:lastmod", default="", namespaces=SITEMAP_NS
            ).strip()
            urls.append(
                SitemapUrlEntry(
                    url=_clean_url(loc),
                    lastmod=lastmod or None,
                    sitemap_url=sitemap_url,
                )
            )
        return nested_sitemaps, urls

    return nested_sitemaps, urls


def discover_sitemap_urls(
    *,
    sitemap_index_url: str,
    allowed_domain: str,
    allow_non_https: bool,
    include_sitemap_keywords: list[str],
    include_url_keywords: list[str],
    fetch_text,
    logger: logging.Logger,
) -> list[SitemapUrlEntry]:
    visited_sitemaps: set[str] = set()
    queued = deque([sitemap_index_url])
    discovered: dict[str, SitemapUrlEntry] = {}

    while queued:
        current_sitemap = queued.popleft().strip()
        if not current_sitemap or current_sitemap in visited_sitemaps:
            continue
        visited_sitemaps.add(current_sitemap)

        if not _is_same_domain(current_sitemap, allowed_domain):
            logger.debug("Skipping out-of-domain sitemap: %s", current_sitemap)
            continue

        if not _is_allowed_scheme(current_sitemap, allow_non_https):
            logger.debug("Skipping non-allowed sitemap scheme: %s", current_sitemap)
            continue

        try:
            xml_content = fetch_text(current_sitemap)
        except Exception as exc:
            logger.warning("Failed to fetch sitemap %s: %s", current_sitemap, exc)
            continue

        try:
            nested_sitemaps, page_urls = parse_sitemap_xml(xml_content, current_sitemap)
        except ElementTree.ParseError as exc:
            logger.warning("Invalid XML sitemap %s: %s", current_sitemap, exc)
            continue

        for nested in nested_sitemaps:
            if nested not in visited_sitemaps:
                queued.append(nested)

        if not _is_relevant_sitemap(current_sitemap, include_sitemap_keywords):
            continue

        for entry in page_urls:
            if not _is_same_domain(entry.url, allowed_domain):
                continue
            if not _is_allowed_scheme(entry.url, allow_non_https):
                continue
            if not _is_relevant_page_url(entry.url, include_url_keywords):
                continue

            existing = discovered.get(entry.url)
            if existing is None or (entry.lastmod and not existing.lastmod):
                discovered[entry.url] = entry

    return list(discovered.values())
