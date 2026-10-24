"""
Prebuilt Index — package a built knowledge base, or download one.

The scheduled GitHub Actions workflow builds the index and publishes it as
nucleus-index.tar.gz on the `index-latest` release. When the server starts
without a local index, it downloads that archive instead of crawling.

    python -m backend.index_bundle pack nucleus-index.tar.gz
    python -m backend.index_bundle download
"""

import os
import shutil
import sys
import tarfile
import tempfile
from pathlib import Path

import httpx
from dotenv import load_dotenv

from backend.vector_store import CHROMA_PERSIST_DIR
from scraper import settings as crawler_settings

load_dotenv()

# Set INDEX_URL to an empty string to never download.
INDEX_URL = os.getenv(
    "INDEX_URL",
    "https://github.com/Likheet/Nucleus-AI/releases/download/index-latest/nucleus-index.tar.gz",
)

CHUNKS_FILE = Path(crawler_settings.CHUNKS_DIR) / "all_chunks.jsonl"

# Archive member name → local path
PARTS = {
    "manifest.json": Path(crawler_settings.MANIFEST_PATH),
    "chunks/all_chunks.jsonl": CHUNKS_FILE,
    "raw/all_pages.jsonl": Path(crawler_settings.RAW_DATA_DIR) / "all_pages.jsonl",
    "chroma_db": Path(CHROMA_PERSIST_DIR),
}


def has_local_index():
    """True if a chunk file and a vector store are already on disk."""
    return CHUNKS_FILE.exists() and (Path(CHROMA_PERSIST_DIR) / "chroma.sqlite3").exists()


def pack(out_path):
    """Write the local index to a .tar.gz archive."""
    with tarfile.open(out_path, "w:gz") as tar:
        for name, path in PARTS.items():
            tar.add(path, arcname=name)
    print(f"Packed index into {out_path} ({Path(out_path).stat().st_size / 1e6:.1f} MB)")


def download(url=None):
    """Download an index archive and put its parts in place."""
    url = url or INDEX_URL
    data_dir = Path(crawler_settings.DATA_DIR)
    data_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(dir=data_dir) as tmp:
        archive = Path(tmp) / "index.tar.gz"
        with httpx.stream("GET", url, follow_redirects=True, timeout=120.0) as response:
            response.raise_for_status()
            with open(archive, "wb") as f:
                for chunk in response.iter_bytes():
                    f.write(chunk)

        extracted = Path(tmp) / "index"
        with tarfile.open(archive) as tar:
            tar.extractall(extracted, filter="data")

        for name, dest in PARTS.items():
            src = extracted / name
            if not src.exists():
                raise FileNotFoundError(f"{name} missing from index archive")
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.is_dir():
                shutil.rmtree(dest)
            elif dest.exists():
                dest.unlink()
            shutil.move(str(src), str(dest))


def ensure_index():
    """
    Download the prebuilt index if there is no local one.

    Returns True if an index is available afterwards.
    """
    if has_local_index():
        return True
    if not INDEX_URL:
        print("No local index and INDEX_URL is empty; run `python -m scraper.refresh`.")
        return False

    print(f"📦 No local index found. Downloading {INDEX_URL} ...")
    try:
        download()
    except (httpx.HTTPError, tarfile.TarError, OSError) as e:
        print(f"⚠️  Could not download the prebuilt index: {e}")
        print("   Build one locally with `python -m scraper.refresh`.")
        return False
    print("✅ Prebuilt index ready.")
    return True


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "pack":
        pack(sys.argv[2] if len(sys.argv) > 2 else "nucleus-index.tar.gz")
    elif command == "download":
        try:
            download(sys.argv[2] if len(sys.argv) > 2 else None)
        except (httpx.HTTPError, tarfile.TarError, OSError) as e:
            sys.exit(f"Download failed: {e}")
        print("Index downloaded.")
    else:
        sys.exit("Usage: python -m backend.index_bundle pack [FILE] | download [URL]")
