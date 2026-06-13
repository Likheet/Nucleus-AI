"""
Refresh Script — Re-crawl UNSW pages and update the vector store.

Designed to be run on a schedule (weekly/monthly) to keep the knowledge
base current. Crawls both the main UNSW site AND the handbook.
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


def refresh(skip_main=False, skip_handbook=False, handbook_areas=None):
    """
    Full refresh: crawl → chunk → embed.

    Args:
        skip_main: Skip the main UNSW site crawl
        skip_handbook: Skip the handbook crawl
        handbook_areas: List of subject area codes for targeted handbook crawl
                       (e.g., ["COMP", "MATH"]). None = all areas.
    """
    print("=" * 60)
    print("NUCLEUS AI — Knowledge Base Refresh")
    print("=" * 60)

    # Step 1: Crawl main UNSW site
    if not skip_main:
        print("\n📥 Step 1/4: Crawling main UNSW website...")
        print("-" * 40)
        from scraper.crawler import run_crawler
        run_crawler()
    else:
        print("\n⏭️  Step 1/4: Skipping main site crawl")

    # Step 2: Crawl handbook
    if not skip_handbook:
        print("\n📚 Step 2/4: Crawling UNSW Handbook...")
        print("-" * 40)
        from scraper.handbook_crawler import run_handbook_crawler
        run_handbook_crawler(subject_areas=handbook_areas)
    else:
        print("\n⏭️  Step 2/4: Skipping handbook crawl")

    # Step 3: Chunk all data
    print("\n✂️  Step 3/4: Chunking all pages...")
    print("-" * 40)
    from scraper.chunker import process_all_pages
    chunks = process_all_pages()

    # Step 4: Embed and index
    print("\n🧮 Step 4/4: Embedding and indexing...")
    print("-" * 40)
    try:
        from backend.vector_store import VectorStore
        store = VectorStore()
        store.index_chunks(chunks)
        print(f"\n✅ Refresh complete! {len(chunks)} chunks indexed.")
    except ImportError:
        print("⚠️  Backend not set up yet. Chunks saved to disk.")
        print("   Run 'python -m backend.vector_store' to index them.")

    print("=" * 60)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Refresh Nucleus AI knowledge base")
    parser.add_argument(
        "--skip-main", action="store_true",
        help="Skip crawling the main UNSW site"
    )
    parser.add_argument(
        "--skip-handbook", action="store_true",
        help="Skip crawling the handbook"
    )
    parser.add_argument(
        "--handbook-only", action="store_true",
        help="Only crawl the handbook (skip main site)"
    )
    parser.add_argument(
        "--areas", nargs="*", default=None,
        help="Specific subject areas for handbook (e.g., COMP MATH ELEC)"
    )

    args = parser.parse_args()

    if args.handbook_only:
        args.skip_main = True

    refresh(
        skip_main=args.skip_main,
        skip_handbook=args.skip_handbook,
        handbook_areas=args.areas,
    )
