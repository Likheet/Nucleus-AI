"""
UNSW Website Crawler — Scrapy Spider + Pipeline

Crawls targeted UNSW web pages, extracts structured content (title, headings,
body text, breadcrumbs), and saves each page as a JSON document with its
source URL preserved for citation in the RAG pipeline.
"""

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import scrapy
from bs4 import BeautifulSoup

from scraper import settings as crawler_settings


class UNSWSpider(scrapy.Spider):
    """Spider that crawls UNSW student-facing pages."""

    name = "unsw_spider"
    allowed_domains = crawler_settings.ALLOWED_DOMAINS
    start_urls = crawler_settings.START_URLS
    custom_settings = {
        "DEPTH_LIMIT": crawler_settings.DEPTH_LIMIT,
        "DOWNLOAD_DELAY": crawler_settings.DOWNLOAD_DELAY,
        "CONCURRENT_REQUESTS": 4,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 2,
        "ROBOTSTXT_OBEY": True,
        "USER_AGENT": crawler_settings.USER_AGENT,
        "HTTPCACHE_ENABLED": crawler_settings.HTTPCACHE_ENABLED,
        "HTTPCACHE_EXPIRATION_SECS": crawler_settings.HTTPCACHE_EXPIRATION_SECS,
        "HTTPCACHE_DIR": crawler_settings.HTTPCACHE_DIR,
        "LOG_LEVEL": crawler_settings.LOG_LEVEL,
        "ITEM_PIPELINES": crawler_settings.ITEM_PIPELINES,
        "RETRY_TIMES": crawler_settings.RETRY_TIMES,
        "RETRY_HTTP_CODES": crawler_settings.RETRY_HTTP_CODES,
        "CLOSESPIDER_PAGECOUNT": crawler_settings.MAX_PAGES,
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.visited_urls = set()
        self.page_count = 0

    def parse(self, response):
        """Parse a page: extract content and follow internal links."""
        url = response.url

        # Skip if already visited (normalized)
        normalized = self._normalize_url(url)
        if normalized in self.visited_urls:
            return
        self.visited_urls.add(normalized)

        # Skip non-HTML responses
        content_type = response.headers.get("Content-Type", b"").decode("utf-8", "ignore")
        if "text/html" not in content_type:
            return

        # Skip ignored URL patterns
        if self._should_skip_url(url):
            return

        # Extract page content
        page_data = self._extract_content(response)
        if page_data and page_data.get("content", "").strip():
            self.page_count += 1
            self.logger.info(
                f"[{self.page_count}] Crawled: {url} "
                f"({len(page_data['content'])} chars)"
            )
            yield page_data

        # Follow internal links
        for href in response.css("a::attr(href)").getall():
            full_url = urljoin(url, href)
            if self._is_valid_link(full_url):
                normalized_link = self._normalize_url(full_url)
                if normalized_link not in self.visited_urls:
                    yield scrapy.Request(full_url, callback=self.parse)

    def _extract_content(self, response):
        """Extract structured content from an HTML page."""
        soup = BeautifulSoup(response.text, "lxml")

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
            # Remove " | UNSW Sydney" suffix if present
            title = re.sub(r"\s*\|\s*UNSW.*$", "", title)

        # H1
        h1 = ""
        h1_tag = soup.find("h1")
        if h1_tag:
            h1 = h1_tag.get_text(strip=True)

        # Breadcrumbs
        breadcrumbs = []
        breadcrumb_el = soup.find(class_=re.compile(r"breadcrumb", re.I))
        if breadcrumb_el:
            breadcrumbs = [
                a.get_text(strip=True)
                for a in breadcrumb_el.find_all("a")
                if a.get_text(strip=True)
            ]

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
            elif child.name in ("p", "li", "td", "dd", "dt", "span", "div"):
                text = child.get_text(strip=True)
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

    def _normalize_url(self, url):
        """Normalize URL for deduplication."""
        parsed = urlparse(url)
        # Remove fragment and trailing slash
        path = parsed.path.rstrip("/")
        return f"{parsed.scheme}://{parsed.netloc}{path}"

    def _should_skip_url(self, url):
        """Check if URL matches any ignored patterns."""
        url_lower = url.lower()
        for pattern in crawler_settings.IGNORED_URL_PATTERNS:
            if pattern in url_lower:
                return True
        # Check file extensions
        parsed = urlparse(url)
        ext = os.path.splitext(parsed.path)[1].lower()
        if ext in crawler_settings.IGNORED_EXTENSIONS:
            return True
        return False

    def _is_valid_link(self, url):
        """Check if a URL is worth following."""
        if not url or not url.startswith("http"):
            return False
        parsed = urlparse(url)
        if parsed.netloc not in self.allowed_domains:
            return False
        if self._should_skip_url(url):
            return False
        return True


class JsonWriterPipeline:
    """Pipeline that writes each crawled page to a JSON file."""

    def open_spider(self, spider):
        """Create output directory when spider starts."""
        self.output_dir = Path(crawler_settings.RAW_DATA_DIR)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.items_file = self.output_dir / "all_pages.jsonl"
        self.file = open(self.items_file, "w", encoding="utf-8")
        self.count = 0

    def close_spider(self, spider):
        """Close file when spider finishes."""
        self.file.close()
        spider.logger.info(
            f"Crawl complete! {self.count} pages saved to {self.items_file}"
        )

    def process_item(self, item, spider):
        """Write each item as a JSON line."""
        line = json.dumps(dict(item), ensure_ascii=False) + "\n"
        self.file.write(line)
        self.count += 1
        return item


# --- CLI Entry Point ---
def run_crawler():
    """Run the UNSW spider from the command line."""
    from scrapy.crawler import CrawlerProcess

    # Create data directories
    Path(crawler_settings.RAW_DATA_DIR).mkdir(parents=True, exist_ok=True)
    Path(crawler_settings.CHUNKS_DIR).mkdir(parents=True, exist_ok=True)

    process = CrawlerProcess(
        settings={
            "BOT_NAME": crawler_settings.BOT_NAME,
            "ROBOTSTXT_OBEY": True,
            "LOG_LEVEL": crawler_settings.LOG_LEVEL,
            "LOG_FORMAT": crawler_settings.LOG_FORMAT,
        }
    )
    process.crawl(UNSWSpider)
    process.start()


if __name__ == "__main__":
    run_crawler()
