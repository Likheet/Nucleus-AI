"""
Scrapy settings for the UNSW Nucleus AI web crawler.

Configures polite crawling with delays, depth limits, and output formats.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# --- Scrapy Core Settings ---
BOT_NAME = "nucleus_crawler"
SPIDER_MODULES = ["scraper"]
NEWSPIDER_MODULE = "scraper"

# --- Polite Crawling ---
# Be respectful to UNSW's servers
ROBOTSTXT_OBEY = True
DOWNLOAD_DELAY = float(os.getenv("CRAWL_DELAY", "1.5"))
CONCURRENT_REQUESTS = 4  # Don't overwhelm the server
CONCURRENT_REQUESTS_PER_DOMAIN = 2

# --- Depth & Scope ---
DEPTH_LIMIT = 6  # Don't go more than 6 links deep
MAX_PAGES = int(os.getenv("MAX_PAGES", "5000"))
CLOSESPIDER_PAGECOUNT = MAX_PAGES

# --- Allowed Domains ---
ALLOWED_DOMAINS = [
    d.strip()
    for d in os.getenv(
        "ALLOWED_DOMAINS",
        "www.unsw.edu.au,student.unsw.edu.au,www.handbook.unsw.edu.au",
    ).split(",")
]

# --- Start URLs ---
# Focused on student-relevant pages (main UNSW site)
START_URLS = [
    "https://www.unsw.edu.au/current-students",
    "https://www.unsw.edu.au/study",
    "https://www.unsw.edu.au/current-students/enrolment",
    "https://www.unsw.edu.au/current-students/academic-life",
    "https://www.unsw.edu.au/current-students/student-support",
    "https://www.unsw.edu.au/current-students/essentials",
    "https://www.unsw.edu.au/current-students/campus-life",
    "https://www.unsw.edu.au/current-students/graduation",
    "https://www.unsw.edu.au/study/how-to-apply",
    "https://www.unsw.edu.au/study/fees",
    "https://www.unsw.edu.au/study/international-students",
]

# --- Handbook Configuration ---
HANDBOOK_YEAR = os.getenv("HANDBOOK_YEAR", "2026")
HANDBOOK_BASE = "https://www.handbook.unsw.edu.au"

# All major UNSW subject area codes for programmatic course crawling
HANDBOOK_SUBJECT_AREAS = [
    # Engineering
    "COMP", "ELEC", "ENGG", "MECH", "CVEN", "MMAN", "MTRN", "SENG",
    "DESN", "MINE", "PTRL", "SOMA", "FOOD", "CEIC", "MANF", "SOLA",
    # Science
    "MATH", "PHYS", "CHEM", "BIOS", "BIOL", "PSYC", "AVIA", "DATA",
    "GEOS", "MSCI", "OPTM", "PATH", "SCIF", "MATS",
    # Business
    "ACCT", "FINS", "MARK", "MGMT", "COMM", "ECON", "INFS", "TABL",
    "ACTL", "RISK",
    # Arts & Social Sciences
    "ARTS", "HIST", "MDIA", "POLS", "SOCI", "LING", "PHIL", "MUSC",
    "MODL", "EDST", "SRAP",
    # Law
    "LAWS", "JURD",
    # Medicine & Health
    "MFAC", "MDCN", "PHAR", "PHCM", "PUBH", "HDAT", "HEAL", "NURS",
    "SWCH",
    # Architecture & Built Environment
    "ARCH", "BENV", "IDES", "PLAN", "LAND", "CONS",
    # General / Cross-faculty
    "GENL", "GENC",
]

# Handbook start URLs — browse pages that list all courses/programs
HANDBOOK_START_URLS = [
    f"{HANDBOOK_BASE}/",
    f"{HANDBOOK_BASE}/undergraduate/courses/{HANDBOOK_YEAR}",
    f"{HANDBOOK_BASE}/postgraduate/courses/{HANDBOOK_YEAR}",
    f"{HANDBOOK_BASE}/undergraduate/programs/{HANDBOOK_YEAR}",
    f"{HANDBOOK_BASE}/postgraduate/programs/{HANDBOOK_YEAR}",
    f"{HANDBOOK_BASE}/research/programs/{HANDBOOK_YEAR}",
]

# --- Output ---
RAW_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "raw")
CHUNKS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "chunks")

# --- User Agent ---
USER_AGENT = (
    "NucleusAI-Bot/1.0 "
    "(UNSW Student Project; +https://github.com/nucleus-ai; "
    "contact@example.com)"
)

# --- Response Handling ---
HTTPERROR_ALLOWED_CODES = []  # Only process 200 OK responses
RETRY_TIMES = 2
RETRY_HTTP_CODES = [500, 502, 503, 504, 408, 429]

# --- Caching (speeds up re-crawls during development) ---
HTTPCACHE_ENABLED = True
HTTPCACHE_EXPIRATION_SECS = 86400  # 24 hours
HTTPCACHE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), ".scrapy", "httpcache"
)

# --- Logging ---
LOG_LEVEL = "INFO"
LOG_FORMAT = "%(asctime)s [%(name)s] %(levelname)s: %(message)s"

# --- Item Pipelines ---
ITEM_PIPELINES = {
    "scraper.crawler.JsonWriterPipeline": 300,
}

# --- URL filtering ---
# Skip these file types and URL patterns
IGNORED_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".zip", ".rar", ".tar", ".gz",
    ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".ico",
    ".mp3", ".mp4", ".avi", ".mov", ".wmv",
    ".css", ".js", ".woff", ".woff2", ".ttf", ".eot",
}

IGNORED_URL_PATTERNS = [
    "/search",
    "/login",
    "/logout",
    "/api/",
    "/feeds/",
    "/print/",
    "?page=",
    "#",
    "mailto:",
    "tel:",
    "javascript:",
]

# --- Handbook URL Patterns ---
# Patterns to identify handbook course/program pages for special extraction
HANDBOOK_COURSE_PATTERN = r"/(?:undergraduate|postgraduate|research)/courses/\d{4}/[A-Z]{4}\d{4}"
HANDBOOK_PROGRAM_PATTERN = r"/(?:undergraduate|postgraduate|research)/programs/\d{4}/\d{4}"
