"""
Sitemap reader — lists the UNSW pages to index, with their <lastmod> dates.

UNSW publishes every page in https://www.unsw.edu.au/sitemap.xml. Each entry's
<lastmod> tells us when the page last changed, so refresh.py only needs to
fetch pages that are new or whose lastmod moved since the previous run.
"""

import os
from urllib.parse import urlparse

import httpx
from lxml import etree
from protego import Protego

from scraper import settings as crawler_settings


def _get(url):
    response = httpx.get(
        url,
        headers={"User-Agent": crawler_settings.USER_AGENT},
        follow_redirects=True,
        timeout=60.0,
    )
    response.raise_for_status()
    return response


def fetch_sitemap(url=None):
    """
    Download a sitemap (or sitemap index) and return {url: lastmod}.

    lastmod is the raw date string from the sitemap ("" if missing).
    """
    url = url or crawler_settings.SITEMAP_URL
    root = etree.fromstring(_get(url).content)

    # A sitemap index points at further sitemaps
    if etree.QName(root).localname == "sitemapindex":
        entries = {}
        for loc in root.iterfind("{*}sitemap/{*}loc"):
            entries.update(fetch_sitemap(loc.text.strip()))
        return entries

    entries = {}
    for url_el in root.iterfind("{*}url"):
        loc = (url_el.findtext("{*}loc") or "").strip()
        if loc:
            entries[loc] = (url_el.findtext("{*}lastmod") or "").strip()
    return entries


def _should_skip_url(url):
    """Check if URL matches any ignored patterns or file types."""
    url_lower = url.lower() + "/"
    for pattern in crawler_settings.IGNORED_URL_PATTERNS:
        if pattern in url_lower:
            return True
    ext = os.path.splitext(urlparse(url).path)[1].lower()
    return ext in crawler_settings.IGNORED_EXTENSIONS


def select_pages(entries, paths=None):
    """Keep only sitemap entries under the configured path prefixes."""
    paths = paths or crawler_settings.SITEMAP_PATHS
    selected = {}
    for url, lastmod in entries.items():
        parsed = urlparse(url)
        if parsed.netloc not in crawler_settings.ALLOWED_DOMAINS:
            continue
        path = parsed.path.rstrip("/")
        if not any(path == p or path.startswith(p + "/") for p in paths):
            continue
        if _should_skip_url(url):
            continue
        selected[url] = lastmod
    return selected


def crawl_delay(site_url=None):
    """
    Seconds to wait between requests: CRAWL_DELAY, or robots.txt's
    Crawl-delay for our user agent if that is longer.
    """
    site_url = site_url or crawler_settings.SITEMAP_URL
    parsed = urlparse(site_url)
    delay = crawler_settings.DOWNLOAD_DELAY
    try:
        robots = _get(f"{parsed.scheme}://{parsed.netloc}/robots.txt").text
        robots_delay = Protego.parse(robots).crawl_delay(crawler_settings.USER_AGENT)
    except httpx.HTTPError:
        robots_delay = None
    if robots_delay:
        delay = max(delay, float(robots_delay))
    return delay


if __name__ == "__main__":
    pages = select_pages(fetch_sitemap())
    print(f"{len(pages)} pages under {crawler_settings.SITEMAP_PATHS}")
    print(f"Crawl delay: {crawl_delay()}s")
