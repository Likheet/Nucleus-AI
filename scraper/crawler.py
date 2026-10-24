"""
UNSW Website Crawler — Scrapy Spider

Fetches a given list of UNSW pages (picked from the sitemap by
scraper/refresh.py), extracts structured content (title, headings, body
text, breadcrumbs), and yields each page as a dict with its source URL
preserved for citation in the RAG pipeline. It does not follow links.
"""

import re
from datetime import datetime, timezone

import scrapy
from bs4 import BeautifulSoup

from scraper import settings as crawler_settings


# Elements whose text becomes section content
TEXT_BLOCKS = ("p", "li", "td", "dd", "dt")


class UNSWSpider(scrapy.Spider):
    """Spider that fetches UNSW student-facing pages listed in the sitemap."""

    name = "unsw_spider"
    allowed_domains = crawler_settings.ALLOWED_DOMAINS
    custom_settings = {
        # One request at a time; DOWNLOAD_DELAY is set by the caller from
        # robots.txt's Crawl-delay.
        "CONCURRENT_REQUESTS": 1,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 1,
        "DOWNLOAD_DELAY_JITTER": 0,
        "ROBOTSTXT_OBEY": True,
        "USER_AGENT": crawler_settings.USER_AGENT,
        # Always fetch fresh copies: lastmod already tells us what changed.
        "HTTPCACHE_ENABLED": False,
        "LOG_LEVEL": crawler_settings.LOG_LEVEL,
        "RETRY_TIMES": crawler_settings.RETRY_TIMES,
        "RETRY_HTTP_CODES": crawler_settings.RETRY_HTTP_CODES,
    }

    def __init__(self, urls=(), *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.urls = list(urls)
        self.page_count = 0

    async def start(self):
        for url in self.urls:
            yield scrapy.Request(
                url, callback=self.parse, dont_filter=True,
                meta={"sitemap_url": url},
            )

    def parse(self, response):
        """Parse a page and extract its content."""
        # Skip non-HTML responses
        content_type = response.headers.get("Content-Type", b"").decode("utf-8", "ignore")
        if "text/html" not in content_type:
            return

        page_data = self._extract_content(response)
        # Key pages by their sitemap URL (stable across redirects)
        page_data["url"] = response.meta["sitemap_url"]
        self.page_count += 1
        self.logger.info(
            f"[{self.page_count}/{len(self.urls)}] Fetched: {page_data['url']} "
            f"({len(page_data['content'])} chars)"
        )
        yield page_data

    def _extract_content(self, response):
        """Extract structured content from an HTML page."""
        soup = BeautifulSoup(response.text, "lxml")

        # Breadcrumbs (read before nav/header and .breadcrumb are removed)
        breadcrumbs = []
        breadcrumb_el = soup.find(class_=re.compile(r"breadcrumb", re.I))
        if breadcrumb_el:
            breadcrumbs = [
                a.get_text(strip=True)
                for a in breadcrumb_el.find_all("a")
                if a.get_text(strip=True)
            ]

        # Remove unwanted elements
        for tag in soup.find_all(
            ["script", "style", "nav", "footer", "header", "noscript", "iframe"]
        ):
            tag.decompose()

        # Remove common UI elements that aren't content
        for selector in [
            ".cookie-banner",
            ".site-header",
            ".site-footer",
            ".breadcrumb",
            ".sidebar",
            ".nav",
            ".menu",
            ".social-share",
            ".back-to-top",
            "#skip-to-content",
        ]:
            for el in soup.select(selector):
                el.decompose()

        # Title
        title = ""
        title_tag = soup.find("title")
        if title_tag:
            title = title_tag.get_text(strip=True)
            # Remove " | UNSW Sydney" / " | Current Students – UNSW Sydney" suffix
            title = re.sub(r"\s*\|[^|]*UNSW[^|]*$", "", title)

        # H1
        h1 = ""
        h1_tag = soup.find("h1")
        if h1_tag:
            h1 = h1_tag.get_text(strip=True)

        # Meta description
        meta_desc = ""
        meta_tag = soup.find("meta", attrs={"name": "description"})
        if meta_tag:
            meta_desc = meta_tag.get("content", "")

        # Main content — try to find the main content area
        main_content = (
            soup.find("main")
            or soup.find("article")
            or soup.find(role="main")
            or soup.find(id=re.compile(r"content|main", re.I))
            or soup.find(class_=re.compile(r"content|main", re.I))
        )

        if main_content:
            content_text = self._clean_text(main_content.get_text(separator="\n"))
        else:
            body = soup.find("body")
            content_text = self._clean_text(body.get_text(separator="\n")) if body else ""

        # Extract section headings with their content
        sections = self._extract_sections(main_content or soup)

        return {
            "url": response.url,
            "title": title or h1,
            "h1": h1,
            "meta_description": meta_desc,
            "breadcrumbs": breadcrumbs,
            "content": content_text,
            "sections": sections,
            "last_crawled": datetime.now(timezone.utc).isoformat(),
        }

    def _extract_sections(self, element):
        """Extract content organized by section headings."""
        if not element:
            return []

        sections = []
        current_heading = ""
        current_content = []

        for child in element.descendants:
            if child.name in ("h1", "h2", "h3", "h4"):
                # Save previous section
                if current_content:
                    text = self._clean_text("\n".join(current_content))
                    if text:
                        sections.append({
                            "heading": current_heading,
                            "content": text,
                        })
                current_heading = child.get_text(strip=True)
                current_content = []
            elif child.name in TEXT_BLOCKS and child.find_parent(TEXT_BLOCKS) is None:
                # Outermost text blocks only: nested divs/spans would repeat
                # the same text many times over
                text = child.get_text(" ", strip=True)
                if text and len(text) > 10:  # Skip very short fragments
                    current_content.append(text)

        # Don't forget the last section
        if current_content:
            text = self._clean_text("\n".join(current_content))
            if text:
                sections.append({
                    "heading": current_heading,
                    "content": text,
                })

        return sections

    def _clean_text(self, text):
        """Clean extracted text: normalize whitespace, remove empty lines."""
        if not text:
            return ""
        # Normalize whitespace within lines
        lines = text.split("\n")
        cleaned = []
        for line in lines:
            line = re.sub(r"\s+", " ", line).strip()
            if line and len(line) > 3:  # Skip very short noise lines
                cleaned.append(line)
        # Remove duplicate consecutive lines
        deduped = []
        for line in cleaned:
            if not deduped or line != deduped[-1]:
                deduped.append(line)
        return "\n".join(deduped)
