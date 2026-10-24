"""
UNSW Handbook Crawler — Optional spider for handbook.unsw.edu.au

    python -m scraper.handbook_crawler             # every course and program
    python -m scraper.handbook_crawler COMP MATH   # only these subject areas' courses

The Handbook lists every page in its sitemap index, each with a <lastmod>
date. This picks the HANDBOOK_YEAR course and program pages, fetches only the
ones that are new or whose lastmod changed since the last run, and writes
data/raw/handbook_pages.jsonl, which `python -m scraper.refresh` indexes.

The Handbook is a Next.js SSR application: each page embeds its data as JSON
in <script id="__NEXT_DATA__">, so structured fields (course code, UOC,
prerequisites, description, etc.) are read from there, no browser needed.
They are kept together so courses can be chunked as atomic units.
"""

import json
import re
from datetime import datetime, timezone

import scrapy
from bs4 import BeautifulSoup

from scraper import settings as crawler_settings

# Elements whose text starts on a new line
BLOCK_TAGS = ["p", "li", "div", "tr", "h1", "h2", "h3", "h4", "h5", "h6"]

FEE_LABELS = {
    "fees_commonwealth": "Commonwealth Supported Students",
    "fees_domestic": "Domestic Students",
    "fees_international": "International Students",
}


class HandbookSpider(scrapy.Spider):
    """Spider that fetches UNSW Handbook course and program pages."""

    name = "handbook_spider"
    allowed_domains = ["www.handbook.unsw.edu.au"]
    custom_settings = {
        "DOWNLOAD_DELAY": 2.0,  # Extra polite — robots.txt sets no Crawl-delay
        "CONCURRENT_REQUESTS": 2,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 2,
        "ROBOTSTXT_OBEY": True,
        "USER_AGENT": crawler_settings.USER_AGENT,
        # Always fetch fresh copies: lastmod already tells us what changed.
        "HTTPCACHE_ENABLED": False,
        "LOG_LEVEL": crawler_settings.LOG_LEVEL,
    }

    def __init__(self, pages=None, *args, **kwargs):
        """pages: {url: lastmod} to fetch, from the Handbook sitemap."""
        super().__init__(*args, **kwargs)
        self.pages = dict(pages or {})
        self.course_count = 0
        self.program_count = 0

    async def start(self):
        for url, lastmod in self.pages.items():
            if re.search(crawler_settings.HANDBOOK_COURSE_PATTERN, url):
                callback = self.parse_course
            else:
                callback = self.parse_program
            yield scrapy.Request(
                url, callback=callback, dont_filter=True,
                meta={"sitemap_url": url, "lastmod": lastmod},
            )

    def parse_course(self, response):
        """Extract structured data from a course page."""
        data = self._page_content(response)
        # Key pages by their sitemap URL (stable across redirects)
        url = response.meta["sitemap_url"]
        course_code = data.get("code", "")
        title = data.get("title", "")
        level = self._level(url)

        outcomes = sorted(
            data.get("unit_learning_outcomes") or [],
            key=lambda lo: str(lo.get("order", "")).zfill(3),
        )
        offering = data.get("offering_detail") or {}
        fees = offering.get("fees") or {}

        sections = {
            "Overview": self._html_to_text(data.get("description")),
            "Conditions for Enrolment / Prerequisites": "\n".join(
                self._html_to_text(rule.get("description"))
                for rule in data.get("enrolment_rules") or []
            ),
            "Course Outline": data.get("course_outline_url", ""),
            "Learning Outcomes": "\n".join(
                self._html_to_text(lo.get("description")) for lo in outcomes
            ),
            "Fees": "\n".join(
                f"{label}: ${fees[key]}"
                for key, label in FEE_LABELS.items() if fees.get(key)
            ),
        }
        content_parts = [f"{heading}: {text}" for heading, text in sections.items() if text.strip()]
        full_content = "\n\n".join(content_parts)

        if full_content.strip():
            self.course_count += 1
            self.logger.info(
                f"[Course {self.course_count}] {course_code}: {title} "
                f"({len(full_content)} chars)"
            )

            yield {
                "url": url,
                "type": "course",
                "course_code": course_code,
                "title": f"{course_code} — {title}" if course_code else title,
                "level": level,
                "uoc": data.get("credit_points", ""),
                "faculty": self._value(data, "parent_academic_org"),
                "school": self._value(data, "academic_org"),
                "offering_terms": offering.get("offering_terms", ""),
                "content": full_content,
                "sections": [
                    {"heading": part.split(":")[0], "content": part}
                    for part in content_parts
                ],
                "breadcrumbs": ["UNSW Handbook", level.title(), "Courses", course_code],
                "lastmod": response.meta["lastmod"],
                "last_crawled": datetime.now(timezone.utc).isoformat(),
                "meta_description": (
                    f"{course_code} {title} - {data.get('credit_points', '')} UOC "
                    f"- UNSW {level.title()}"
                ),
            }

    def parse_program(self, response):
        """Extract structured data from a program page."""
        data = self._page_content(response)
        url = response.meta["sitemap_url"]
        program_code = data.get("code", "")
        title = data.get("title", "")
        level = self._level(url)

        sections = {
            "Overview": self._html_to_text(data.get("description")),
            "Program Structure": self._html_to_text(data.get("structure_summary")),
            "Admission Requirements": "\n".join(
                self._html_to_text(req.get("description"))
                for group in data.get("entry_requirements_v2") or []
                for req in group.get("requirements") or []
            ),
            "Fees": self._html_to_text(data.get("fees_description")),
        }
        content_parts = [f"{heading}: {text}" for heading, text in sections.items() if text.strip()]
        full_content = "\n\n".join(content_parts)

        if full_content.strip():
            self.program_count += 1
            self.logger.info(
                f"[Program {self.program_count}] {program_code}: {title} "
                f"({len(full_content)} chars)"
            )

            yield {
                "url": url,
                "type": "program",
                "program_code": program_code,
                "title": f"Program {program_code} — {title}" if program_code else title,
                "level": level,
                "faculty": self._value(data, "parent_academic_org"),
                "duration": data.get("full_time_duration", ""),
                "content": full_content,
                "sections": [
                    {"heading": part.split(":")[0], "content": part}
                    for part in content_parts
                ],
                "breadcrumbs": ["UNSW Handbook", level.title(), "Programs", program_code],
                "lastmod": response.meta["lastmod"],
                "last_crawled": datetime.now(timezone.utc).isoformat(),
                "meta_description": f"Program {program_code} {title} - UNSW {level.title()}",
            }

    # --- Helper Methods ---

    def _extract_next_data(self, response):
        """Extract the __NEXT_DATA__ JSON from a Next.js SSR page."""
        try:
            match = re.search(
                r'<script\s+id="__NEXT_DATA__"\s+type="application/json">(.*?)</script>',
                response.text,
                re.DOTALL,
            )
            if match:
                return json.loads(match.group(1))
        except (json.JSONDecodeError, AttributeError):
            pass
        return {}

    def _page_content(self, response):
        """The course/program fields from the page's __NEXT_DATA__."""
        data = self._extract_next_data(response)
        content = data.get("props", {}).get("pageProps", {}).get("pageContent")
        if not content:
            self.logger.warning(f"No __NEXT_DATA__ page content: {response.url}")
        return content or {}

    def _level(self, url):
        if "/postgraduate/" in url:
            return "postgraduate"
        if "/research/" in url:
            return "research"
        return "undergraduate"

    def _value(self, data, field):
        """Read a {"value": ...} reference field, e.g. the owning school."""
        return (data.get(field) or {}).get("value") or ""

    def _html_to_text(self, html):
        """Turn a Handbook HTML snippet into plain text, one block per line."""
        if not html:
            return ""
        soup = BeautifulSoup(html, "lxml")
        for br in soup.find_all("br"):
            br.replace_with("\n")
        for li in soup.find_all("li"):
            li.insert(0, "- ")
        for block in soup.find_all(BLOCK_TAGS):
            block.append("\n")
        lines = (re.sub(r"\s+", " ", line).strip() for line in soup.get_text().split("\n"))
        return "\n".join(line for line in lines if line)


def select_pages(entries, year, subject_areas=None):
    """
    Keep the year's course and program pages from the sitemap entries. With
    subject_areas, keep only those areas' courses (programs have numeric
    codes, so they have no subject area).
    """
    areas = {area.upper() for area in subject_areas or ()}
    selected = {}
    for url, lastmod in entries.items():
        if f"/{year}/" not in url:
            continue
        if re.search(crawler_settings.HANDBOOK_COURSE_PATTERN, url):
            if areas and url.rsplit("/", 1)[1][:4] not in areas:
                continue
        elif areas or not re.search(crawler_settings.HANDBOOK_PROGRAM_PATTERN, url):
            continue
        selected[url] = lastmod
    return selected


def run_handbook_crawler(subject_areas=None, year=None):
    """
    Bring data/raw/handbook_pages.jsonl in line with the Handbook sitemap:
    fetch new or changed pages, keep unchanged ones, drop the rest.
    """
    from scrapy import signals
    from scrapy.crawler import CrawlerProcess

    from scraper.refresh import HANDBOOK_FILE, _read_jsonl, _write_jsonl
    from scraper.sitemap import fetch_sitemap

    year = year or crawler_settings.HANDBOOK_YEAR
    scope = f"{', '.join(subject_areas)} courses" if subject_areas else "courses and programs"

    print(f"Reading {crawler_settings.HANDBOOK_SITEMAP_URL}")
    wanted = select_pages(
        fetch_sitemap(crawler_settings.HANDBOOK_SITEMAP_URL), year, subject_areas
    )
    previous = _read_jsonl(HANDBOOK_FILE)
    stored = {p["url"]: p for p in previous if p["url"] in wanted}
    to_fetch = {
        url: lastmod for url, lastmod in wanted.items()
        if stored.get(url, {}).get("lastmod") != lastmod
    }
    print(
        f"{len(wanted)} {year} {scope}: {len(wanted) - len(to_fetch)} unchanged, "
        f"{len(to_fetch)} new or changed, {len(previous) - len(stored)} removed"
    )

    fetched = {}
    if to_fetch:
        delay = HandbookSpider.custom_settings["DOWNLOAD_DELAY"]
        print(
            f"Fetching {len(to_fetch)} pages, {delay:g}s apart "
            f"(about {len(to_fetch) * delay / 60:.0f} min)"
        )

        def collect(item, response, spider):
            fetched[item["url"]] = dict(item)

        process = CrawlerProcess(
            settings={
                "BOT_NAME": crawler_settings.BOT_NAME,
                "ROBOTSTXT_OBEY": True,
                "LOG_LEVEL": crawler_settings.LOG_LEVEL,
                "LOG_FORMAT": crawler_settings.LOG_FORMAT,
            }
        )
        crawler = process.create_crawler(HandbookSpider)
        crawler.signals.connect(collect, signal=signals.item_scraped)
        process.crawl(crawler, pages=to_fetch)
        process.start()
        print(f"Fetched {len(fetched)}/{len(to_fetch)} (failures are retried next run)")

    # Pages that failed keep their old copy and lastmod, so they're retried
    stored.update(fetched)
    _write_jsonl(HANDBOOK_FILE, [stored[url] for url in sorted(stored)])
    print(f"Saved {len(stored)} pages to {HANDBOOK_FILE}")


if __name__ == "__main__":
    import sys

    # Allow passing subject areas as arguments for targeted crawls
    # e.g.: python -m scraper.handbook_crawler COMP MATH ELEC
    areas = sys.argv[1:] if len(sys.argv) > 1 else None
    run_handbook_crawler(subject_areas=areas)
