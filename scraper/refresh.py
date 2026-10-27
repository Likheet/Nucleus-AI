"""
Refresh Script — Build or update the knowledge base from UNSW's sitemap.

One command does everything:

    python -m scraper.refresh

  1. Read the sitemap and pick the pages under SITEMAP_PATHS (/student).
  2. Compare each page's <lastmod> with data/manifest.json.
  3. Fetch only new or changed pages (robots.txt, its Crawl-delay, one
     request at a time).
  4. Re-chunk and re-embed pages whose content changed, and drop pages that
     left the sitemap.

The first run fetches every page (about 500 pages at UNSW's 10s Crawl-delay,
plus redirect hops, so roughly 2 hours). Later runs only fetch what changed. The scheduled
GitHub Actions workflow runs this weekly and publishes the result, so the
server can download a prebuilt index instead of crawling.
"""

import hashlib
import json
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper import settings as crawler_settings

PAGES_FILE = Path(crawler_settings.RAW_DATA_DIR) / "all_pages.jsonl"
# Optional: written by `python -m scraper.handbook_crawler`
HANDBOOK_FILE = Path(crawler_settings.RAW_DATA_DIR) / "handbook_pages.jsonl"
CHUNKS_FILE = Path(crawler_settings.CHUNKS_DIR) / "all_chunks.jsonl"
MANIFEST_FILE = Path(crawler_settings.MANIFEST_PATH)


def _read_jsonl(path):
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _write(path, text):
    """Write a file atomically, so an interrupted run never leaves half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _write_jsonl(path, rows):
    _write(path, "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))


def content_hash(page):
    """Hash the fields chunking uses, to tell real changes from lastmod bumps."""
    fields = {k: page.get(k) for k in ("title", "content", "sections", "breadcrumbs")}
    raw = json.dumps(fields, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def fetch_pages(urls, delay):
    """Fetch pages with UNSWSpider. Returns {sitemap_url: page_data}."""
    from scrapy import signals
    from scrapy.crawler import CrawlerProcess

    from scraper.crawler import UNSWSpider

    pages = {}

    def collect(item, response, spider):
        pages[item["url"]] = dict(item)

    process = CrawlerProcess(
        settings={
            "BOT_NAME": crawler_settings.BOT_NAME,
            "LOG_LEVEL": crawler_settings.LOG_LEVEL,
            "LOG_FORMAT": crawler_settings.LOG_FORMAT,
            "DOWNLOAD_DELAY": delay,
        }
    )
    crawler = process.create_crawler(UNSWSpider)
    crawler.signals.connect(collect, signal=signals.item_scraped)
    process.crawl(crawler, urls=urls)
    process.start()
    return pages


def refresh(limit=None, rechunk=False):
    """
    Incremental refresh: sitemap diff → fetch → chunk → embed.

    Args:
        limit: Fetch at most this many pages this run (the rest are picked
               up by later runs). None = no limit.
        rechunk: Re-chunk every stored page, e.g. after changing the chunker.
    """
    from backend.embedder import DEFAULT_MODEL
    from backend.vector_store import CHROMA_PERSIST_DIR, VectorStore
    from scraper.chunker import chunk_page
    from scraper.crawler import EXTRACTOR_VERSION
    from scraper.sitemap import crawl_delay, fetch_sitemap, select_pages

    started = time.time()
    now = datetime.now(timezone.utc).isoformat()

    print("=" * 60)
    print("NUCLEUS AI — Knowledge Base Refresh")
    print("=" * 60)

    # The manifest is the source of truth: stored pages and chunks that it
    # doesn't list (e.g. from an old crawl) are dropped.
    manifest = json.loads(MANIFEST_FILE.read_text()) if MANIFEST_FILE.exists() else {}
    known = manifest.get("pages", {})
    pages = {p["url"]: p for p in _read_jsonl(PAGES_FILE) if p["url"] in known}
    chunks_by_url = {}
    for chunk in _read_jsonl(CHUNKS_FILE):
        url = chunk["metadata"]["url"]
        if url in known:
            chunks_by_url.setdefault(url, []).append(chunk)

    # Step 1: Sitemap
    print(f"\n🗺️  Step 1/4: Reading {crawler_settings.SITEMAP_URL}")
    wanted = select_pages(fetch_sitemap())
    to_fetch = [
        url for url, lastmod in wanted.items()
        if url not in known
        or known[url]["lastmod"] != lastmod
        # Extracted by an older version of the crawler
        or known[url].get("extractor") != EXTRACTOR_VERSION
    ]
    outdated = sum(
        1 for url in to_fetch
        if url in known and known[url]["lastmod"] == wanted[url]
    )
    removed = [
        url for url, entry in known.items()
        if entry["source"] == "sitemap" and url not in wanted
    ]
    print(
        f"   {len(wanted)} pages under {', '.join(crawler_settings.SITEMAP_PATHS)}: "
        f"{len(wanted) - len(to_fetch)} unchanged, {len(to_fetch)} new or changed, "
        f"{len(removed)} removed"
    )
    if outdated:
        print(f"   ({outdated} of them because the extractor changed since they were fetched)")
    if limit is not None and len(to_fetch) > limit:
        to_fetch = to_fetch[:limit]
        print(f"   Fetching only the first {limit} this run (--limit)")

    # Step 2: Fetch
    fetched = {}
    if to_fetch:
        delay = crawl_delay()
        minutes = len(to_fetch) * delay / 60
        print(
            f"\n📥 Step 2/4: Fetching {len(to_fetch)} pages, {delay:g}s apart "
            f"(about {minutes:.0f} min)"
        )
        fetched = fetch_pages(to_fetch, delay)
        print(f"   Fetched {len(fetched)}/{len(to_fetch)} (failures are retried next run)")
    else:
        print("\n⏭️  Step 2/4: Nothing to fetch")

    # Step 3: Chunk what changed
    print("\n✂️  Step 3/4: Chunking changed pages...")
    changed = set()

    def record(url, page, lastmod, source):
        entry = known.get(url)
        h = content_hash(page)
        if entry is None or entry["content_hash"] != h:
            changed.add(url)
        known[url] = {
            "source": source,
            "lastmod": lastmod,
            "content_hash": h,
            "fetched_at": page.get("last_crawled", now),
        }

    for url, page in fetched.items():
        outdated_page = known.get(url, {}).get("extractor") != EXTRACTOR_VERSION
        record(url, page, wanted[url], "sitemap")
        known[url]["extractor"] = EXTRACTOR_VERSION
        if outdated_page:
            # Re-chunk even if the text is the same: extractor changes can
            # come with chunk format changes
            changed.add(url)
        pages[url] = page

    # Handbook pages (optional, from a separate handbook crawl)
    handbook = {p["url"]: p for p in _read_jsonl(HANDBOOK_FILE)}
    for url, page in handbook.items():
        record(url, page, page.get("lastmod", ""), "handbook")
    removed += [
        url for url, entry in known.items()
        if entry["source"] == "handbook" and url not in handbook
    ]

    for url in removed:
        known.pop(url, None)
        pages.pop(url, None)
        chunks_by_url.pop(url, None)

    if rechunk:
        changed.update(known)
    for url in changed:
        page = pages.get(url) or handbook.get(url)
        if page is not None:
            chunks_by_url[url] = chunk_page(page)
    print(f"   {len(changed)} pages with new content, {len(removed)} removed")

    # Step 4: Embed — reconcile the vector store with the chunk list by ID
    print("\n🧮 Step 4/4: Updating the vector store...")
    all_chunks = [c for url in sorted(chunks_by_url) for c in chunks_by_url[url]]
    if manifest.get("embedding_model", DEFAULT_MODEL) != DEFAULT_MODEL:
        print(f"   Embedding model changed to {DEFAULT_MODEL}; re-embedding everything")
        # Start from an empty store. Chroma's delete_collection leaves the old
        # vectors on disk, where they'd be packed into every index archive.
        shutil.rmtree(CHROMA_PERSIST_DIR, ignore_errors=True)
    store = VectorStore(model=DEFAULT_MODEL)
    stored_ids = store.ids()
    stale = stored_ids - {c["id"] for c in all_chunks}
    if stale:
        store.delete(stale)
    to_embed = [
        c for c in all_chunks
        if c["metadata"]["url"] in changed or c["id"] not in stored_ids
    ]
    store.index_chunks(to_embed)
    print(f"   Deleted {len(stale)} stale chunks, embedded {len(to_embed)}")

    # Save. The manifest goes last: if anything above fails, the next run
    # simply redoes the same pages.
    _write_jsonl(PAGES_FILE, [pages[url] for url in sorted(pages)])
    _write_jsonl(CHUNKS_FILE, all_chunks)
    manifest.update({
        "sitemap_url": crawler_settings.SITEMAP_URL,
        "sitemap_paths": crawler_settings.SITEMAP_PATHS,
        "embedding_model": DEFAULT_MODEL,
        "updated_at": now,
        "page_count": len(known),
        "chunk_count": len(all_chunks),
        "pages": dict(sorted(known.items())),
    })
    _write(MANIFEST_FILE, json.dumps(manifest, indent=1, ensure_ascii=False))

    print(
        f"\n✅ Refresh complete in {time.time() - started:.0f}s: "
        f"{len(known)} pages, {len(all_chunks)} chunks."
    )
    print("=" * 60)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Refresh Nucleus AI knowledge base")
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Fetch at most N pages this run (later runs fetch the rest)",
    )
    parser.add_argument(
        "--rechunk", action="store_true",
        help="Re-chunk and re-embed every stored page (after changing the chunker)",
    )
    args = parser.parse_args()

    refresh(limit=args.limit, rechunk=args.rechunk)
