"""
UNSW Handbook Crawler — Specialized spider for handbook.unsw.edu.au

The handbook is a Next.js SSR application. This means:
  1. The HTML contains a <script id="__NEXT_DATA__"> tag with the full page data as JSON
  2. We can extract structured course/program data directly — no browser needed
  3. Course/program URLs follow predictable patterns

This spider generates URLs programmatically for all subject areas and extracts
structured fields (course code, name, UOC, prerequisites, description, etc.)
so they can be chunked as atomic units rather than getting ripped apart.
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import scrapy
from bs4 import BeautifulSoup

from scraper import settings as crawler_settings


class HandbookSpider(scrapy.Spider):
    """Spider that crawls UNSW Handbook course and program pages."""

    name = "handbook_spider"
    allowed_domains = ["www.handbook.unsw.edu.au"]
    custom_settings = {
        "DOWNLOAD_DELAY": 2.0,  # Extra polite — handbook is a smaller site
        "CONCURRENT_REQUESTS": 2,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 2,
        "ROBOTSTXT_OBEY": True,
        "USER_AGENT": crawler_settings.USER_AGENT,
        "HTTPCACHE_ENABLED": crawler_settings.HTTPCACHE_ENABLED,
        "HTTPCACHE_EXPIRATION_SECS": crawler_settings.HTTPCACHE_EXPIRATION_SECS,
        "HTTPCACHE_DIR": crawler_settings.HTTPCACHE_DIR,
        "LOG_LEVEL": crawler_settings.LOG_LEVEL,
        "ITEM_PIPELINES": {
            "scraper.handbook_crawler.HandbookJsonPipeline": 300,
        },
    }

    def __init__(self, subject_areas=None, year=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.year = year or crawler_settings.HANDBOOK_YEAR
        self.subject_areas = subject_areas or crawler_settings.HANDBOOK_SUBJECT_AREAS
        self.visited = set()
        self.course_count = 0
        self.program_count = 0

    def start_requests(self):
        """Generate requests for all subject area browse pages."""
        base = crawler_settings.HANDBOOK_BASE
        year = self.year

        # Start with browse/listing pages to discover courses and programs
        for url in crawler_settings.HANDBOOK_START_URLS:
            yield scrapy.Request(url, callback=self.parse_listing)

        # Also generate direct course URLs for every subject area
        # Each subject area page lists courses for that area
        for area in self.subject_areas:
            # Undergraduate courses
            url = f"{base}/undergraduate/courses/{year}?query={area}"
            yield scrapy.Request(url, callback=self.parse_listing, meta={"area": area})
            # Postgraduate courses
            url = f"{base}/postgraduate/courses/{year}?query={area}"
            yield scrapy.Request(url, callback=self.parse_listing, meta={"area": area})

    def parse_listing(self, response):
        """Parse a listing/browse page and follow links to individual courses."""
        # Follow links to individual course and program pages
        for href in response.css("a::attr(href)").getall():
            if not href:
                continue

            # Match course URLs: /undergraduate/courses/2026/COMP1511
            if re.search(crawler_settings.HANDBOOK_COURSE_PATTERN, href):
                full_url = response.urljoin(href)
                if full_url not in self.visited:
                    self.visited.add(full_url)
                    yield scrapy.Request(full_url, callback=self.parse_course)

            # Match program URLs: /undergraduate/programs/2026/3778
            elif re.search(crawler_settings.HANDBOOK_PROGRAM_PATTERN, href):
                full_url = response.urljoin(href)
                if full_url not in self.visited:
                    self.visited.add(full_url)
                    yield scrapy.Request(full_url, callback=self.parse_program)

    def parse_course(self, response):
        """Extract structured data from a course page."""
        data = self._extract_next_data(response)
        soup = BeautifulSoup(response.text, "lxml")

        url = response.url

        # Extract course code from URL (e.g., COMP1511)
        code_match = re.search(r"/([A-Z]{4}\d{4})$", url)
        course_code = code_match.group(1) if code_match else ""

        # Extract the level from URL
        level = "undergraduate"
        if "/postgraduate/" in url:
            level = "postgraduate"
        elif "/research/" in url:
            level = "research"

        # Try to get title from the page
        title = self._get_text(soup, "h2[data-testid='ai-header']") or ""
        if not title:
            title_tag = soup.find("title")
            if title_tag:
                title = title_tag.get_text(strip=True)
                title = re.sub(r"^Handbook\s*[-–—]\s*", "", title)

        # Extract all text content sections
        content_parts = []

        # Overview / Description
        overview = self._extract_section_text(soup, "Overview")
        if overview:
            content_parts.append(f"Overview: {overview}")

        # Conditions for Enrolment (prerequisites)
        conditions = self._extract_section_text(soup, "Conditions for Enrolment")
        if conditions:
            content_parts.append(f"Conditions for Enrolment / Prerequisites: {conditions}")

        # Course Outline
        outline = self._extract_section_text(soup, "Course Outline")
        if outline:
            content_parts.append(f"Course Outline: {outline}")

        # Learning Outcomes
        outcomes = self._extract_section_text(soup, "Learning Outcomes")
        if outcomes:
            content_parts.append(f"Learning Outcomes: {outcomes}")

        # Fees
        fees = self._extract_section_text(soup, "Fees")
        if fees:
            content_parts.append(f"Fees: {fees}")

        # If we couldn't find structured sections, grab all body text
        if not content_parts:
            main_el = soup.find("main") or soup.find("body")
            if main_el:
                # Remove nav, header, footer, scripts
                for tag in main_el.find_all(["script", "style", "nav", "footer", "header"]):
                    tag.decompose()
                body_text = self._clean_text(main_el.get_text(separator="\n"))
                if body_text:
                    content_parts.append(body_text)

        # UOC (Units of Credit)
        uoc = ""
        uoc_match = re.search(r"(\d+)\s*Units?\s*of\s*Credit", response.text)
        if uoc_match:
            uoc = uoc_match.group(1)

        # Faculty/School
        faculty = self._extract_attribute(soup, "Faculty")
        school = self._extract_attribute(soup, "School")

        # Offering Terms
        offering = self._extract_attribute(soup, "Offering Terms") or \
                   self._extract_attribute(soup, "Term")

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
                "uoc": uoc,
                "faculty": faculty,
                "school": school,
                "offering_terms": offering,
                "content": full_content,
                "sections": [
                    {"heading": part.split(":")[0] if ":" in part else "",
                     "content": part}
                    for part in content_parts
                ],
                "breadcrumbs": ["UNSW Handbook", level.title(), "Courses", course_code],
                "last_crawled": datetime.now(timezone.utc).isoformat(),
                "meta_description": f"{course_code} {title} - {uoc} UOC - UNSW {level.title()}",
            }

    def parse_program(self, response):
        """Extract structured data from a program page."""
        soup = BeautifulSoup(response.text, "lxml")
        url = response.url

        # Extract program code from URL
        code_match = re.search(r"/(\d{4})$", url)
        program_code = code_match.group(1) if code_match else ""

        level = "undergraduate"
        if "/postgraduate/" in url:
            level = "postgraduate"
        elif "/research/" in url:
            level = "research"

        title = self._get_text(soup, "h2[data-testid='ai-header']") or ""
        if not title:
            title_tag = soup.find("title")
            if title_tag:
                title = title_tag.get_text(strip=True)
                title = re.sub(r"^Handbook\s*[-–—]\s*", "", title)

        content_parts = []

        # Overview
        overview = self._extract_section_text(soup, "Overview")
        if overview:
            content_parts.append(f"Overview: {overview}")

        # Program Structure
        structure = self._extract_section_text(soup, "Program Structure")
        if structure:
            content_parts.append(f"Program Structure: {structure}")

        # Admission Requirements
        admission = self._extract_section_text(soup, "Admission Requirements")
        if admission:
            content_parts.append(f"Admission Requirements: {admission}")

        # Fees
        fees = self._extract_section_text(soup, "Fees")
        if fees:
            content_parts.append(f"Fees: {fees}")

        # Fallback
        if not content_parts:
            main_el = soup.find("main") or soup.find("body")
            if main_el:
                for tag in main_el.find_all(["script", "style", "nav", "footer", "header"]):
                    tag.decompose()
                body_text = self._clean_text(main_el.get_text(separator="\n"))
                if body_text:
                    content_parts.append(body_text)

        # Duration
        duration = self._extract_attribute(soup, "Duration")
        faculty = self._extract_attribute(soup, "Faculty")

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
                "faculty": faculty,
                "duration": duration,
                "content": full_content,
                "sections": [
                    {"heading": part.split(":")[0] if ":" in part else "",
                     "content": part}
                    for part in content_parts
                ],
                "breadcrumbs": ["UNSW Handbook", level.title(), "Programs", program_code],
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

    def _extract_section_text(self, soup, section_name):
        """Extract text content from a named section/accordion."""
        # Try finding by heading text
        for tag in soup.find_all(["h2", "h3", "h4", "button", "div"]):
            text = tag.get_text(strip=True)
            if section_name.lower() in text.lower():
                # Get the next sibling container or parent's content
                parent = tag.find_parent(
                    class_=re.compile(r"Accordion|Card|Section|ReadMore", re.I)
                )
                if parent:
                    content = self._clean_text(parent.get_text(separator="\n"))
                    # Remove the heading itself from the content
                    content = content.replace(text, "", 1).strip()
                    if content and len(content) > 20:
                        return content

        # Try by data-testid or aria-label
        el = soup.find(attrs={"data-testid": re.compile(section_name, re.I)})
        if el:
            return self._clean_text(el.get_text(separator="\n"))

        return ""

    def _extract_attribute(self, soup, attribute_name):
        """Extract a key-value attribute (e.g., 'Faculty: Engineering')."""
        for tag in soup.find_all(string=re.compile(attribute_name, re.I)):
            parent = tag.find_parent()
            if parent:
                # The value is usually in a sibling or nearby element
                next_el = parent.find_next_sibling()
                if next_el:
                    val = next_el.get_text(strip=True)
                    if val and len(val) < 200:
                        return val
        return ""

    def _get_text(self, soup, selector):
        """Get text from a CSS selector, or empty string."""
        el = soup.select_one(selector)
        return el.get_text(strip=True) if el else ""

    def _clean_text(self, text):
        """Normalize whitespace and remove noise."""
        if not text:
            return ""
        lines = text.split("\n")
        cleaned = []
        for line in lines:
            line = re.sub(r"\s+", " ", line).strip()
            if line and len(line) > 3:
                cleaned.append(line)
        deduped = []
        for line in cleaned:
            if not deduped or line != deduped[-1]:
                deduped.append(line)
        return "\n".join(deduped)


class HandbookJsonPipeline:
    """Write handbook items to a separate JSONL file."""

    def open_spider(self, spider):
        self.output_dir = Path(crawler_settings.RAW_DATA_DIR)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.items_file = self.output_dir / "handbook_pages.jsonl"
        self.file = open(self.items_file, "w", encoding="utf-8")
        self.count = 0

    def close_spider(self, spider):
        self.file.close()
        spider.logger.info(
            f"Handbook crawl complete! {self.count} items saved to {self.items_file}"
        )

    def process_item(self, item, spider):
        line = json.dumps(dict(item), ensure_ascii=False) + "\n"
        self.file.write(line)
        self.count += 1
        return item


def run_handbook_crawler(subject_areas=None, year=None):
    """Run the Handbook spider from the command line."""
    from scrapy.crawler import CrawlerProcess

    Path(crawler_settings.RAW_DATA_DIR).mkdir(parents=True, exist_ok=True)

    process = CrawlerProcess(
        settings={
            "BOT_NAME": crawler_settings.BOT_NAME,
            "ROBOTSTXT_OBEY": True,
            "LOG_LEVEL": crawler_settings.LOG_LEVEL,
            "LOG_FORMAT": crawler_settings.LOG_FORMAT,
        }
    )

    kwargs = {}
    if subject_areas:
        kwargs["subject_areas"] = subject_areas
    if year:
        kwargs["year"] = year

    process.crawl(HandbookSpider, **kwargs)
    process.start()


if __name__ == "__main__":
    import sys

    # Allow passing subject areas as arguments for targeted crawls
    # e.g.: python -m scraper.handbook_crawler COMP MATH ELEC
    areas = sys.argv[1:] if len(sys.argv) > 1 else None
    run_handbook_crawler(subject_areas=areas)
