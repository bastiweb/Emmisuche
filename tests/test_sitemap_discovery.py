from __future__ import annotations

import logging

from app.crawler.sitemap import discover_sitemap_urls


def test_nested_sitemap_discovery_and_url_deduplication() -> None:
    root = """<?xml version="1.0" encoding="UTF-8"?>
    <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <sitemap><loc>https://example.com/post-sitemap.xml</loc></sitemap>
      <sitemap><loc>https://example.com/post-sitemap-nested.xml</loc></sitemap>
      <sitemap><loc>https://example.com/category-sitemap.xml</loc></sitemap>
    </sitemapindex>"""
    post = """<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://example.com/recipe-a/</loc><lastmod>2026-04-10T00:00:00+00:00</lastmod></url>
      <url><loc>https://example.com/recipe-b</loc><lastmod>2026-04-10T00:00:00+00:00</lastmod></url>
      <url><loc>https://other.com/offsite/</loc></url>
    </urlset>"""
    nested_index = """<?xml version="1.0" encoding="UTF-8"?>
    <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <sitemap><loc>https://example.com/post-sitemap-part2.xml</loc></sitemap>
    </sitemapindex>"""
    part2 = """<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://example.com/recipe-a</loc><lastmod>2026-04-11T00:00:00+00:00</lastmod></url>
      <url><loc>https://example.com/recipe-c</loc></url>
    </urlset>"""
    category = """<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://example.com/category/suppe/</loc></url>
    </urlset>"""

    payloads = {
        "https://example.com/sitemap_index.xml": root,
        "https://example.com/post-sitemap.xml": post,
        "https://example.com/post-sitemap-nested.xml": nested_index,
        "https://example.com/post-sitemap-part2.xml": part2,
        "https://example.com/category-sitemap.xml": category,
    }

    def fetch_text(url: str) -> str:
        return payloads[url]

    metrics: dict[str, int] = {}
    entries = discover_sitemap_urls(
        sitemap_index_url="https://example.com/sitemap_index.xml",
        allowed_domain="example.com",
        allow_non_https=False,
        include_sitemap_keywords=["post-sitemap"],
        include_url_keywords=[],
        fetch_text=fetch_text,
        logger=logging.getLogger("test"),
        metrics=metrics,
    )

    urls = sorted(entry.url for entry in entries)
    assert urls == [
        "https://example.com/recipe-a",
        "https://example.com/recipe-b",
        "https://example.com/recipe-c",
    ]
    assert metrics["discovered_sitemaps"] == 5
    assert metrics["discovered_url_entries"] == 6
    assert metrics["candidate_urls"] == 3
    assert metrics["duplicate_urls"] >= 1
