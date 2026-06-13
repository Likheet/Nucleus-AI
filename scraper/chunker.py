"""
Text Chunker — Splits crawled pages into overlapping chunks for embedding.

Each chunk preserves:
- Source URL (for citation)
- Page title
- Section heading (if any)
- Breadcrumb path

Uses LangChain's RecursiveCharacterTextSplitter for intelligent splitting
that respects paragraph and sentence boundaries.
"""

import json
import hashlib
from pathlib import Path

from langchain_text_splitters import RecursiveCharacterTextSplitter

from scraper import settings as crawler_settings


# --- Chunking Configuration ---
CHUNK_SIZE = 500       # Target chunk size in characters (~125 tokens)
CHUNK_OVERLAP = 80     # Overlap between chunks to preserve context
MIN_CHUNK_LENGTH = 50  # Skip chunks shorter than this


def create_splitter():
    """Create a text splitter optimized for web content."""
    return RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        length_function=len,
        separators=[
            "\n\n",   # Double newline (paragraph break)
            "\n",     # Single newline
            ". ",     # Sentence boundary
            "? ",     # Question boundary
            "! ",     # Exclamation boundary
            "; ",     # Semicolon
            ", ",     # Comma
            " ",      # Word boundary
            "",       # Character boundary (last resort)
        ],
        is_separator_regex=False,
    )


def generate_chunk_id(url, chunk_index):
    """Generate a deterministic ID for a chunk (for deduplication)."""
    raw = f"{url}::chunk::{chunk_index}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def chunk_handbook_page(page_data):
    """
    Chunk a handbook course/program page as an ATOMIC UNIT.

    Handbook pages are treated differently from regular web pages:
    - A course's code, name, UOC, and prerequisites MUST stay together
    - We build a structured text block with all key info, then split only if
      the total content exceeds 2x the normal chunk size
    - This prevents the chunker from separating "COMP1511" from its prerequisites

    Args:
        page_data: Dict from handbook_crawler with structured course/program fields.

    Returns:
        List of chunk dicts.
    """
    splitter = create_splitter()
    chunks = []
    url = page_data.get("url", "")
    title = page_data.get("title", "")
    page_type = page_data.get("type", "course")
    breadcrumbs = page_data.get("breadcrumbs", [])
    breadcrumb_path = " > ".join(breadcrumbs) if breadcrumbs else ""

    # Build the structured header that ALWAYS stays with every chunk
    header_parts = [title]
    if page_type == "course":
        code = page_data.get("course_code", "")
        uoc = page_data.get("uoc", "")
        level = page_data.get("level", "")
        faculty = page_data.get("faculty", "")
        school = page_data.get("school", "")
        offering = page_data.get("offering_terms", "")
        if uoc:
            header_parts.append(f"{uoc} Units of Credit")
        if level:
            header_parts.append(f"Level: {level.title()}")
        if faculty:
            header_parts.append(f"Faculty: {faculty}")
        if school:
            header_parts.append(f"School: {school}")
        if offering:
            header_parts.append(f"Offering: {offering}")
    elif page_type == "program":
        duration = page_data.get("duration", "")
        faculty = page_data.get("faculty", "")
        if duration:
            header_parts.append(f"Duration: {duration}")
        if faculty:
            header_parts.append(f"Faculty: {faculty}")

    header = "\n".join(header_parts)
    content = page_data.get("content", "")

    # Combine header + content
    full_text = f"{header}\n\n{content}"

    # If the full text fits in a larger chunk, keep it as ONE atomic chunk
    HANDBOOK_MAX_ATOMIC = CHUNK_SIZE * 3  # ~1500 chars — keep as single chunk
    if len(full_text) <= HANDBOOK_MAX_ATOMIC:
        chunk_id = generate_chunk_id(url, "atomic_0")
        chunks.append({
            "id": chunk_id,
            "text": full_text.strip(),
            "metadata": {
                "url": url,
                "title": title,
                "section_heading": "",
                "breadcrumbs": breadcrumb_path,
                "chunk_index": 0,
                "content_type": page_type,
            },
        })
    else:
        # Too long — split but prepend the header to EVERY chunk
        text_chunks = splitter.split_text(content)
        for i, chunk_text in enumerate(text_chunks):
            if len(chunk_text.strip()) < MIN_CHUNK_LENGTH:
                continue
            # Prepend header so every chunk has the course code / context
            enriched = f"{header}\n\n{chunk_text.strip()}"
            chunk_id = generate_chunk_id(url, f"hb_{i}")
            chunks.append({
                "id": chunk_id,
                "text": enriched,
                "metadata": {
                    "url": url,
                    "title": title,
                    "section_heading": "",
                    "breadcrumbs": breadcrumb_path,
                    "chunk_index": i,
                    "content_type": page_type,
                },
            })

    return chunks


def chunk_page(page_data):
    """
    Split a single page's content into chunks, preserving metadata.

    Automatically detects handbook pages (course/program) and uses
    handbook-specific atomic chunking to keep structured data together.

    Args:
        page_data: Dict with keys: url, title, content, sections, breadcrumbs, etc.

    Returns:
        List of chunk dicts ready for embedding.
    """
    # Route handbook pages to the specialized chunker
    if page_data.get("type") in ("course", "program"):
        return chunk_handbook_page(page_data)

    splitter = create_splitter()
    chunks = []
    url = page_data.get("url", "")
    title = page_data.get("title", "")
    breadcrumbs = page_data.get("breadcrumbs", [])
    breadcrumb_path = " > ".join(breadcrumbs) if breadcrumbs else ""

    sections = page_data.get("sections", [])

    if sections:
        # Split by section for better context preservation
        for section in sections:
            heading = section.get("heading", "")
            content = section.get("content", "")
            if not content or len(content) < MIN_CHUNK_LENGTH:
                continue

            # Prepend heading to content for context
            if heading:
                full_text = f"{heading}\n\n{content}"
            else:
                full_text = content

            text_chunks = splitter.split_text(full_text)

            for i, chunk_text in enumerate(text_chunks):
                if len(chunk_text.strip()) < MIN_CHUNK_LENGTH:
                    continue

                chunk_id = generate_chunk_id(url, f"{heading}_{i}")
                chunks.append({
                    "id": chunk_id,
                    "text": chunk_text.strip(),
                    "metadata": {
                        "url": url,
                        "title": title,
                        "section_heading": heading,
                        "breadcrumbs": breadcrumb_path,
                        "chunk_index": len(chunks),
                    },
                })
    else:
        # Fallback: split the entire page content
        content = page_data.get("content", "")
        if content and len(content) >= MIN_CHUNK_LENGTH:
            text_chunks = splitter.split_text(content)

            for i, chunk_text in enumerate(text_chunks):
                if len(chunk_text.strip()) < MIN_CHUNK_LENGTH:
                    continue

                chunk_id = generate_chunk_id(url, str(i))
                chunks.append({
                    "id": chunk_id,
                    "text": chunk_text.strip(),
                    "metadata": {
                        "url": url,
                        "title": title,
                        "section_heading": "",
                        "breadcrumbs": breadcrumb_path,
                        "chunk_index": i,
                    },
                })

    return chunks


def _process_jsonl_file(filepath, all_chunks, label="pages"):
    """Process a single JSONL file and append chunks to the list."""
    filepath = Path(filepath)
    if not filepath.exists():
        print(f"  Skipping {filepath.name} (not found)")
        return 0

    page_count = 0
    with open(filepath, "r", encoding="utf-8") as fin:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            try:
                page_data = json.loads(line)
            except json.JSONDecodeError:
                continue

            page_chunks = chunk_page(page_data)
            all_chunks.extend(page_chunks)
            page_count += 1

    print(f"  {label}: {page_count} pages → {len(all_chunks)} total chunks so far")
    return page_count


def process_all_pages(output_file=None):
    """
    Read all crawled data (main site + handbook) and generate chunks.

    Processes BOTH:
      - data/raw/all_pages.jsonl (main UNSW site)
      - data/raw/handbook_pages.jsonl (handbook courses/programs)

    Args:
        output_file: Path to write chunked output

    Returns:
        List of all chunks
    """
    if output_file is None:
        output_file = Path(crawler_settings.CHUNKS_DIR) / "all_chunks.jsonl"

    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    raw_dir = Path(crawler_settings.RAW_DATA_DIR)
    all_chunks = []
    total_pages = 0

    # Data files to process (order matters for dedup)
    data_files = [
        (raw_dir / "all_pages.jsonl", "Main site"),
        (raw_dir / "handbook_pages.jsonl", "Handbook"),
    ]

    found_any = False
    for filepath, label in data_files:
        if filepath.exists():
            found_any = True
            count = _process_jsonl_file(filepath, all_chunks, label)
            total_pages += count

    if not found_any:
        print("ERROR: No crawled data files found in data/raw/")
        print("Run the crawlers first:")
        print("  python -m scraper.crawler            # Main UNSW site")
        print("  python -m scraper.handbook_crawler    # Handbook")
        return []

    # Write chunks to output file
    with open(output_path, "w", encoding="utf-8") as fout:
        for chunk in all_chunks:
            fout.write(json.dumps(chunk, ensure_ascii=False) + "\n")

    print(f"\nChunking complete!")
    print(f"  Total pages processed: {total_pages}")
    print(f"  Total chunks: {len(all_chunks)}")
    print(f"  Output file: {output_path}")
    print(f"  Avg chunks/page: {len(all_chunks)/max(total_pages,1):.1f}")

    return all_chunks


if __name__ == "__main__":
    process_all_pages()
