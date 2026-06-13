"""
Vector Store — ChromaDB wrapper for storing and searching document embeddings.

ChromaDB runs in embedded mode (in-process) — no separate server needed.
Just `pip install chromadb` and it works. Data persists to disk automatically.
"""

import json
import os
from pathlib import Path

import chromadb
from dotenv import load_dotenv

from backend.embedder import embed_texts

load_dotenv()

CHROMA_PERSIST_DIR = os.getenv(
    "CHROMA_PERSIST_DIR",
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "chroma_db"),
)
COLLECTION_NAME = "unsw_pages"


class VectorStore:
    """ChromaDB-backed vector store for UNSW document chunks."""

    def __init__(self, persist_dir=None):
        """
        Initialize the vector store.

        Args:
            persist_dir: Directory for ChromaDB persistent storage.
                         Defaults to ./data/chroma_db
        """
        self.persist_dir = persist_dir or CHROMA_PERSIST_DIR
        Path(self.persist_dir).mkdir(parents=True, exist_ok=True)

        self.client = chromadb.PersistentClient(path=self.persist_dir)
        self.collection = self.client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},  # Use cosine similarity
        )
        print(
            f"ChromaDB initialized. Collection '{COLLECTION_NAME}' "
            f"has {self.collection.count()} documents."
        )

    def index_chunks(self, chunks, batch_size=100):
        """
        Embed and store chunks in ChromaDB.

        Args:
            chunks: List of chunk dicts with 'id', 'text', and 'metadata' keys
            batch_size: Number of chunks to process at once
        """
        if not chunks:
            print("No chunks to index.")
            return

        print(f"Indexing {len(chunks)} chunks...")

        # Process in batches
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i : i + batch_size]

            ids = [c["id"] for c in batch]
            texts = [c["text"] for c in batch]
            metadatas = [c["metadata"] for c in batch]

            # Generate embeddings
            embeddings = embed_texts(texts, show_progress=False)

            # Upsert into ChromaDB (handles duplicates)
            self.collection.upsert(
                ids=ids,
                embeddings=embeddings.tolist(),
                documents=texts,
                metadatas=metadatas,
            )

            progress = min(i + batch_size, len(chunks))
            print(f"  Indexed {progress}/{len(chunks)} chunks")

        print(f"Indexing complete! Total: {self.collection.count()} documents")

    def search(self, query_text, n_results=5, where=None):
        """
        Search for chunks similar to the query.

        Args:
            query_text: The search query string
            n_results: Number of results to return
            where: Optional metadata filter dict (e.g. {"title": "Enrolment"})

        Returns:
            List of dicts with keys: text, metadata, distance
        """
        from backend.embedder import embed_query

        query_embedding = embed_query(query_text)

        search_kwargs = {
            "query_embeddings": [query_embedding.tolist()],
            "n_results": n_results,
            "include": ["documents", "metadatas", "distances"],
        }
        if where:
            search_kwargs["where"] = where

        results = self.collection.query(**search_kwargs)

        # Format results
        formatted = []
        if results and results["documents"]:
            for doc, meta, dist in zip(
                results["documents"][0],
                results["metadatas"][0],
                results["distances"][0],
            ):
                formatted.append({
                    "text": doc,
                    "metadata": meta,
                    "distance": dist,
                    "similarity": 1 - dist,  # Convert distance to similarity
                })

        return formatted

    def get_stats(self):
        """Get statistics about the vector store."""
        count = self.collection.count()

        # Get sample of unique URLs
        sample = self.collection.peek(limit=10)
        urls = set()
        if sample and sample["metadatas"]:
            for meta in sample["metadatas"]:
                if "url" in meta:
                    urls.add(meta["url"])

        return {
            "total_chunks": count,
            "sample_urls": list(urls),
            "persist_dir": self.persist_dir,
        }

    def clear(self):
        """Delete all documents from the collection."""
        self.client.delete_collection(COLLECTION_NAME)
        self.collection = self.client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
        print("Collection cleared.")


def index_from_file(chunks_file=None):
    """Index chunks from the chunker's output file."""
    from scraper import settings as crawler_settings

    if chunks_file is None:
        chunks_file = Path(crawler_settings.CHUNKS_DIR) / "all_chunks.jsonl"

    chunks_path = Path(chunks_file)
    if not chunks_path.exists():
        print(f"ERROR: Chunks file not found: {chunks_path}")
        print("Run the chunker first: python -m scraper.chunker")
        return

    chunks = []
    with open(chunks_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    chunks.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    store = VectorStore()
    store.index_chunks(chunks)
    return store


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "search":
        # Quick search test
        query = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else "How do I enrol?"
        store = VectorStore()
        results = store.search(query)
        print(f"\nSearch: '{query}'")
        print("=" * 60)
        for i, r in enumerate(results, 1):
            print(f"\n--- Result {i} (similarity: {r['similarity']:.4f}) ---")
            print(f"URL: {r['metadata'].get('url', 'N/A')}")
            print(f"Title: {r['metadata'].get('title', 'N/A')}")
            print(f"Text: {r['text'][:200]}...")
    else:
        # Index from file
        index_from_file()
